select
    product_id,
    product_name,
    category,
    list_price_usd
from {{ ref('stg_catalog__products') }}
