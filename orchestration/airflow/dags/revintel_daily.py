"""Daily Customer & Revenue Intelligence pipeline.

ingest (Python: clean, validate, Azure, Snowflake RAW)
  -> source_freshness (dbt)
  -> transform (dbt build: models, snapshot, tests)
  -> publish (Power BI dataset refresh)

Every task runs the same `revintel` CLI (baked into the container image) and passes
Airflow's run_id, so logs, ops.pipeline_runs and the lake batch share one id.
Credentials come from environment variables / Airflow connections backed by Key Vault.
"""

from __future__ import annotations

from datetime import datetime, timedelta

try:  # Airflow 3
    from airflow.providers.standard.operators.bash import BashOperator
    from airflow.sdk import DAG
except ImportError:  # Airflow 2.x
    from airflow import DAG  # type: ignore[no-redef,attr-defined]
    from airflow.operators.bash import BashOperator  # type: ignore[no-redef]

TARGET = "prod"
RUN_ID = "{{ run_id | replace(':', '') | replace('+', '') }}"


def _alert_on_failure(context: dict) -> None:
    """Forward task failures to the same Slack/Teams webhook the CLI uses."""
    import os

    from revintel.observability import send_alert

    ti = context["task_instance"]
    send_alert(
        os.getenv("ALERT_WEBHOOK_URL"),
        f"Airflow task failed: {ti.dag_id}.{ti.task_id}",
        f"try {ti.try_number}, logical date {context.get('logical_date')}",
    )


default_args = {
    "owner": "analytics-engineering",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "execution_timeout": timedelta(hours=1),
    "on_failure_callback": _alert_on_failure,
}

with DAG(
    dag_id="revintel_daily",
    description="Customer & Revenue Intelligence: ingest -> dbt -> Power BI",
    schedule="0 5 * * *",  # 05:00 UTC, after the ERP/CRM nightly extracts land
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["revintel", "snowflake", "dbt", "powerbi"],
) as dag:
    ingest = BashOperator(
        task_id="ingest",
        bash_command=f"revintel ingest --target {TARGET} --upload-azure --load-mode stage --run-id {RUN_ID}",
    )

    source_freshness = BashOperator(
        task_id="source_freshness",
        bash_command=f"dbt source freshness --project-dir /app/dbt --profiles-dir /app/dbt --target {TARGET}",
        retries=0,
    )

    transform = BashOperator(
        task_id="transform",
        bash_command=f"revintel transform --target {TARGET} --run-id {RUN_ID}",
    )

    publish = BashOperator(
        task_id="publish",
        bash_command=f"revintel publish --target {TARGET} --run-id {RUN_ID}",
    )

    ingest >> source_freshness >> transform >> publish
