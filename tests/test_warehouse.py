from datetime import datetime

import pandas as pd

from revintel.validate import Check
from revintel.warehouse import DuckDBWarehouse


def _batch(batch_id: str) -> pd.DataFrame:
    return pd.DataFrame({"id": [1, 2], "_batch_id": batch_id, "_loaded_at": datetime(2026, 1, 1)})


def test_reloading_a_batch_is_idempotent(settings):
    with DuckDBWarehouse(settings.duckdb_path) as wh:
        wh.append_raw("things", _batch("b1"), "b1")
        wh.append_raw("things", _batch("b1"), "b1")  # retry of the same batch
        wh.append_raw("things", _batch("b2"), "b2")
        rows = wh.con.execute("select _batch_id, count(*) from raw.things group by 1 order by 1").fetchall()
    assert rows == [("b1", 2), ("b2", 2)]


def test_audit_records(settings):
    now = datetime(2026, 1, 1, 12)
    with DuckDBWarehouse(settings.duckdb_path) as wh:
        wh.ensure_ops_tables()
        wh.record_run("r1", "ingest", "failed", now, now, {"rows": 3}, "boom")
        wh.record_checks("r1", now, [Check("unique(id)", "t", False, "1 duplicate")])
        run = wh.con.execute("select stage, status, metrics, error_message from ops.pipeline_runs").fetchone()
        check = wh.con.execute("select table_name, passed from ops.dq_results").fetchone()
    assert run == ("ingest", "failed", '{"rows": 3}', "boom")
    assert check == ("t", False)
