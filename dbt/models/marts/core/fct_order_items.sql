{{
    config(
        materialized='incremental',
        unique_key='order_item_id',
        incremental_strategy='delete+insert',
        on_schema_change='append_new_columns',
        cluster_by=['order_month'] if target.type == 'snowflake' else none
    )
}}

-- Grain: one row per order line. Incremental on the CDC timestamp with a lookback
-- window so late-arriving updates (refunds, cancellations) are reprocessed.
select *
from {{ ref('int_order_items__converted') }}

{% if is_incremental() %}
where ingested_at >= (
    select {{ dbt.dateadd('day', -var('incremental_lookback_days'), 'max(ingested_at)') }}
    from {{ this }}
)
{% endif %}
