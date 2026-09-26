"""Local stand-in for Snowflake.

Loads the clean Parquet layer into DuckDB and executes the *same* Snowflake SQL
files (transpiled with sqlglot), so models and metrics can be developed and
tested offline, and exports CSVs Power BI can use without a warehouse.
"""
from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import sqlglot

from revintel.config import TABLES

log = logging.getLogger(__name__)

MODEL_FILES = ("03_core_models.sql", "04_analytics_views.sql")


def snowflake_to_duckdb(sql: str) -> list[str]:
    return [s for s in sqlglot.transpile(sql, read="snowflake", write="duckdb") if s.strip()]


def _quote_path(path: Path) -> str:
    return "'" + path.resolve().as_posix().replace("'", "''") + "'"


def build_local_warehouse(clean_dir: Path, sql_dir: Path, db_path: Path, export_dir: Path | None = None) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        for schema in ("raw", "core", "analytics"):
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        for table in TABLES:
            con.execute(
                f"CREATE OR REPLACE TABLE raw.{table} AS "
                f"SELECT * FROM read_parquet({_quote_path(clean_dir / f'{table}.parquet')})"
            )
        for filename in MODEL_FILES:
            statements = snowflake_to_duckdb((sql_dir / filename).read_text(encoding="utf-8"))
            for stmt in statements:
                con.execute(stmt)
            log.info("Executed %s (%d statements)", filename, len(statements))

        objects = con.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema IN ('core', 'analytics') ORDER BY 1, 2"
        ).fetchall()
        counts = {f"{s}.{t}": con.execute(f"SELECT COUNT(*) FROM {s}.{t}").fetchone()[0] for s, t in objects}

        if export_dir is not None:
            export_dir.mkdir(parents=True, exist_ok=True)
            for schema, table in objects:
                target = export_dir / f"{table}.csv"
                con.execute(f"COPY (SELECT * FROM {schema}.{table}) TO {_quote_path(target)} (HEADER, DELIMITER ',')")
            log.info("Exported %d tables/views to %s", len(objects), export_dir)

        kpis = con.execute("SELECT * FROM analytics.kpi_summary").df().iloc[0].to_dict()
        return {"row_counts": counts, "kpis": kpis}
    finally:
        con.close()
