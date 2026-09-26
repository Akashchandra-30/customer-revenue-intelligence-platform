"""Warehouse adapters.

``DuckDBWarehouse`` is the local/CI stand-in; ``SnowflakeWarehouse`` is the real
target. Both expose the same operations, so the pipeline and the dbt project are
identical in every environment.

RAW is append-only. Every row carries ``_batch_id`` and ``_loaded_at``, and a
batch is deleted before it is (re)loaded, so retries are idempotent. dbt staging
models pick the latest version of each record.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Self

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from revintel.config import SQL_DIR, Settings, Target
from revintel.validate import Check

log = logging.getLogger(__name__)

OPS_DDL = (
    """create table if not exists ops.pipeline_runs (
        run_id varchar, stage varchar, target varchar, status varchar,
        started_at timestamp, finished_at timestamp, duration_seconds double,
        metrics varchar, error_message varchar)""",
    """create table if not exists ops.dq_results (
        run_id varchar, checked_at timestamp, table_name varchar, check_name varchar,
        severity varchar, passed boolean, detail varchar)""",
)


class Warehouse(ABC):
    dbt_target: Target

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @abstractmethod
    def execute(self, sql: str, params: list | None = None) -> None: ...

    @abstractmethod
    def insert_rows(self, table: str, rows: list[dict[str, Any]]) -> None: ...

    @abstractmethod
    def append_raw(self, table: str, df: pd.DataFrame, batch_id: str) -> int: ...

    @abstractmethod
    def close(self) -> None: ...

    def ensure_ops_tables(self) -> None:
        for ddl in OPS_DDL:
            self.execute(ddl)

    def record_run(
        self,
        run_id: str,
        stage: str,
        status: str,
        started_at: datetime,
        finished_at: datetime,
        metrics: dict,
        error: str | None,
    ) -> None:
        self.insert_rows(
            "ops.pipeline_runs",
            [
                {
                    "run_id": run_id,
                    "stage": stage,
                    "target": self.dbt_target,
                    "status": status,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
                    "metrics": json.dumps(metrics, default=str),
                    "error_message": error,
                }
            ],
        )

    def record_checks(self, run_id: str, checked_at: datetime, checks: list[Check]) -> None:
        self.insert_rows(
            "ops.dq_results",
            [
                {
                    "run_id": run_id,
                    "checked_at": checked_at,
                    "table_name": c.table,
                    "check_name": c.name,
                    "severity": c.severity,
                    "passed": c.passed,
                    "detail": c.detail,
                }
                for c in checks
            ],
        )


class DuckDBWarehouse(Warehouse):
    dbt_target: Target = "local"

    def __init__(self, path: Path):
        import duckdb

        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.con = duckdb.connect(str(path))
        for schema in ("raw", "ops"):
            self.con.execute(f"create schema if not exists {schema}")

    def execute(self, sql: str, params: list | None = None) -> None:
        self.con.execute(sql, params or [])

    def insert_rows(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        cols = list(rows[0])
        sql = f"insert into {table} ({', '.join(cols)}) values ({', '.join('?' * len(cols))})"
        self.con.executemany(sql, [[r[c] for c in cols] for r in rows])

    def append_raw(self, table: str, df: pd.DataFrame, batch_id: str) -> int:
        self.con.register("incoming", df)
        try:
            self.con.execute(f"create table if not exists raw.{table} as select * from incoming limit 0")
            self.con.execute(f"delete from raw.{table} where _batch_id = ?", [batch_id])
            self.con.execute(f"insert into raw.{table} by name select * from incoming")
        finally:
            self.con.unregister("incoming")
        return len(df)

    def export_csv(self, schemas: tuple[str, ...], out_dir: Path) -> list[str]:
        out_dir.mkdir(parents=True, exist_ok=True)
        placeholders = ", ".join("?" * len(schemas))
        objects = self.con.execute(
            f"select table_schema, table_name from information_schema.tables "
            f"where table_schema in ({placeholders}) order by 1, 2",
            list(schemas),
        ).fetchall()
        for schema, name in objects:
            target = (out_dir / f"{name}.csv").resolve().as_posix().replace("'", "''")
            self.con.execute(f"copy (select * from {schema}.{name}) to '{target}' (header, delimiter ',')")
        return [f"{s}.{n}" for s, n in objects]

    def close(self) -> None:
        self.con.close()


def _private_key_der(pem: str, passphrase: str | None) -> bytes:
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(pem.encode(), password=passphrase.encode() if passphrase else None)
    return key.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


class SnowflakeWarehouse(Warehouse):
    def __init__(self, settings: Settings, dbt_target: Target):
        settings.require("snowflake_account", "snowflake_user")
        self.dbt_target = dbt_target
        kwargs: dict[str, Any] = {
            "account": settings.snowflake_account,
            "user": settings.snowflake_user,
            "role": settings.snowflake_role,
            "warehouse": settings.snowflake_warehouse,
            "database": settings.snowflake_database,
            "application": "revintel-pipeline",
            "session_parameters": {"QUERY_TAG": f"revintel:{dbt_target}"},
        }
        if settings.snowflake_private_key:
            passphrase = settings.snowflake_private_key_passphrase
            kwargs["private_key"] = _private_key_der(
                settings.snowflake_private_key.get_secret_value(), passphrase.get_secret_value() if passphrase else None
            )
        elif settings.snowflake_password:
            kwargs["password"] = settings.snowflake_password.get_secret_value()
        else:
            kwargs["authenticator"] = settings.snowflake_authenticator
        self.con = self._connect(**kwargs)
        for _ in self.con.execute_string((SQL_DIR / "01_raw_tables.sql").read_text(encoding="utf-8")):
            pass

    @staticmethod
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, max=30), reraise=True)
    def _connect(**kwargs: Any):
        import snowflake.connector

        return snowflake.connector.connect(**kwargs)

    def execute(self, sql: str, params: list | None = None) -> None:
        self.con.cursor().execute(sql, params)

    def insert_rows(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        cols = list(rows[0])
        sql = f"insert into {table} ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))})"
        self.con.cursor().executemany(sql, [[r[c] for c in cols] for r in rows])

    def append_raw(self, table: str, df: pd.DataFrame, batch_id: str) -> int:
        from snowflake.connector.pandas_tools import write_pandas

        self.execute(f"delete from raw.{table} where _batch_id = %s", [batch_id])
        ok, _, nrows, _ = write_pandas(
            self.con,
            df,
            table_name=table.upper(),
            schema="RAW",
            quote_identifiers=False,
            use_logical_type=True,
            auto_create_table=False,
        )
        if not ok:
            raise RuntimeError(f"write_pandas failed for raw.{table}")
        return nrows

    def copy_from_stage(self, table: str, batch_id: str) -> int:
        """Bulk-load one batch's Parquet files from the Azure external stage."""
        self.execute(f"delete from raw.{table} where _batch_id = %s", [batch_id])
        cur = self.con.cursor()
        cur.execute(
            f"copy into raw.{table} from @raw.azure_clean_stage/{table}/batch_id={batch_id}/ "
            "file_format = (format_name = 'raw.parquet_fmt') match_by_column_name = case_insensitive "
            "on_error = abort_statement force = true"
        )
        return sum(int(row[3]) for row in cur.fetchall() if len(row) > 3 and str(row[3]).isdigit())

    def close(self) -> None:
        self.con.close()


def open_warehouse(target: Target, settings: Settings) -> Warehouse:
    if target == "local":
        return DuckDBWarehouse(settings.duckdb_path)
    return SnowflakeWarehouse(settings, target)
