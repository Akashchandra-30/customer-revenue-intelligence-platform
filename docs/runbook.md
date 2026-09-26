# Runbook

On-call guide for the `revintel_daily` pipeline. Failures alert the team's Slack/Teams
channel with the `run_id` and stage. Queries referenced below are in
[`sql/02_ops_monitoring.sql`](../sql/02_ops_monitoring.sql).

## Where to look

| Question | Where |
|---|---|
| Which stage failed, and why? | `ops.pipeline_runs` (latest row per stage), Airflow task log, Log Analytics (`run_id` is in every JSON log line) |
| Which data-quality checks failed? | `ops.dq_results`, or `dq/batch_id=<run_id>/report.json` in the lake |
| Which records were rejected? | `rejects/batch_id=<run_id>/*.csv` in the lake |
| Which dbt test failed? | Airflow `transform` log; rerun locally with `dbt test --select <model>` |

## Common failures

### `DataQualityError` in ingest
The source delivered data that breaks a hard rule, for example duplicate keys or orphan orders. Nothing was loaded, so the warehouse is still consistent with yesterday.
1. Read the failed checks in `ops.dq_results` for the run.
2. If the source is wrong, contact the system owner (CRM: Sales Ops; ERP: Finance Systems) and ask them to re-deliver the extract.
3. Re-run with the **same** run id so the batch replaces itself idempotently:
   `revintel ingest --target prod --upload-azure --load-mode stage --run-id <run_id>`

### High reject rate warning (`reject_rate<5%`)
The load continued, but more rows than usual were quarantined. Review the reject CSVs and raise the issue with the source owner if the pattern is new.

### dbt source freshness error
RAW has not received a batch in more than 50 hours, which usually means the ingest task or an upstream extract did not run. Check the ingest task first.

### dbt test failure in transform
Models built before the failure stay in place, but Power BI is **not** refreshed, because publish depends on transform. Fix the model or data, then clear the task in Airflow.
Incremental drift (the `assert_order_totals_match_line_items` test) → `revintel transform --target prod --full-refresh --select fct_orders fct_order_items`.

### Snowflake auth errors
Key-pair rotation: generate a new key, then `ALTER USER SVC_REVINTEL SET RSA_PUBLIC_KEY_2 = '...'`. Update the Key Vault secret `snowflake-private-key`, confirm a run succeeds, then unset `RSA_PUBLIC_KEY`.

## Backfill / replay
Every batch is kept in the lake. To rebuild history after a logic change:
```bash
revintel transform --target prod --full-refresh
```
To replay a specific batch into RAW, re-run `COPY INTO raw.<table>` from
`@raw.azure_clean_stage/<table>/batch_id=<id>/`.

## Cost
The resource monitor `REVINTEL_MONTHLY` notifies at 75% of 50 credits and suspends the warehouse at 100%. Daily credit usage is in `sql/02_ops_monitoring.sql`.
