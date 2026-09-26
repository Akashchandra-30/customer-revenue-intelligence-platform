-- =============================================================================
-- ANALYTICS layer: revenue trends, customer lifetime value, retention and
-- segmentation. These views are what the Power BI model imports.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Monthly revenue trend: MoM / YoY growth, rolling 3-month, YTD and cumulative.
-- (LAG offsets assume one row per month, which holds for a trading business.)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.monthly_revenue AS
WITH monthly AS (
    SELECT
        order_month,
        SUM(net_revenue_usd)                                             AS revenue_usd,
        COUNT(*)                                                         AS orders,
        COUNT(DISTINCT customer_id)                                      AS active_customers,
        COUNT(DISTINCT CASE WHEN completed_order_seq = 1 THEN customer_id END) AS new_customers
    FROM core.fct_orders
    WHERE status = 'completed'
    GROUP BY order_month
)
SELECT
    order_month,
    revenue_usd,
    orders,
    active_customers,
    new_customers,
    active_customers - new_customers                                     AS returning_customers,
    ROUND(revenue_usd / NULLIF(orders, 0), 2)                            AS avg_order_value_usd,
    LAG(revenue_usd) OVER (ORDER BY order_month)                         AS prev_month_revenue_usd,
    ROUND(100 * (revenue_usd - LAG(revenue_usd) OVER (ORDER BY order_month))
          / NULLIF(LAG(revenue_usd) OVER (ORDER BY order_month), 0), 2)  AS mom_growth_pct,
    ROUND(100 * (revenue_usd - LAG(revenue_usd, 12) OVER (ORDER BY order_month))
          / NULLIF(LAG(revenue_usd, 12) OVER (ORDER BY order_month), 0), 2) AS yoy_growth_pct,
    SUM(revenue_usd) OVER (
        ORDER BY order_month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)   AS rolling_3m_revenue_usd,
    SUM(revenue_usd) OVER (
        PARTITION BY YEAR(order_month) ORDER BY order_month
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)                AS ytd_revenue_usd,
    SUM(revenue_usd) OVER (
        ORDER BY order_month ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cumulative_revenue_usd
FROM monthly;

-- -----------------------------------------------------------------------------
-- Customer lifetime value: historical value, predicted 24-month margin CLV,
-- lifecycle status, and ranking within segment.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.customer_ltv AS
WITH as_of AS (
    SELECT MAX(order_date) AS as_of_date FROM core.fct_orders
),
completed AS (
    SELECT customer_id, order_date, net_revenue_usd
    FROM core.fct_orders
    WHERE status = 'completed'
),
per_customer AS (
    SELECT
        customer_id,
        MIN(order_date)       AS first_order_date,
        MAX(order_date)       AS last_order_date,
        COUNT(*)              AS orders,
        SUM(net_revenue_usd)  AS total_revenue_usd
    FROM completed
    GROUP BY customer_id
),
base AS (
    SELECT
        c.customer_id,
        c.full_name,
        c.segment,
        c.country,
        c.acquisition_channel,
        c.signup_month,
        p.first_order_date,
        p.last_order_date,
        p.orders,
        p.total_revenue_usd,
        ROUND(p.total_revenue_usd / p.orders, 2)                    AS avg_order_value_usd,
        DATEDIFF(day, p.last_order_date, a.as_of_date)              AS days_since_last_order,
        DATEDIFF(month, p.first_order_date, a.as_of_date) + 1       AS tenure_months
    FROM per_customer AS p
    JOIN core.dim_customer AS c ON c.customer_id = p.customer_id
    CROSS JOIN as_of AS a
)
SELECT
    customer_id,
    full_name,
    segment,
    country,
    acquisition_channel,
    signup_month,
    first_order_date,
    last_order_date,
    orders,
    total_revenue_usd,
    avg_order_value_usd,
    days_since_last_order,
    tenure_months,
    ROUND(orders / tenure_months, 3)                                 AS orders_per_month,
    CASE
        WHEN days_since_last_order <= 90  THEN 'Active'
        WHEN days_since_last_order <= 180 THEN 'Lapsing'
        ELSE 'Churned'
    END                                                              AS lifecycle_status,
    -- Predicted CLV = AOV x monthly purchase frequency x gross margin (35%) x 24 months
    ROUND(avg_order_value_usd * (orders / tenure_months) * 0.35 * 24, 2) AS predicted_clv_24m_usd,
    RANK() OVER (PARTITION BY segment ORDER BY total_revenue_usd DESC) AS revenue_rank_in_segment,
    ROUND(PERCENT_RANK() OVER (ORDER BY total_revenue_usd), 4)       AS revenue_percentile,
    ROUND(SUM(total_revenue_usd) OVER (
              ORDER BY total_revenue_usd DESC, customer_id
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
          / SUM(total_revenue_usd) OVER (), 4)                       AS cumulative_revenue_share
FROM base;

-- -----------------------------------------------------------------------------
-- Cohort retention: share of each first-purchase cohort buying again N months later.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.cohort_retention AS
WITH completed AS (
    SELECT customer_id, order_month, net_revenue_usd
    FROM core.fct_orders
    WHERE status = 'completed'
),
first_purchase AS (
    SELECT customer_id, MIN(order_month) AS cohort_month
    FROM completed
    GROUP BY customer_id
),
cohort_size AS (
    SELECT cohort_month, COUNT(*) AS cohort_customers
    FROM first_purchase
    GROUP BY cohort_month
),
activity AS (
    SELECT
        f.cohort_month,
        DATEDIFF(month, f.cohort_month, c.order_month)  AS months_since_first,
        COUNT(DISTINCT c.customer_id)                   AS active_customers,
        SUM(c.net_revenue_usd)                          AS revenue_usd
    FROM completed AS c
    JOIN first_purchase AS f ON f.customer_id = c.customer_id
    GROUP BY f.cohort_month, DATEDIFF(month, f.cohort_month, c.order_month)
)
SELECT
    a.cohort_month,
    a.months_since_first,
    s.cohort_customers,
    a.active_customers,
    ROUND(a.active_customers / s.cohort_customers, 4)   AS retention_rate,
    a.revenue_usd,
    ROUND(SUM(a.revenue_usd) OVER (
              PARTITION BY a.cohort_month ORDER BY a.months_since_first
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
          / s.cohort_customers, 2)                      AS cumulative_revenue_per_customer_usd
FROM activity AS a
JOIN cohort_size AS s ON s.cohort_month = a.cohort_month;

-- -----------------------------------------------------------------------------
-- Rolling 90-day retention by month: of customers who bought in the prior
-- 90 days, how many bought again in the following 90 days.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.retention_90d AS
WITH completed AS (
    SELECT DISTINCT customer_id, order_date
    FROM core.fct_orders
    WHERE status = 'completed'
),
months AS (
    SELECT DISTINCT order_month AS month_start
    FROM core.fct_orders
),
bounds AS (
    SELECT MAX(order_date) AS max_date FROM core.fct_orders
),
base AS (
    SELECT m.month_start, COUNT(DISTINCT c.customer_id) AS base_customers
    FROM months AS m
    JOIN completed AS c
      ON c.order_date >= DATEADD(day, -90, m.month_start) AND c.order_date < m.month_start
    GROUP BY m.month_start
),
retained AS (
    SELECT m.month_start, COUNT(DISTINCT prev.customer_id) AS retained_customers
    FROM months AS m
    JOIN completed AS prev
      ON prev.order_date >= DATEADD(day, -90, m.month_start) AND prev.order_date < m.month_start
    JOIN completed AS nxt
      ON nxt.customer_id = prev.customer_id
     AND nxt.order_date >= m.month_start AND nxt.order_date < DATEADD(day, 90, m.month_start)
    GROUP BY m.month_start
)
SELECT
    b.month_start,
    b.base_customers,
    COALESCE(r.retained_customers, 0)                                   AS retained_customers,
    ROUND(COALESCE(r.retained_customers, 0) / b.base_customers, 4)      AS retention_rate_90d,
    ROUND(1 - COALESCE(r.retained_customers, 0) / b.base_customers, 4)  AS churn_rate_90d
FROM base AS b
CROSS JOIN bounds AS x
LEFT JOIN retained AS r ON r.month_start = b.month_start
-- only months with a full 90-day forward window
WHERE DATEADD(day, 90, b.month_start) <= x.max_date;

-- -----------------------------------------------------------------------------
-- RFM segmentation with quintile scores (NTILE).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.rfm_segments AS
WITH scored AS (
    SELECT
        customer_id,
        segment,
        country,
        days_since_last_order                                               AS recency_days,
        orders                                                              AS frequency,
        total_revenue_usd                                                   AS monetary_usd,
        NTILE(5) OVER (ORDER BY days_since_last_order DESC, customer_id)    AS r_score,
        NTILE(5) OVER (ORDER BY orders, customer_id)                        AS f_score,
        NTILE(5) OVER (ORDER BY total_revenue_usd, customer_id)             AS m_score
    FROM analytics.customer_ltv
)
SELECT
    customer_id,
    segment,
    country,
    recency_days,
    frequency,
    monetary_usd,
    r_score,
    f_score,
    m_score,
    r_score * 100 + f_score * 10 + m_score AS rfm_code,
    CASE
        WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN 'Champions'
        WHEN r_score >= 3 AND f_score >= 3                  THEN 'Loyal'
        WHEN r_score >= 4 AND f_score <= 2                  THEN 'New / Promising'
        WHEN r_score <= 2 AND f_score >= 3                  THEN 'At Risk'
        WHEN r_score <= 2 AND m_score >= 4                  THEN 'Cannot Lose'
        WHEN r_score <= 2                                   THEN 'Hibernating'
        ELSE 'Needs Attention'
    END AS rfm_segment
FROM scored;

-- -----------------------------------------------------------------------------
-- Revenue by customer segment / geography / channel, with share of month.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.revenue_by_segment AS
SELECT
    o.order_month,
    c.segment,
    c.country,
    c.acquisition_channel,
    o.sales_channel,
    SUM(o.net_revenue_usd)            AS revenue_usd,
    COUNT(*)                          AS orders,
    COUNT(DISTINCT o.customer_id)     AS customers,
    ROUND(SUM(o.net_revenue_usd)
          / NULLIF(SUM(SUM(o.net_revenue_usd)) OVER (PARTITION BY o.order_month), 0), 4) AS share_of_month_revenue
FROM core.fct_orders AS o
JOIN core.dim_customer AS c ON c.customer_id = o.customer_id
WHERE o.status = 'completed'
GROUP BY o.order_month, c.segment, c.country, c.acquisition_channel, o.sales_channel;

-- -----------------------------------------------------------------------------
-- Product category performance with monthly rank.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.revenue_by_category AS
WITH monthly AS (
    SELECT
        order_month,
        category,
        SUM(net_revenue_usd)  AS revenue_usd,
        SUM(quantity)         AS units
    FROM core.fct_order_items
    WHERE status = 'completed'
    GROUP BY order_month, category
)
SELECT
    order_month,
    category,
    revenue_usd,
    units,
    DENSE_RANK() OVER (PARTITION BY order_month ORDER BY revenue_usd DESC)     AS rank_in_month,
    ROUND(revenue_usd / SUM(revenue_usd) OVER (PARTITION BY order_month), 4)   AS share_of_month_revenue,
    ROUND(100 * (revenue_usd - LAG(revenue_usd) OVER (PARTITION BY category ORDER BY order_month))
          / NULLIF(LAG(revenue_usd) OVER (PARTITION BY category ORDER BY order_month), 0), 2) AS mom_growth_pct
FROM monthly;

-- -----------------------------------------------------------------------------
-- Headline KPIs (single row) for dashboard cards.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.kpi_summary AS
SELECT
    COUNT(*)                                                             AS paying_customers,
    SUM(total_revenue_usd)                                               AS total_revenue_usd,
    SUM(orders)                                                          AS completed_orders,
    ROUND(SUM(total_revenue_usd) / SUM(orders), 2)                       AS avg_order_value_usd,
    ROUND(AVG(total_revenue_usd), 2)                                     AS avg_historical_clv_usd,
    ROUND(AVG(predicted_clv_24m_usd), 2)                                 AS avg_predicted_clv_24m_usd,
    ROUND(AVG(CASE WHEN orders > 1 THEN 1 ELSE 0 END), 4)                AS repeat_purchase_rate,
    ROUND(AVG(CASE WHEN lifecycle_status = 'Active' THEN 1 ELSE 0 END), 4) AS active_customer_rate,
    ROUND(SUM(CASE WHEN revenue_percentile >= 0.9 THEN total_revenue_usd ELSE 0 END)
          / SUM(total_revenue_usd), 4)                                   AS top_10pct_revenue_share
FROM analytics.customer_ltv;
