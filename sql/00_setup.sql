-- =============================================================================
-- One-time Snowflake setup (run as ACCOUNTADMIN / SYSADMIN + SECURITYADMIN).
-- Creates compute, database, layered schemas, roles and the Azure stage.
-- =============================================================================

-- ---------- Compute ----------------------------------------------------------
CREATE WAREHOUSE IF NOT EXISTS REVINTEL_WH
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'Customer & Revenue Intelligence: ELT + BI';

-- ---------- Storage layers -------------------------------------------------
CREATE DATABASE IF NOT EXISTS REVINTEL;
CREATE SCHEMA IF NOT EXISTS REVINTEL.RAW       COMMENT = 'Validated source data, 1:1 with cleaned extracts';
CREATE SCHEMA IF NOT EXISTS REVINTEL.CORE      COMMENT = 'Conformed star schema (dims + facts)';
CREATE SCHEMA IF NOT EXISTS REVINTEL.ANALYTICS COMMENT = 'Business metrics consumed by Power BI';

-- ---------- Roles ------------------------------------------------------------
CREATE ROLE IF NOT EXISTS REVINTEL_LOADER;    -- used by the Python pipeline
CREATE ROLE IF NOT EXISTS REVINTEL_REPORTER;  -- used by Power BI (read-only)

GRANT USAGE ON WAREHOUSE REVINTEL_WH TO ROLE REVINTEL_LOADER;
GRANT USAGE ON WAREHOUSE REVINTEL_WH TO ROLE REVINTEL_REPORTER;
GRANT USAGE ON DATABASE REVINTEL TO ROLE REVINTEL_LOADER;
GRANT USAGE ON DATABASE REVINTEL TO ROLE REVINTEL_REPORTER;
GRANT ALL ON SCHEMA REVINTEL.RAW TO ROLE REVINTEL_LOADER;
GRANT ALL ON SCHEMA REVINTEL.CORE TO ROLE REVINTEL_LOADER;
GRANT ALL ON SCHEMA REVINTEL.ANALYTICS TO ROLE REVINTEL_LOADER;
GRANT USAGE ON SCHEMA REVINTEL.CORE TO ROLE REVINTEL_REPORTER;
GRANT USAGE ON SCHEMA REVINTEL.ANALYTICS TO ROLE REVINTEL_REPORTER;
GRANT SELECT ON FUTURE TABLES IN SCHEMA REVINTEL.CORE TO ROLE REVINTEL_REPORTER;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA REVINTEL.ANALYTICS TO ROLE REVINTEL_REPORTER;

-- ---------- Azure Data Lake integration ---------------------------------------
-- Replace <tenant-id> and <storage-account>. After creating the integration run
--   DESC STORAGE INTEGRATION REVINTEL_AZURE_INT;
-- open AZURE_CONSENT_URL, then grant the AZURE_MULTI_TENANT_APP_NAME service
-- principal "Storage Blob Data Reader" on the storage account.
CREATE STORAGE INTEGRATION IF NOT EXISTS REVINTEL_AZURE_INT
    TYPE = EXTERNAL_STAGE
    STORAGE_PROVIDER = 'AZURE'
    ENABLED = TRUE
    AZURE_TENANT_ID = '<tenant-id>'
    STORAGE_ALLOWED_LOCATIONS = ('azure://<storage-account>.blob.core.windows.net/revintel/clean/');

GRANT USAGE ON INTEGRATION REVINTEL_AZURE_INT TO ROLE REVINTEL_LOADER;

CREATE FILE FORMAT IF NOT EXISTS REVINTEL.RAW.PARQUET_FMT TYPE = PARQUET;

CREATE STAGE IF NOT EXISTS REVINTEL.RAW.AZURE_CLEAN_STAGE
    URL = 'azure://<storage-account>.blob.core.windows.net/revintel/clean/'
    STORAGE_INTEGRATION = REVINTEL_AZURE_INT
    FILE_FORMAT = REVINTEL.RAW.PARQUET_FMT;

GRANT USAGE ON STAGE REVINTEL.RAW.AZURE_CLEAN_STAGE TO ROLE REVINTEL_LOADER;
