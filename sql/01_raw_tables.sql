-- RAW layer: append-only landing tables. Executed by the pipeline on every
-- Snowflake connection (idempotent). Each batch is identified by _batch_id;
-- the same business key appears once per batch and dbt staging keeps the latest.

CREATE TABLE IF NOT EXISTS raw.fx_rates (
    currency        VARCHAR(3)    NOT NULL,
    rate_to_usd     NUMBER(18, 6) NOT NULL,
    _batch_id       VARCHAR       NOT NULL,
    _loaded_at      TIMESTAMP_NTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS raw.products (
    product_id      VARCHAR(10)   NOT NULL,
    product_name    VARCHAR(200)  NOT NULL,
    category        VARCHAR(50)   NOT NULL,
    list_price_usd  NUMBER(12, 2) NOT NULL,
    _batch_id       VARCHAR       NOT NULL,
    _loaded_at      TIMESTAMP_NTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS raw.customers (
    customer_id         VARCHAR(20)   NOT NULL,
    first_name          VARCHAR(100),
    last_name           VARCHAR(100),
    email               VARCHAR(320)  NOT NULL,
    country             VARCHAR(10)   NOT NULL,
    segment             VARCHAR(20)   NOT NULL,
    acquisition_channel VARCHAR(50),
    signup_date         DATE          NOT NULL,
    updated_at          TIMESTAMP_NTZ,
    _batch_id           VARCHAR       NOT NULL,
    _loaded_at          TIMESTAMP_NTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS raw.orders (
    order_id        VARCHAR(20)   NOT NULL,
    customer_id     VARCHAR(20)   NOT NULL,
    order_ts        TIMESTAMP_NTZ NOT NULL,
    currency        VARCHAR(3)    NOT NULL,
    status          VARCHAR(20)   NOT NULL,
    sales_channel   VARCHAR(30),
    discount_pct    NUMBER(5, 4)  NOT NULL DEFAULT 0,
    ingested_at     TIMESTAMP_NTZ NOT NULL,
    _batch_id       VARCHAR       NOT NULL,
    _loaded_at      TIMESTAMP_NTZ NOT NULL
)
CLUSTER BY (TO_DATE(_loaded_at));

CREATE TABLE IF NOT EXISTS raw.order_items (
    order_id        VARCHAR(20)   NOT NULL,
    line_number     INTEGER       NOT NULL,
    product_id      VARCHAR(10)   NOT NULL,
    quantity        INTEGER       NOT NULL,
    unit_price      NUMBER(14, 2) NOT NULL,
    _batch_id       VARCHAR       NOT NULL,
    _loaded_at      TIMESTAMP_NTZ NOT NULL
)
CLUSTER BY (TO_DATE(_loaded_at));

-- Operational metadata (also created by the pipeline if missing)
CREATE TABLE IF NOT EXISTS ops.pipeline_runs (
    run_id VARCHAR, stage VARCHAR, target VARCHAR, status VARCHAR,
    started_at TIMESTAMP_NTZ, finished_at TIMESTAMP_NTZ, duration_seconds DOUBLE,
    metrics VARCHAR, error_message VARCHAR
);

CREATE TABLE IF NOT EXISTS ops.dq_results (
    run_id VARCHAR, checked_at TIMESTAMP_NTZ, table_name VARCHAR, check_name VARCHAR,
    severity VARCHAR, passed BOOLEAN, detail VARCHAR
);
