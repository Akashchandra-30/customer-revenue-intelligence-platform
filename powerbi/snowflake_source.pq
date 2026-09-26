// Power Query (M) - connect Power BI to the Snowflake CORE/ANALYTICS layers.
// 1. Home > Manage Parameters: create text parameters SnowflakeServer
//    (e.g. "xy12345.west-europe.azure.snowflakecomputing.com") and SnowflakeWarehouse ("REVINTEL_WH").
// 2. Home > Get Data > Blank Query > Advanced Editor, paste one query per table,
//    changing the Schema/Object names. Use Import mode with scheduled refresh,
//    or DirectQuery for the large fact tables.

let
    Source    = Snowflake.Databases(SnowflakeServer, SnowflakeWarehouse, [Role = "REVINTEL_REPORTER"]),
    Database  = Source{[Name = "REVINTEL", Kind = "Database"]}[Data],
    Schema    = Database{[Name = "CORE", Kind = "Schema"]}[Data],
    fct_orders = Schema{[Name = "FCT_ORDERS", Kind = "Table"]}[Data],
    Typed = Table.TransformColumnTypes(
        fct_orders,
        {
            {"ORDER_DATE", type date},
            {"ORDER_MONTH", type date},
            {"NET_REVENUE_USD", Currency.Type},
            {"GROSS_AMOUNT_USD", Currency.Type},
            {"DISCOUNT_AMOUNT_USD", Currency.Type}
        }
    ),
    // Snowflake returns upper-case identifiers; lower-case them to match measures.dax
    Renamed = Table.TransformColumnNames(Typed, Text.Lower)
in
    Renamed

// Objects to import:
//   CORE.FCT_ORDERS, CORE.FCT_ORDER_ITEMS, CORE.DIM_CUSTOMER, CORE.DIM_PRODUCT
//   ANALYTICS.CUSTOMER_LTV, ANALYTICS.RFM_SEGMENTS, ANALYTICS.COHORT_RETENTION,
//   ANALYTICS.MONTHLY_REVENUE, ANALYTICS.RETENTION_90D, ANALYTICS.KPI_SUMMARY
//
// Offline alternative: `python -m revintel.pipeline --target local` writes the same
// tables as CSV to output/powerbi/ - use Get Data > Folder on that directory.
