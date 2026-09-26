-- Revenue by customer segment, geography and channel, with share of the month
select
    o.order_month,
    c.segment,
    c.country,
    c.acquisition_channel,
    o.sales_channel,
    sum(o.net_revenue_usd)          as revenue_usd,
    count(*)                        as orders,
    count(distinct o.customer_id)   as customers,
    round(sum(o.net_revenue_usd)
          / nullif(sum(sum(o.net_revenue_usd)) over (partition by o.order_month), 0), 4) as share_of_month_revenue
from {{ ref('fct_orders') }} as o
join {{ ref('dim_customer') }} as c on c.customer_id = o.customer_id
where o.is_revenue_order
group by 1, 2, 3, 4, 5
