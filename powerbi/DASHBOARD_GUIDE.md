# Power BI Dashboard Guide

## Data model (star schema)

```
                 dim_customer ───1:1─── customer_ltv
                  │   1                 rfm_segments (1:1)
                  │
                  * 
'Date' 1 ───* fct_orders 1 ───* fct_order_items *─── 1 dim_product
 (order_date)     (order_id)
```

| Relationship | From | To | Cardinality |
|---|---|---|---|
| Orders by date | `fct_orders[order_date]` | `'Date'[Date]` | many-to-one |
| Orders by customer | `fct_orders[customer_id]` | `dim_customer[customer_id]` | many-to-one |
| Lines by order | `fct_order_items[order_id]` | `fct_orders[order_id]` | many-to-one |
| Lines by product | `fct_order_items[product_id]` | `dim_product[product_id]` | many-to-one |
| LTV | `customer_ltv[customer_id]` | `dim_customer[customer_id]` | one-to-one |
| RFM | `rfm_segments[customer_id]` | `dim_customer[customer_id]` | one-to-one |

`cohort_retention`, `monthly_revenue`, `retention_90d` and `kpi_summary` are
pre-aggregated in Snowflake and stay disconnected.

Mark `'Date'` as the date table. Apply `theme.json` via *View › Themes › Browse*.

## Report pages

### 1. Executive Overview
- **KPI cards:** Total Revenue, Revenue YoY %, Active Customers, Average Order Value, Avg Customer LTV, Repeat Purchase Rate %
- **Line + column combo:** `Total Revenue` (columns) and `Revenue Rolling 3M` (line) by `'Date'[Year Month]`
- **Line:** Revenue MoM % with a zero reference line
- **Slicers:** Year, segment, country

### 2. Revenue Performance
- **Stacked column:** Total Revenue by Year Month, legend = `dim_product[category]`
- **Bar:** Revenue Share % by `dim_customer[segment]`
- **Filled map:** Total Revenue by `dim_customer[country]`
- **Matrix:** sales channel × year with Total Revenue, Revenue YoY %, Discount Rate %
- **Waterfall:** Revenue YTD by month

### 3. Customer Segments & CLV
- **Donut:** customer count by `rfm_segments[rfm_segment]`
- **Scatter:** customers with `frequency` (x), `monetary_usd` (y), coloured by `rfm_segment`
- **Table:** top customers ranked by `total_revenue_usd`, with `predicted_clv_24m_usd`, `lifecycle_status`
- **Bar:** Avg Predicted CLV 24M by `acquisition_channel` (which channels bring valuable customers)
- **Card:** Top 10% Customer Revenue Share

### 4. Retention & Churn
- **Cohort heatmap (matrix):** rows `cohort_month`, columns `months_since_first`, values `Cohort Retention %`, with background colour scale conditional formatting
- **Line:** `retention_90d[retention_rate_90d]` and `churn_rate_90d` by `month_start`
- **Stacked bar:** lifecycle status (Active / Lapsing / Churned) by segment
- **Line:** New vs Returning Customers by month

## Refresh
Publish to the Power BI Service, configure the Snowflake data source credentials
(role `REVINTEL_REPORTER`), and schedule refresh after the daily pipeline run.
