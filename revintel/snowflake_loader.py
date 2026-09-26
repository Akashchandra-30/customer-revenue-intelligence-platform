"""Load validated data into Snowflake and build the CORE and ANALYTICS layers."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from revintel.config import TABLES, SnowflakeSettings

log = logging.getLogger(__name__)


def _connect(settings: SnowflakeSettings):
    import snowflake.connector

    return snowflake.connector.connect(
        account=settings.account,
        user=settings.user,
        password=settings.password,
        role=settings.role,
        warehouse=settings.warehouse,
        database=settings.database,
        application="revintel-pipeline",
    )


def run_sql_file(conn, path: Path) -> int:
    cursors = conn.execute_string(path.read_text(encoding="utf-8"))
    log.info("Executed %s (%d statements)", path.name, len(cursors))
    return len(cursors)


def load_to_snowflake(tables: dict[str, pd.DataFrame], settings: SnowflakeSettings, sql_dir: Path,
                      via_azure_stage: bool = False) -> dict[str, int]:
    """Refresh RAW (direct write_pandas, or COPY INTO from the Azure stage), then rebuild models."""
    from snowflake.connector.pandas_tools import write_pandas

    conn = _connect(settings)
    try:
        run_sql_file(conn, sql_dir / "01_raw_tables.sql")
        if via_azure_stage:
            run_sql_file(conn, sql_dir / "02_load_from_azure_stage.sql")
        else:
            cur = conn.cursor()
            for name in TABLES:
                cur.execute(f"TRUNCATE TABLE raw.{name}")
                ok, _, nrows, _ = write_pandas(
                    conn, tables[name], table_name=name.upper(), schema="RAW",
                    quote_identifiers=False, use_logical_type=True,
                )
                if not ok:
                    raise RuntimeError(f"write_pandas failed for raw.{name}")
                log.info("Loaded %d rows into RAW.%s", nrows, name.upper())

        run_sql_file(conn, sql_dir / "03_core_models.sql")
        run_sql_file(conn, sql_dir / "04_analytics_views.sql")

        cur = conn.cursor()
        counts = {}
        for obj in ("core.fct_orders", "core.dim_customer", "analytics.customer_ltv", "analytics.monthly_revenue"):
            counts[obj] = cur.execute(f"SELECT COUNT(*) FROM {obj}").fetchone()[0]
        return counts
    finally:
        conn.close()
