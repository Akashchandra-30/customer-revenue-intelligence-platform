-- =============================================================================
-- CORE layer: conformed star schema.
-- Written in Snowflake SQL; the local runner transpiles it to DuckDB with sqlglot
-- so the exact same logic is tested without a Snowflake account.
-- =============================================================================

CREATE OR REPLACE TABLE core.dim_customer AS
SELECT
    customer_id,
    first_name,
    last_name,
    first_name || ' ' || last_name                   AS full_name,
    email,
    country,
    segment,
    acquisition_channel,
    CAST(signup_date AS DATE)                        AS signup_date,
    CAST(DATE_TRUNC('month', signup_date) AS DATE)   AS signup_month
FROM raw.customers;

CREATE OR REPLACE TABLE core.dim_product AS
SELECT
    product_id,
    product_name,
    category,
    list_price_usd
FROM raw.products;

-- Line-level fact: converts local-currency amounts to USD and applies the order discount
CREATE OR REPLACE TABLE core.fct_order_items AS
SELECT
    i.order_id,
    i.line_number,
    i.product_id,
    p.category,
    o.customer_id,
    CAST(DATE_TRUNC('month', o.order_ts) AS DATE)    AS order_month,
    o.status,
    o.currency,
    i.quantity,
    i.unit_price                                     AS unit_price_local,
    ROUND(i.quantity * i.unit_price, 2)              AS line_amount_local,
    ROUND(i.quantity * i.unit_price * fx.rate_to_usd, 2) AS line_amount_usd,
    CASE
        WHEN o.status = 'completed'
            THEN ROUND(i.quantity * i.unit_price * fx.rate_to_usd * (1 - o.discount_pct), 2)
        ELSE 0
    END                                              AS net_revenue_usd
FROM raw.order_items AS i
JOIN raw.orders      AS o  ON o.order_id = i.order_id
JOIN raw.fx_rates    AS fx ON fx.currency = o.currency
JOIN raw.products    AS p  ON p.product_id = i.product_id;

-- Order-level fact
CREATE OR REPLACE TABLE core.fct_orders AS
WITH order_totals AS (
    SELECT
        order_id,
        COUNT(*)              AS line_count,
        SUM(quantity)         AS units,
        SUM(line_amount_usd)  AS gross_amount_usd,
        SUM(net_revenue_usd)  AS net_revenue_usd
    FROM core.fct_order_items
    GROUP BY order_id
)
SELECT
    o.order_id,
    o.customer_id,
    o.order_ts,
    CAST(o.order_ts AS DATE)                          AS order_date,
    CAST(DATE_TRUNC('month', o.order_ts) AS DATE)     AS order_month,
    o.status,
    o.sales_channel,
    o.currency,
    o.discount_pct,
    t.line_count,
    t.units,
    t.gross_amount_usd,
    ROUND(t.gross_amount_usd * o.discount_pct, 2)     AS discount_amount_usd,
    t.net_revenue_usd,
    -- 1 = customer's first completed purchase; NULL for refunded/cancelled orders
    CASE
        WHEN o.status = 'completed' THEN
            ROW_NUMBER() OVER (
                PARTITION BY o.customer_id, o.status = 'completed'
                ORDER BY o.order_ts, o.order_id
            )
    END                                               AS completed_order_seq
FROM raw.orders   AS o
JOIN order_totals AS t ON t.order_id = o.order_id;
