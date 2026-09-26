-- Order lines enriched with order context and converted to USD, net of order-level discount
select
    i.order_item_id,
    i.order_id,
    i.line_number,
    i.product_id,
    p.category,
    o.customer_id,
    o.order_date,
    cast({{ dbt.date_trunc('month', 'o.order_ts') }} as date)                 as order_month,
    o.status,
    o.currency,
    o.ingested_at,
    i.quantity,
    i.unit_price_local,
    {{ money('i.quantity * i.unit_price_local') }}                            as line_amount_local,
    {{ money('i.quantity * i.unit_price_local * fx.rate_to_usd') }}           as line_amount_usd,
    case
        when o.status = 'completed'
            then {{ money('i.quantity * i.unit_price_local * fx.rate_to_usd * (1 - o.discount_pct)') }}
        else cast(0 as decimal(18, 2))
    end                                                                       as net_revenue_usd
from {{ ref('stg_erp__order_items') }}   as i
join {{ ref('stg_erp__orders') }}        as o  on o.order_id = i.order_id
join {{ ref('stg_finance__fx_rates') }}  as fx on fx.currency = o.currency
join {{ ref('stg_catalog__products') }}  as p  on p.product_id = i.product_id
