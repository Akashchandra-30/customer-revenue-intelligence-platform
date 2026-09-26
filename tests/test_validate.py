import pandas as pd
import pytest

from revintel.validate import DataQualityError, assert_passed, relationship, run_checks, unique


def _tables():
    return {
        "customers": pd.DataFrame(
            {"customer_id": ["C1"], "email": ["a@b.com"], "signup_date": ["2024-01-01"], "segment": ["SMB"]}
        ),
        "orders": pd.DataFrame(
            {
                "order_id": ["SO1"],
                "customer_id": ["C1"],
                "order_ts": ["2024-02-01"],
                "status": ["completed"],
                "currency": ["USD"],
            }
        ),
        "order_items": pd.DataFrame(
            {"order_id": ["SO1"], "line_number": [1], "product_id": ["P1"], "quantity": [1], "unit_price": [9.99]}
        ),
        "products": pd.DataFrame({"product_id": ["P1"], "list_price_usd": [9.99]}),
        "fx_rates": pd.DataFrame({"currency": ["USD"], "rate_to_usd": [1.0]}),
    }


def test_clean_tables_pass():
    assert_passed(run_checks(_tables()))


def test_detects_duplicates_and_orphans():
    df = pd.DataFrame({"id": [1, 1, 2]})
    assert not unique(df, "t", ["id"]).passed
    assert not relationship(pd.DataFrame({"fk": [1, 3]}), "t", "fk", df, "id").passed


def test_gate_raises_on_failure():
    tables = _tables()
    tables["orders"].loc[0, "status"] = "shipped"
    with pytest.raises(DataQualityError, match="accepted_values"):
        assert_passed(run_checks(tables))
