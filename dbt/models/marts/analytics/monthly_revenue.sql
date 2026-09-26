-- Monthly revenue trend: MoM / YoY growth, rolling 3-month, YTD and cumulative
with months as (
    select distinct month_start as order_month
    from {{ ref('dim_date') }}
    where date_day between (select min(order_date) from {{ ref('fct_orders') }})
                       and (select max(order_date) from {{ ref('fct_orders') }})
),

orders as (
    select
        order_month,
        sum(net_revenue_usd)          as revenue_usd,
        count(*)                      as orders,
        count(distinct customer_id)   as active_customers
    from {{ ref('fct_orders') }}
    where is_revenue_order
    group by order_month
),

new_customers as (
    select first_order_month as order_month, count(*) as new_customers
    from {{ ref('dim_customer') }}
    where first_order_month is not null
    group by first_order_month
),

-- A dense month spine guarantees lag(x, 12) really means "same month last year"
monthly as (
    select
        m.order_month,
        coalesce(o.revenue_usd, 0)       as revenue_usd,
        coalesce(o.orders, 0)            as orders,
        coalesce(o.active_customers, 0)  as active_customers,
        coalesce(n.new_customers, 0)     as new_customers
    from months as m
    left join orders as o on o.order_month = m.order_month
    left join new_customers as n on n.order_month = m.order_month
)

select
    order_month,
    revenue_usd,
    orders,
    active_customers,
    new_customers,
    active_customers - new_customers                                        as returning_customers,
    round(revenue_usd / nullif(orders, 0), 2)                               as avg_order_value_usd,
    lag(revenue_usd) over (order by order_month)                            as prev_month_revenue_usd,
    round(100 * (revenue_usd - lag(revenue_usd) over (order by order_month))
          / nullif(lag(revenue_usd) over (order by order_month), 0), 2)     as mom_growth_pct,
    round(100 * (revenue_usd - lag(revenue_usd, 12) over (order by order_month))
          / nullif(lag(revenue_usd, 12) over (order by order_month), 0), 2) as yoy_growth_pct,
    sum(revenue_usd) over (
        order by order_month rows between 2 preceding and current row)      as rolling_3m_revenue_usd,
    sum(revenue_usd) over (
        partition by extract(year from order_month) order by order_month
        rows between unbounded preceding and current row)                   as ytd_revenue_usd,
    sum(revenue_usd) over (
        order by order_month rows between unbounded preceding and current row) as cumulative_revenue_usd
from monthly
