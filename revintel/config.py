"""Project paths and typed, environment-driven settings.

Values come from environment variables (or a local ``.env``). In Azure they are
injected from Key Vault into the Container Apps job; nothing secret lives in code.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# REVINTEL_HOME lets an installed package (e.g. in the Docker image) find dbt/ and sql/
ROOT = Path(os.getenv("REVINTEL_HOME", Path(__file__).resolve().parent.parent))
DATA_DIR = ROOT / "data"
LANDING_DIR = DATA_DIR / "landing"  # source-system extracts as delivered
LAKE_DIR = DATA_DIR / "lake"  # local mirror of the Azure container layout
OUTPUT_DIR = ROOT / "output"
SQL_DIR = ROOT / "sql"
DBT_DIR = ROOT / "dbt"

# Load order matters: parents before children.
TABLES = ("fx_rates", "products", "customers", "orders", "order_items")

Target = Literal["local", "dev", "prod"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", populate_by_name=True)

    log_format: Literal["text", "json"] = "text"
    log_level: str = "INFO"
    duckdb_path: Path = Field(
        OUTPUT_DIR / "revintel.duckdb", validation_alias=AliasChoices("REVINTEL_DUCKDB_PATH", "DUCKDB_PATH")
    )

    # Snowflake: key-pair auth for services (prod), SSO for developers (dev), password as a fallback
    snowflake_account: str | None = None
    snowflake_user: str | None = None
    snowflake_private_key: SecretStr | None = None  # PEM content (from Key Vault)
    snowflake_private_key_passphrase: SecretStr | None = None
    snowflake_password: SecretStr | None = None
    snowflake_authenticator: str = "externalbrowser"
    snowflake_role: str = "REVINTEL_LOADER"
    snowflake_warehouse: str = "REVINTEL_WH"
    snowflake_database: str = "REVINTEL"

    # Azure Data Lake: managed identity via account URL (preferred) or a connection string
    azure_storage_account_url: str | None = None
    azure_storage_connection_string: SecretStr | None = None
    azure_storage_container: str = "revintel"

    # Power BI service principal for dataset refresh
    powerbi_tenant_id: str | None = None
    powerbi_client_id: str | None = None
    powerbi_client_secret: SecretStr | None = None
    powerbi_workspace_id: str | None = None
    powerbi_dataset_id: str | None = None

    # Slack / Teams incoming webhook for failure alerts
    alert_webhook_url: SecretStr | None = None

    def require(self, *names: str) -> None:
        missing = [n.upper() for n in names if getattr(self, n) in (None, "")]
        if missing:
            raise RuntimeError(f"Missing required settings: {', '.join(missing)} (see .env.example)")


@lru_cache
def get_settings() -> Settings:
    return Settings()
