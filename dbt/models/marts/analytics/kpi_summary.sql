-- Single-row headline KPIs for dashboard cards
select
    count(*)                                                                as paying_customers,
    sum(total_revenue_usd)                                                  as total_revenue_usd,
    sum(orders)                                                             as completed_orders,
    round(sum(total_revenue_usd) / sum(orders), 2)                          as avg_order_value_usd,
    round(avg(total_revenue_usd), 2)                                        as avg_historical_clv_usd,
    round(avg(predicted_clv_usd), 2)                                        as avg_predicted_clv_usd,
    round(avg(case when orders > 1 then 1 else 0 end), 4)                   as repeat_purchase_rate,
    round(avg(case when lifecycle_status = 'Active' then 1 else 0 end), 4)  as active_customer_rate,
    round(sum(case when revenue_percentile >= 0.9 then total_revenue_usd else 0 end)
          / sum(total_revenue_usd), 4)                                      as top_10pct_revenue_share
from {{ ref('customer_ltv') }}
