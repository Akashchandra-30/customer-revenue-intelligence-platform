// Power Query (M) - connect Power BI to Snowflake CORE / ANALYTICS.
//
// 1. Home > Manage Parameters: create text parameters
//      SnowflakeServer     e.g. "xy12345.west-europe.azure.snowflakecomputing.com"
//      SnowflakeWarehouse  "REVINTEL_WH"
// 2. Create the function below as a blank query named fnSnowflakeTable.
// 3. Create one query per table: = fnSnowflakeTable("CORE", "FCT_ORDERS")
// Import mode + scheduled refresh (triggered by the pipeline's publish stage).
// For very large facts use DirectQuery or incremental refresh on ORDER_DATE.

(schema as text, objectName as text) as table =>
let
    Source   = Snowflake.Databases(SnowflakeServer, SnowflakeWarehouse, [Role = "REVINTEL_REPORTER"]),
    Database = Source{[Name = "REVINTEL", Kind = "Database"]}[Data],
    Schema   = Database{[Name = schema, Kind = "Schema"]}[Data],
    Data     = Schema{[Name = objectName]}[Data],
    // Snowflake returns upper-case identifiers; lower-case them to match measures.dax
    Renamed  = Table.TransformColumnNames(Data, Text.Lower)
in
    Renamed

// Objects to import:
//   CORE:      FCT_ORDERS, FCT_ORDER_ITEMS, DIM_CUSTOMER, DIM_PRODUCT, DIM_DATE, SECURITY_COUNTRY_ACCESS
//   ANALYTICS: CUSTOMER_LTV, RFM_SEGMENTS, COHORT_RETENTION, MONTHLY_REVENUE, RETENTION_90D, KPI_SUMMARY
//
// Offline alternative: `revintel run --target local --generate` writes the same tables
// as CSV to output/powerbi/ - use Get Data > Folder on that directory.
