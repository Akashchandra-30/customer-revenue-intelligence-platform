-- Order-level revenue must equal the sum of its lines (catches incremental drift between the two facts)
with lines as (
    select order_id, sum(net_revenue_usd) as net_revenue_usd, sum(line_amount_usd) as gross_amount_usd
    from {{ ref('fct_order_items') }}
    group by order_id
)

select o.order_id, o.net_revenue_usd, l.net_revenue_usd as line_net_revenue_usd
from {{ ref('fct_orders') }} as o
full outer join lines as l on l.order_id = o.order_id
where o.order_id is null
   or l.order_id is null
   or abs(o.net_revenue_usd - l.net_revenue_usd) > 0.01
   or abs(o.gross_amount_usd - l.gross_amount_usd) > 0.01
