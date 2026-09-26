"""End-to-end on DuckDB: ingest -> dbt build (models, snapshot, tests) -> second batch.

Covers idempotent re-loads, incremental facts, SCD2 history and revenue reconciliation.
Marked slow because it runs dbt twice (~1 min).
"""

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from revintel.config import Settings
from revintel.observability import run_id_var
from revintel.pipeline import ingest, new_run_id, publish, transform

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    base: Path = tmp_path_factory.mktemp("e2e")
    settings = Settings(duckdb_path=base / "revintel.duckdb", _env_file=None)
    paths = {"landing_dir": base / "landing", "lake_dir": base / "lake"}

    def run_batch(**kwargs):
        run_id_var.set(new_run_id())
        ingest("local", settings, n_customers=300, seed=7, **paths, **kwargs)
        transform("local", settings, artifacts_dir=base / "dbt")
        return run_id_var.get()

    first = run_batch(generate_data=True)
    return {"base": base, "settings": settings, "paths": paths, "run_batch": run_batch, "first": first}


def query(env, sql):
    # same config as dbt-duckdb's in-process connection (read-write), so DuckDB shares it
    with duckdb.connect(str(env["settings"].duckdb_path)) as con:
        return con.execute(sql).fetchall()


def test_first_batch_builds_all_marts(env):
    for table in (
        "core.fct_orders",
        "core.dim_customer",
        "analytics.customer_ltv",
        "analytics.monthly_revenue",
        "analytics.cohort_retention",
        "analytics.rfm_segments",
    ):
        assert query(env, f"select count(*) from {table}")[0][0] > 0, table


def test_revenue_reconciles_with_independent_pandas_calculation(env):
    lake = env["paths"]["lake_dir"] / "clean"
    batch = f"batch_id={env['first']}"
    orders = pd.read_parquet(lake / "orders" / batch)
    items = pd.read_parquet(lake / "order_items" / batch)
    fx = pd.read_parquet(lake / "fx_rates" / batch)
    lines = items.merge(orders, on="order_id").merge(fx, on="currency")
    lines = lines[lines["status"] == "completed"]
    expected = (lines["quantity"] * lines["unit_price"] * lines["rate_to_usd"] * (1 - lines["discount_pct"])).sum()

    actual = query(env, "select sum(revenue_usd) from analytics.monthly_revenue")[0][0]
    # SQL rounds each line to cents; allow half a cent per line
    assert float(actual) == pytest.approx(expected, abs=0.005 * len(lines))


def test_second_batch_is_idempotent_and_tracks_scd2_changes(env):
    before = query(env, "select count(*), sum(net_revenue_usd) from core.fct_orders")[0]

    # A customer is upgraded to Enterprise in the CRM before the next extract
    crm = env["paths"]["landing_dir"] / "crm" / "customers.csv"
    customers = pd.read_csv(crm, dtype=str)
    target = customers.loc[customers["segment"] == "Consumer", "customer_id"].iloc[0]
    customers.loc[customers["customer_id"] == target, ["segment", "updated_at"]] = ["Enterprise", "2026-09-15 00:00:00"]
    customers.to_csv(crm, index=False)

    env["run_batch"]()

    assert query(env, "select count(distinct _batch_id) from raw.orders")[0][0] == 2
    assert query(env, "select count(*), sum(net_revenue_usd) from core.fct_orders")[0] == before
    history = query(
        env,
        f"select segment, is_current from core.dim_customer_history where customer_id = '{target}' order by valid_from",
    )
    assert history == [("Consumer", False), ("Enterprise", True)]
    assert query(env, f"select segment from core.dim_customer where customer_id = '{target}'")[0][0] == "Enterprise"


def test_audit_tables_record_every_stage(env):
    stages = query(env, "select stage, status from ops.pipeline_runs order by started_at")
    assert stages == [("ingest", "success"), ("transform", "success")] * 2
    assert query(env, "select bool_and(passed) from ops.dq_results where severity = 'error'")[0][0] is True


def test_publish_exports_marts_for_power_bi(env, tmp_path):
    run_id_var.set(new_run_id())
    metrics = publish("local", env["settings"], export_dir=tmp_path)
    assert "analytics.customer_ltv" in metrics["exported"]
    assert (tmp_path / "kpi_summary.csv").exists()
