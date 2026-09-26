-- Operational queries for the on-call engineer (see docs/runbook.md).

-- Latest run per stage and whether it succeeded
SELECT stage, run_id, status, started_at, duration_seconds, error_message
FROM ops.pipeline_runs
QUALIFY ROW_NUMBER() OVER (PARTITION BY stage ORDER BY started_at DESC) = 1;

-- Failed data-quality checks in the last 7 days
SELECT checked_at, run_id, table_name, check_name, severity, detail
FROM ops.dq_results
WHERE NOT passed AND checked_at >= DATEADD(day, -7, CURRENT_TIMESTAMP())
ORDER BY checked_at DESC;

-- Rows loaded per batch (volume anomaly check)
SELECT _batch_id, MIN(_loaded_at) AS loaded_at, COUNT(*) AS order_rows
FROM raw.orders
GROUP BY _batch_id
ORDER BY loaded_at DESC
LIMIT 30;

-- Warehouse credit usage for the last 30 days (cost monitoring)
SELECT DATE_TRUNC('day', start_time) AS day, SUM(credits_used) AS credits
FROM snowflake.account_usage.warehouse_metering_history
WHERE warehouse_name = 'REVINTEL_WH' AND start_time >= DATEADD(day, -30, CURRENT_TIMESTAMP())
GROUP BY 1
ORDER BY 1;

-- Housekeeping: RAW keeps 90 days of batches (the lake keeps the full history)
-- DELETE FROM raw.orders      WHERE _loaded_at < DATEADD(day, -90, CURRENT_TIMESTAMP());
-- DELETE FROM raw.order_items WHERE _loaded_at < DATEADD(day, -90, CURRENT_TIMESTAMP());
