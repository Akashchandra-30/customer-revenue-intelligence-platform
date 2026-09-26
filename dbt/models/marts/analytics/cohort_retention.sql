-- Share of each first-purchase cohort that buys again N months later
with activity as (
    select
        c.first_order_month                                                   as cohort_month,
        {{ dbt.datediff('c.first_order_month', 'o.order_month', 'month') }}   as months_since_first,
        count(distinct o.customer_id)                                         as active_customers,
        sum(o.net_revenue_usd)                                                as revenue_usd
    from {{ ref('fct_orders') }} as o
    join {{ ref('dim_customer') }} as c on c.customer_id = o.customer_id
    where o.is_revenue_order
    group by 1, 2
),

cohort_size as (
    select first_order_month as cohort_month, count(*) as cohort_customers
    from {{ ref('dim_customer') }}
    where is_paying_customer
    group by 1
)

select
    a.cohort_month,
    a.months_since_first,
    s.cohort_customers,
    a.active_customers,
    round(a.active_customers / s.cohort_customers, 4)   as retention_rate,
    a.revenue_usd,
    round(sum(a.revenue_usd) over (
              partition by a.cohort_month order by a.months_since_first
              rows between unbounded preceding and current row)
          / s.cohort_customers, 2)                      as cumulative_revenue_per_customer_usd
from activity as a
join cohort_size as s on s.cohort_month = a.cohort_month
