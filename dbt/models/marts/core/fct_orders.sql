{{
    config(
        materialized='incremental',
        unique_key='order_id',
        incremental_strategy='delete+insert',
        on_schema_change='append_new_columns',
        cluster_by=['order_month'] if target.type == 'snowflake' else none
    )
}}

-- Grain: one row per order.
with orders as (
    select *
    from {{ ref('stg_erp__orders') }}
    {% if is_incremental() %}
    where ingested_at >= (
        select {{ dbt.dateadd('day', -var('incremental_lookback_days'), 'max(ingested_at)') }}
        from {{ this }}
    )
    {% endif %}
),

line_totals as (
    select
        order_id,
        count(*)              as line_count,
        sum(quantity)         as units,
        sum(line_amount_usd)  as gross_amount_usd,
        sum(net_revenue_usd)  as net_revenue_usd
    from {{ ref('int_order_items__converted') }}
    where order_id in (select order_id from orders)
    group by order_id
)

select
    o.order_id,
    o.customer_id,
    o.order_ts,
    o.order_date,
    cast({{ dbt.date_trunc('month', 'o.order_ts') }} as date)   as order_month,
    o.status,
    o.status = 'completed'                                      as is_revenue_order,
    o.sales_channel,
    o.currency,
    o.discount_pct,
    l.line_count,
    l.units,
    l.gross_amount_usd,
    {{ money('l.gross_amount_usd * o.discount_pct') }}          as discount_amount_usd,
    l.net_revenue_usd,
    o.ingested_at
from orders as o
join line_totals as l on l.order_id = o.order_id
