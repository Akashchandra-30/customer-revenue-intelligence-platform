-- Customer lifetime value: historical value, predicted margin CLV, lifecycle status and ranking
with as_of as (
    select max(order_date) as as_of_date from {{ ref('fct_orders') }}
),

base as (
    select
        c.customer_id,
        c.full_name,
        c.segment,
        c.country,
        c.acquisition_channel,
        c.signup_month,
        c.first_order_date,
        c.last_order_date,
        c.completed_orders                                                    as orders,
        c.lifetime_revenue_usd                                                as total_revenue_usd,
        round(c.lifetime_revenue_usd / c.completed_orders, 2)                 as avg_order_value_usd,
        {{ dbt.datediff('c.last_order_date', 'a.as_of_date', 'day') }}        as days_since_last_order,
        {{ dbt.datediff('c.first_order_date', 'a.as_of_date', 'month') }} + 1 as tenure_months
    from {{ ref('dim_customer') }} as c
    cross join as_of as a
    where c.is_paying_customer
)

select
    *,
    round(orders / tenure_months, 3)                                          as orders_per_month,
    case
        when days_since_last_order <= {{ var('active_days') }}  then 'Active'
        when days_since_last_order <= {{ var('lapsing_days') }} then 'Lapsing'
        else 'Churned'
    end                                                                       as lifecycle_status,
    -- Predicted CLV = AOV x monthly purchase frequency x gross margin x horizon (months)
    round(avg_order_value_usd * (orders / tenure_months)
          * {{ var('gross_margin') }} * {{ var('clv_horizon_months') }}, 2)   as predicted_clv_usd,
    rank() over (partition by segment order by total_revenue_usd desc)       as revenue_rank_in_segment,
    round(percent_rank() over (order by total_revenue_usd), 4)               as revenue_percentile,
    round(sum(total_revenue_usd) over (
              order by total_revenue_usd desc, customer_id
              rows between unbounded preceding and current row)
          / sum(total_revenue_usd) over (), 4)                                as cumulative_revenue_share
from base
