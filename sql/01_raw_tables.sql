-- RAW layer: typed landing tables for the cleaned, validated extracts.

CREATE TABLE IF NOT EXISTS raw.fx_rates (
    currency        VARCHAR(3)    NOT NULL PRIMARY KEY,
    rate_to_usd     NUMBER(18, 6) NOT NULL
);

CREATE TABLE IF NOT EXISTS raw.products (
    product_id      VARCHAR(10)   NOT NULL PRIMARY KEY,
    product_name    VARCHAR(200)  NOT NULL,
    category        VARCHAR(50)   NOT NULL,
    list_price_usd  NUMBER(12, 2) NOT NULL
);

CREATE TABLE IF NOT EXISTS raw.customers (
    customer_id         VARCHAR(20)  NOT NULL PRIMARY KEY,
    first_name          VARCHAR(100),
    last_name           VARCHAR(100),
    email               VARCHAR(320) NOT NULL,
    country             VARCHAR(10)  NOT NULL,
    segment             VARCHAR(20)  NOT NULL,
    acquisition_channel VARCHAR(50),
    signup_date         DATE         NOT NULL
);

CREATE TABLE IF NOT EXISTS raw.orders (
    order_id        VARCHAR(20)   NOT NULL PRIMARY KEY,
    customer_id     VARCHAR(20)   NOT NULL REFERENCES raw.customers (customer_id),
    order_ts        TIMESTAMP_NTZ NOT NULL,
    currency        VARCHAR(3)    NOT NULL,
    status          VARCHAR(20)   NOT NULL,
    sales_channel   VARCHAR(30),
    discount_pct    NUMBER(5, 4)  NOT NULL DEFAULT 0
)
CLUSTER BY (TO_DATE(order_ts));

CREATE TABLE IF NOT EXISTS raw.order_items (
    order_id        VARCHAR(20)   NOT NULL REFERENCES raw.orders (order_id),
    line_number     INTEGER       NOT NULL,
    product_id      VARCHAR(10)   NOT NULL REFERENCES raw.products (product_id),
    quantity        INTEGER       NOT NULL,
    unit_price      NUMBER(14, 2) NOT NULL,
    PRIMARY KEY (order_id, line_number)
);
