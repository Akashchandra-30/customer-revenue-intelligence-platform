{{ config(post_hook=["{{ mask_pii(this, 'email') }}"]) }}

-- Grain: one row per customer (current attributes). History lives in dim_customer_history.
with customers as (
    select * from {{ ref('stg_crm__customers') }}
),

purchases as (
    select
        customer_id,
        min(order_date)  as first_order_date,
        max(order_date)  as last_order_date,
        count(*)         as completed_orders,
        sum(net_revenue_usd) as lifetime_revenue_usd
    from {{ ref('fct_orders') }}
    where is_revenue_order
    group by customer_id
)

select
    c.customer_id,
    c.first_name,
    c.last_name,
    c.first_name || ' ' || c.last_name                                  as full_name,
    c.email,
    c.country,
    c.segment,
    c.acquisition_channel,
    c.signup_date,
    cast({{ dbt.date_trunc('month', 'c.signup_date') }} as date)        as signup_month,
    p.first_order_date,
    cast({{ dbt.date_trunc('month', 'p.first_order_date') }} as date)   as first_order_month,
    p.last_order_date,
    coalesce(p.completed_orders, 0)                                     as completed_orders,
    coalesce(p.lifetime_revenue_usd, 0)                                 as lifetime_revenue_usd,
    p.customer_id is not null                                           as is_paying_customer
from customers as c
left join purchases as p on p.customer_id = c.customer_id
