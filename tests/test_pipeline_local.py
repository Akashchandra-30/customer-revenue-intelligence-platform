"""End-to-end: generate -> clean -> validate -> DuckDB running the Snowflake SQL."""
import duckdb
import pandas as pd
import pytest

from revintel.pipeline import run


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory):
    base = tmp_path_factory.mktemp("revintel")
    summary = run(target="local", generate_data=True, n_customers=400, seed=7,
                  raw_dir=base / "raw", clean_dir=base / "clean", rejects_dir=base / "rejects",
                  output_dir=base / "output")
    con = duckdb.connect(str(base / "output" / "revintel.duckdb"), read_only=True)
    yield summary, con, base
    con.close()


def test_all_models_built(warehouse):
    summary, _, _ = warehouse
    for obj in ("core.fct_orders", "core.dim_customer", "analytics.monthly_revenue",
                "analytics.customer_ltv", "analytics.cohort_retention", "analytics.rfm_segments"):
        assert summary["row_counts"][obj] > 0, obj


def test_sql_revenue_reconciles_with_pandas(warehouse):
    _, con, base = warehouse
    orders = pd.read_parquet(base / "clean" / "orders.parquet")
    items = pd.read_parquet(base / "clean" / "order_items.parquet")
    fx = pd.read_parquet(base / "clean" / "fx_rates.parquet")
    lines = items.merge(orders, on="order_id").merge(fx, on="currency")
    lines = lines[lines["status"] == "completed"]
    expected = (lines["quantity"] * lines["unit_price"] * lines["rate_to_usd"] * (1 - lines["discount_pct"])).round(2).sum()

    actual = con.execute("SELECT SUM(revenue_usd) FROM analytics.monthly_revenue").fetchone()[0]
    # SQL rounds half-up, pandas half-to-even: allow half a cent per line
    assert float(actual) == pytest.approx(expected, abs=0.005 * len(lines))


def test_cohort_month_zero_is_full_retention(warehouse):
    _, con, _ = warehouse
    rates = con.execute("SELECT DISTINCT retention_rate FROM analytics.cohort_retention "
                        "WHERE months_since_first = 0").fetchall()
    assert rates == [(1.0,)]


def test_customer_ltv_one_row_per_paying_customer(warehouse):
    _, con, _ = warehouse
    total, distinct = con.execute("SELECT COUNT(*), COUNT(DISTINCT customer_id) FROM analytics.customer_ltv").fetchone()
    assert total == distinct
    share = con.execute("SELECT MAX(cumulative_revenue_share) FROM analytics.customer_ltv").fetchone()[0]
    assert float(share) == pytest.approx(1.0)


def test_rfm_scores_in_range(warehouse):
    _, con, _ = warehouse
    lo, hi = con.execute("SELECT MIN(LEAST(r_score, f_score, m_score)), MAX(GREATEST(r_score, f_score, m_score)) "
                         "FROM analytics.rfm_segments").fetchone()
    assert (lo, hi) == (1, 5)
