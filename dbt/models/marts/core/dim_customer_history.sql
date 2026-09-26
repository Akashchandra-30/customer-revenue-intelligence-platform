-- SCD Type 2: every historical version of a customer's attributes (segment, country, ...)
select
    dbt_scd_id                                              as customer_version_key,
    customer_id,
    segment,
    country,
    acquisition_channel,
    dbt_valid_from                                          as valid_from,
    coalesce(dbt_valid_to, cast('9999-12-31' as timestamp)) as valid_to,
    dbt_valid_to is null                                    as is_current
from {{ ref('snap_customers') }}
