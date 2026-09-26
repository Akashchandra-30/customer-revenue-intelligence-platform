-- Recency / Frequency / Monetary quintile scoring and segment labels
with scored as (
    select
        customer_id,
        segment,
        country,
        days_since_last_order                                               as recency_days,
        orders                                                              as frequency,
        total_revenue_usd                                                   as monetary_usd,
        ntile(5) over (order by days_since_last_order desc, customer_id)    as r_score,
        ntile(5) over (order by orders, customer_id)                        as f_score,
        ntile(5) over (order by total_revenue_usd, customer_id)             as m_score
    from {{ ref('customer_ltv') }}
)

select
    *,
    r_score * 100 + f_score * 10 + m_score as rfm_code,
    case
        when r_score >= 4 and f_score >= 4 and m_score >= 4 then 'Champions'
        when r_score >= 3 and f_score >= 3                  then 'Loyal'
        when r_score >= 4 and f_score <= 2                  then 'New / Promising'
        when r_score <= 2 and f_score >= 3                  then 'At Risk'
        when r_score <= 2 and m_score >= 4                  then 'Cannot Lose'
        when r_score <= 2                                   then 'Hibernating'
        else 'Needs Attention'
    end as rfm_segment
from scored
