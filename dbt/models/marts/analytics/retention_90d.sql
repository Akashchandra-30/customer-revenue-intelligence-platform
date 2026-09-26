-- Of customers who bought in the 90 days before a month starts, how many buy in the next 90 days
with purchases as (
    select distinct customer_id, order_date
    from {{ ref('fct_orders') }}
    where is_revenue_order
),

months as (
    select distinct order_month as month_start from {{ ref('fct_orders') }}
),

bounds as (
    select max(order_date) as max_date from {{ ref('fct_orders') }}
),

base as (
    select m.month_start, p.customer_id
    from months as m
    join purchases as p
      on p.order_date >= {{ dbt.dateadd('day', -90, 'm.month_start') }}
     and p.order_date < m.month_start
    group by 1, 2
),

retained as (
    select b.month_start, count(distinct b.customer_id) as retained_customers
    from base as b
    join purchases as p
      on p.customer_id = b.customer_id
     and p.order_date >= b.month_start
     and p.order_date < {{ dbt.dateadd('day', 90, 'b.month_start') }}
    group by 1
),

base_counts as (
    select month_start, count(*) as base_customers
    from base
    group by 1
)

select
    b.month_start,
    b.base_customers,
    coalesce(r.retained_customers, 0)                                   as retained_customers,
    round(coalesce(r.retained_customers, 0) / b.base_customers, 4)      as retention_rate_90d,
    round(1 - coalesce(r.retained_customers, 0) / b.base_customers, 4)  as churn_rate_90d
from base_counts as b
cross join bounds as x
left join retained as r on r.month_start = b.month_start
-- only months with a complete 90-day forward window
where {{ dbt.dateadd('day', 90, 'b.month_start') }} <= x.max_date
