-- Product category performance with monthly rank, share and growth
with monthly as (
    select
        order_month,
        category,
        sum(net_revenue_usd)  as revenue_usd,
        sum(quantity)         as units
    from {{ ref('fct_order_items') }}
    where status = 'completed'
    group by 1, 2
)

select
    order_month,
    category,
    revenue_usd,
    units,
    dense_rank() over (partition by order_month order by revenue_usd desc)     as rank_in_month,
    round(revenue_usd / sum(revenue_usd) over (partition by order_month), 4)   as share_of_month_revenue,
    round(100 * (revenue_usd - lag(revenue_usd) over (partition by category order by order_month))
          / nullif(lag(revenue_usd) over (partition by category order by order_month), 0), 2) as mom_growth_pct
from monthly
