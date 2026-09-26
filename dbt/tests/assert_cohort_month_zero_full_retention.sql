-- By definition every customer in a cohort is active in month 0
select cohort_month, retention_rate
from {{ ref('cohort_retention') }}
where months_since_first = 0
  and retention_rate <> 1
