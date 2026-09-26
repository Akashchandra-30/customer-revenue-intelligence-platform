-- Latest known version of each customer across all loaded batches
with source as (
    select * from {{ source('raw', 'customers') }}
),

latest as (
    select *
    from source
    qualify row_number() over (
        partition by customer_id
        order by updated_at desc, _loaded_at desc
    ) = 1
)

select
    customer_id,
    first_name,
    last_name,
    email,
    country,
    segment,
    acquisition_channel,
    cast(signup_date as date)      as signup_date,
    cast(updated_at as timestamp)  as updated_at,
    _batch_id,
    _loaded_at
from latest
