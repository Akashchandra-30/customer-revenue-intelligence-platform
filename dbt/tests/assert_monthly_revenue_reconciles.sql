-- The monthly trend must add up to total recognised revenue in the order fact
with trend as (
    select sum(revenue_usd) as revenue_usd from {{ ref('monthly_revenue') }}
),

fact as (
    select sum(net_revenue_usd) as revenue_usd from {{ ref('fct_orders') }} where is_revenue_order
)

select t.revenue_usd as trend_revenue, f.revenue_usd as fact_revenue
from trend as t
cross join fact as f
where abs(t.revenue_usd - f.revenue_usd) > 0.01
