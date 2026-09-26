select
    product_id,
    product_name,
    category,
    cast(list_price_usd as decimal(12, 2)) as list_price_usd
from {{ source('raw', 'products') }}
qualify row_number() over (partition by product_id order by _loaded_at desc) = 1
