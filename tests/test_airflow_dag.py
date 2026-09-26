"""DAG integrity test: runs in CI's airflow job; skipped where Airflow isn't installed."""

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("airflow")

DAG_FILE = Path(__file__).parents[1] / "orchestration" / "airflow" / "dags" / "revintel_daily.py"


def test_dag_structure():
    spec = importlib.util.spec_from_file_location("revintel_daily", DAG_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dag = module.dag

    assert dag.dag_id == "revintel_daily"
    assert set(dag.task_ids) == {"ingest", "source_freshness", "transform", "publish"}
    assert dag.get_task("ingest").downstream_task_ids == {"source_freshness"}
    assert dag.get_task("transform").downstream_task_ids == {"publish"}
    assert dag.max_active_runs == 1
