# Power BI Dashboard Guide

## Semantic model (star schema)

```
                       dim_customer ──1:1── customer_ltv
                        │ 1          └─1:1── rfm_segments
                        │
 dim_date 1 ──* fct_orders 1 ──* fct_order_items *── 1 dim_product
 (date_day)    (order_date)     (order_id)

 security_country_access  (disconnected; used by the RLS rule)
 cohort_retention, monthly_revenue, retention_90d, kpi_summary  (pre-aggregated, disconnected)
```

| Relationship | From (many) | To (one) | Notes |
|---|---|---|---|
| Orders by date | `fct_orders[order_date]` | `dim_date[date_day]` | mark `dim_date` as date table |
| Orders by customer | `fct_orders[customer_id]` | `dim_customer[customer_id]` | |
| Lines by order | `fct_order_items[order_id]` | `fct_orders[order_id]` | |
| Lines by product | `fct_order_items[product_id]` | `dim_product[product_id]` | |
| LTV | `customer_ltv[customer_id]` | `dim_customer[customer_id]` | 1:1, both directions, apply security filter |
| RFM | `rfm_segments[customer_id]` | `dim_customer[customer_id]` | 1:1, both directions, apply security filter |

Model hygiene: hide the key columns and raw numeric columns so users only work
with measures. Put the measures from [`measures.dax`](measures.dax) in a `_Measures`
table with display folders (Revenue, Time Intelligence, Customers, CLV, Cohorts).
Set currency formats on `*_usd` measures and apply [`theme.json`](theme.json).

## Security

Dynamic row-level security is defined in [`rls_roles.dax`](rls_roles.dax). Regional managers
see only their countries, based on the `security_country_access` dbt seed. PII (email) is
masked in Snowflake for the `REVINTEL_REPORTER` role, so it never reaches the model.

## Report pages

### 1. Executive Overview
- **KPI cards:** Total Revenue (coloured by `YoY Colour`), Revenue YoY %, Active Customers, Average Order Value, Avg Customer LTV, Repeat Purchase Rate %
- **Combo chart:** `Total Revenue` (columns) and `Revenue Rolling 3M` (line) by `dim_date[year_month]`
- **Line:** Revenue MoM % with a zero reference line
- **Slicers:** year, segment, country · footer card: `Last Refreshed`

### 2. Revenue Performance
- **Stacked column:** Total Revenue by month, legend `dim_product[category]`
- **Bar:** Revenue Share % by `dim_customer[segment]`
- **Filled map:** Total Revenue by `dim_customer[country]`
- **Matrix:** sales channel × year with Total Revenue, Revenue YoY %, Discount Rate %
- **Waterfall:** Revenue YTD by month

### 3. Customer Segments & CLV
- **Donut:** customers by `rfm_segments[rfm_segment]`
- **Scatter:** `frequency` × `monetary_usd` per customer, coloured by RFM segment
- **Table:** top customers by `total_revenue_usd` with `predicted_clv_usd`, `lifecycle_status`
- **Bar:** Avg Predicted CLV by `acquisition_channel` (which channels bring valuable customers)
- **Card:** Top 10% Customer Revenue Share

### 4. Retention & Churn
- **Cohort heatmap (matrix):** rows `cohort_month`, columns `months_since_first`, value `Cohort Retention %`, background colour scale
- **Line:** `retention_rate_90d` and `churn_rate_90d` by `month_start`
- **Stacked bar:** lifecycle status by segment
- **Line:** New vs Returning Customers by month

## Deployment & refresh
- Develop in Power BI Desktop against the `dev` schemas, then publish to a **Dev** workspace and promote through a **deployment pipeline** (Dev → Test → Prod).
- Data source credentials use the `REVINTEL_REPORTER` role.
- The pipeline's `publish` stage triggers the dataset refresh through the REST API once `dbt build` has passed, so users never see partially loaded data.
