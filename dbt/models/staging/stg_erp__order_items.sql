with source as (
    select * from {{ source('raw', 'order_items') }}
),

latest as (
    select *
    from source
    qualify row_number() over (
        partition by order_id, line_number
        order by _loaded_at desc
    ) = 1
)

select
    order_id || '-' || cast(line_number as varchar)  as order_item_id,
    order_id,
    cast(line_number as integer)                     as line_number,
    product_id,
    cast(quantity as integer)                        as quantity,
    cast(unit_price as decimal(14, 2))               as unit_price_local,
    _loaded_at
from latest
