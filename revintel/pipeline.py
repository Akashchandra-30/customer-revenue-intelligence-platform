"""Pipeline stages: ingest -> transform -> publish.

Each stage can run on its own (Airflow runs them as separate tasks) and writes an
audit record to ``ops.pipeline_runs`` whether it succeeds or fails.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from revintel import config
from revintel.config import Settings, Target
from revintel.extract import extract_all
from revintel.generate_data import generate
from revintel.observability import run_id_var, stage_var
from revintel.transform import CleanResult, transform_all
from revintel.validate import Check, assert_passed, reconciliation, run_checks
from revintel.warehouse import DuckDBWarehouse, SnowflakeWarehouse, open_warehouse

log = logging.getLogger(__name__)

LoadMode = Literal["direct", "stage"]


def new_run_id() -> str:
    return f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:6]}"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@contextmanager
def tracked_stage(stage: str, target: Target, settings: Settings) -> Iterator[dict[str, Any]]:
    stage_var.set(stage)
    metrics: dict[str, Any] = {}
    started, status, error = _utcnow(), "success", None
    log.info("Stage '%s' started (target=%s)", stage, target)
    try:
        yield metrics
    except Exception as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"[:4000]
        raise
    finally:
        finished = _utcnow()
        try:
            with open_warehouse(target, settings) as wh:
                wh.ensure_ops_tables()
                wh.record_run(run_id_var.get(), stage, status, started, finished, metrics, error)
        except Exception:
            log.exception("Could not write audit record for stage '%s'", stage)
        log.info("Stage '%s' %s in %.1fs", stage, status, (finished - started).total_seconds())


def _write_quarantine(results: dict[str, CleanResult], checks: list[Check], lake_dir: Path, run_id: str) -> None:
    rejects_dir = lake_dir / "rejects" / f"batch_id={run_id}"
    rejects_dir.mkdir(parents=True, exist_ok=True)
    for name, res in results.items():
        if len(res.rejects):
            res.rejects.to_csv(rejects_dir / f"{name}_rejects.csv", index=False)
    dq_dir = lake_dir / "dq" / f"batch_id={run_id}"
    dq_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "run_id": run_id,
        "checks": [c.to_dict() for c in checks],
        "rejects_by_reason": {
            n: r.rejects["reject_reason"].value_counts().to_dict() for n, r in results.items() if len(r.rejects)
        },
        "duplicates_removed": {n: r.duplicates_removed for n, r in results.items()},
    }
    (dq_dir / "report.json").write_text(json.dumps(report, indent=2, default=str))


def _write_clean(clean: dict[str, pd.DataFrame], lake_dir: Path, run_id: str) -> None:
    for name, df in clean.items():
        out = lake_dir / "clean" / name / f"batch_id={run_id}"
        out.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out / f"{name}.parquet", index=False)


def ingest(
    target: Target,
    settings: Settings,
    *,
    landing_dir: Path = config.LANDING_DIR,
    lake_dir: Path = config.LAKE_DIR,
    generate_data: bool = False,
    n_customers: int = 5000,
    seed: int = 42,
    upload_azure: bool = False,
    load_mode: LoadMode = "direct",
) -> dict[str, Any]:
    """Extract, clean and validate the source extracts, then append them to RAW as a new batch."""
    run_id = run_id_var.get()
    with tracked_stage("ingest", target, settings) as metrics:
        if generate_data or not (landing_dir / "crm" / "customers.csv").exists():
            generate(landing_dir, n_customers, seed)

        raw = extract_all(landing_dir)
        results = transform_all(raw)
        checks = run_checks({n: r.data for n, r in results.items()}) + reconciliation(raw, results)
        _write_quarantine(results, checks, lake_dir, run_id)

        loaded_at = _utcnow()
        clean = {n: r.data.assign(_batch_id=run_id, _loaded_at=loaded_at) for n, r in results.items()}
        metrics.update(
            checks_passed=sum(c.passed for c in checks),
            checks_total=len(checks),
            rejected={n: len(r.rejects) for n, r in results.items()},
        )
        for c in checks:
            if not c.passed:
                log.warning("DQ %s [%s] %s: %s", c.severity, c.table, c.name, c.detail)

        with open_warehouse(target, settings) as wh:
            wh.ensure_ops_tables()
            wh.record_checks(run_id, loaded_at, checks)
            assert_passed(checks)  # nothing reaches the warehouse if an error-level check fails

            _write_clean(clean, lake_dir, run_id)
            if upload_azure:
                from revintel.azure_storage import upload_batch

                metrics["blobs_uploaded"] = len(upload_batch(lake_dir, run_id, settings))

            if load_mode == "stage":
                if not isinstance(wh, SnowflakeWarehouse) or not upload_azure:
                    raise ValueError("load_mode='stage' needs a Snowflake target and --upload-azure")
                loaded = {t: wh.copy_from_stage(t, run_id) for t in config.TABLES}
            else:
                loaded = {t: wh.append_raw(t, clean[t], run_id) for t in config.TABLES}
        metrics["rows_loaded"] = loaded
        log.info("Loaded batch %s into RAW: %s", run_id, loaded)
        return metrics


def transform(
    target: Target,
    settings: Settings,
    *,
    full_refresh: bool = False,
    select: str | None = None,
    artifacts_dir: Path | None = None,
) -> dict[str, Any]:
    """Build and test all dbt models (staging -> snapshots -> marts)."""
    from revintel.dbt_runner import run_dbt

    with tracked_stage("transform", target, settings) as metrics:
        if target != "local":
            run_dbt(["source", "freshness"], target, settings, artifacts_dir)
        cmd = ["build"] + (["--full-refresh"] if full_refresh else []) + (["--select", select] if select else [])
        run_dbt(cmd, target, settings, artifacts_dir)
        metrics["dbt_command"] = " ".join(cmd)
        return metrics


def publish(target: Target, settings: Settings, *, export_dir: Path = config.OUTPUT_DIR / "powerbi") -> dict[str, Any]:
    """Local: export marts to CSV for Power BI Desktop. Cloud: refresh the Power BI dataset."""
    with tracked_stage("publish", target, settings) as metrics:
        if target == "local":
            with DuckDBWarehouse(settings.duckdb_path) as wh:
                metrics["exported"] = wh.export_csv(("core", "analytics"), export_dir)
            log.info("Exported %d tables to %s", len(metrics["exported"]), export_dir)
        elif settings.powerbi_dataset_id:
            from revintel.powerbi import refresh_dataset

            metrics["powerbi_refresh"] = refresh_dataset(settings)
        else:
            log.warning("POWERBI_DATASET_ID not set; skipping dataset refresh")
            metrics["powerbi_refresh"] = "skipped"
        return metrics
