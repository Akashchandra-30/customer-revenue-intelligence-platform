"""Project paths and environment-driven settings for Azure and Snowflake."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CLEAN_DIR = DATA_DIR / "clean"
REJECTS_DIR = DATA_DIR / "rejects"
OUTPUT_DIR = ROOT / "output"
SQL_DIR = ROOT / "sql"

# Load order matters: parents before children.
TABLES = ("fx_rates", "products", "customers", "orders", "order_items")


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name} (see .env.example)")
    return value


@dataclass(frozen=True)
class SnowflakeSettings:
    account: str
    user: str
    password: str
    role: str
    warehouse: str
    database: str

    @classmethod
    def from_env(cls) -> "SnowflakeSettings":
        return cls(
            account=_require("SNOWFLAKE_ACCOUNT"),
            user=_require("SNOWFLAKE_USER"),
            password=_require("SNOWFLAKE_PASSWORD"),
            role=os.getenv("SNOWFLAKE_ROLE", "REVINTEL_LOADER"),
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "REVINTEL_WH"),
            database=os.getenv("SNOWFLAKE_DATABASE", "REVINTEL"),
        )


@dataclass(frozen=True)
class AzureSettings:
    connection_string: str
    container: str

    @classmethod
    def from_env(cls) -> "AzureSettings":
        return cls(
            connection_string=_require("AZURE_STORAGE_CONNECTION_STRING"),
            container=os.getenv("AZURE_STORAGE_CONTAINER", "revintel"),
        )
