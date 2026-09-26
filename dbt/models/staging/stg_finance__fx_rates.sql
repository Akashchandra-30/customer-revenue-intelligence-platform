select
    currency,
    cast(rate_to_usd as decimal(18, 6)) as rate_to_usd
from {{ source('raw', 'fx_rates') }}
qualify row_number() over (partition by currency order by _loaded_at desc) = 1
