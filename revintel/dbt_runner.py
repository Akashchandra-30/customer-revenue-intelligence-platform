"""Invoke dbt programmatically so the pipeline, Airflow and CI share one entry point."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from revintel.config import DBT_DIR, Settings, Target

log = logging.getLogger(__name__)

# Settings exported to the environment for dbt's profiles.yml (env_var(...))
_DBT_ENV = (
    "snowflake_account",
    "snowflake_user",
    "snowflake_private_key",
    "snowflake_private_key_passphrase",
    "snowflake_warehouse",
    "snowflake_database",
)


class DbtError(RuntimeError):
    pass


def _export_env(settings: Settings) -> None:
    os.environ["REVINTEL_DUCKDB_PATH"] = str(settings.duckdb_path.resolve())
    for name in _DBT_ENV:
        value = getattr(settings, name)
        if value is None:
            continue
        os.environ.setdefault(
            name.upper(), value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)
        )


def _invoke(args: list[str]) -> None:
    from dbt.cli.main import dbtRunner

    log.info("dbt %s", " ".join(args))
    result = dbtRunner().invoke(args)
    if not result.success:
        raise DbtError(f"dbt {args[0]} failed" + (f": {result.exception}" if result.exception else ""))


def run_dbt(command: list[str], target: Target, settings: Settings, artifacts_dir: Path | None = None) -> None:
    """Run a dbt command, e.g. ``run_dbt(["build"], "local", settings)``."""
    _export_env(settings)
    common = ["--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)]
    if not (DBT_DIR / "dbt_packages").exists():
        _invoke(["deps", *common])
    args = [*command, *common, "--target", target]
    if artifacts_dir is not None:
        args += ["--target-path", str(artifacts_dir / "target"), "--log-path", str(artifacts_dir / "logs")]
    _invoke(args)
