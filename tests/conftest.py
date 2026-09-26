import pytest

from revintel.config import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Isolated settings: DuckDB file in a temp dir, no cloud credentials."""
    return Settings(duckdb_path=tmp_path / "revintel.duckdb", alert_webhook_url=None, _env_file=None)
