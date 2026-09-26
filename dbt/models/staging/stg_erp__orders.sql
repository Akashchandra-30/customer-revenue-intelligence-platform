-- CDC can redeliver an order (e.g. status change to refunded); latest delivery wins
with source as (
    select * from {{ source('raw', 'orders') }}
),

latest as (
    select *
    from source
    qualify row_number() over (
        partition by order_id
        order by ingested_at desc, _loaded_at desc
    ) = 1
)

select
    order_id,
    customer_id,
    cast(order_ts as timestamp)             as order_ts,
    cast(order_ts as date)                  as order_date,
    status,
    sales_channel,
    currency,
    cast(discount_pct as decimal(5, 4))     as discount_pct,
    cast(ingested_at as timestamp)          as ingested_at,
    _batch_id,
    _loaded_at
from latest
