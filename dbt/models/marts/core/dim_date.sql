with spine as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('" ~ var('date_spine_start') ~ "' as date)",
        end_date="cast('" ~ var('date_spine_end') ~ "' as date)"
    ) }}
)

select
    cast(date_day as date)                                          as date_day,
    extract(year from date_day)                                     as year,
    extract(quarter from date_day)                                  as quarter,
    extract(month from date_day)                                    as month,
    cast({{ dbt.date_trunc('month', 'date_day') }} as date)         as month_start,
    cast(extract(year from date_day) as varchar) || '-'
        || lpad(cast(extract(month from date_day) as varchar), 2, '0') as year_month
from spine
