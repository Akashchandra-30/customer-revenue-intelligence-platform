-- Bulk-load the cleaned Parquet files that the pipeline uploaded to Azure
-- (azure://<account>.blob.core.windows.net/revintel/clean/<table>/<table>.parquet).
-- TRUNCATE also clears COPY load metadata, so each run is a full, idempotent refresh.

TRUNCATE TABLE raw.fx_rates;
COPY INTO raw.fx_rates FROM @raw.azure_clean_stage/fx_rates/
    FILE_FORMAT = (FORMAT_NAME = 'raw.parquet_fmt') MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE ON_ERROR = ABORT_STATEMENT;

TRUNCATE TABLE raw.products;
COPY INTO raw.products FROM @raw.azure_clean_stage/products/
    FILE_FORMAT = (FORMAT_NAME = 'raw.parquet_fmt') MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE ON_ERROR = ABORT_STATEMENT;

TRUNCATE TABLE raw.customers;
COPY INTO raw.customers FROM @raw.azure_clean_stage/customers/
    FILE_FORMAT = (FORMAT_NAME = 'raw.parquet_fmt') MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE ON_ERROR = ABORT_STATEMENT;

TRUNCATE TABLE raw.orders;
COPY INTO raw.orders FROM @raw.azure_clean_stage/orders/
    FILE_FORMAT = (FORMAT_NAME = 'raw.parquet_fmt') MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE ON_ERROR = ABORT_STATEMENT;

TRUNCATE TABLE raw.order_items;
COPY INTO raw.order_items FROM @raw.azure_clean_stage/order_items/
    FILE_FORMAT = (FORMAT_NAME = 'raw.parquet_fmt') MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE ON_ERROR = ABORT_STATEMENT;
