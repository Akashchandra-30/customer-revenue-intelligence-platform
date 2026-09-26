import pandas as pd

from revintel.transform import clean_customers, clean_order_items, clean_orders


def test_clean_customers_standardises_and_keeps_latest_version():
    raw = pd.DataFrame(
        {
            "customer_id": ["C1", "C1", "c2", "C3"],
            "first_name": ["  ada ", "ADA", "Grace", "Alan"],
            "last_name": ["lovelace", "Lovelace", "hopper", "turing"],
            "email": ["ADA@Example.com", "ada@example.com", "grace@example.com", "not-an-email"],
            "country": ["uk", "GB", None, "US"],
            "segment": ["CONSUMER", "consumer", "smb", "Enterprise"],
            "acquisition_channel": ["Organic", "Organic", "Referral", "Partner"],
            "signup_date": ["2024-03-01", "01 Mar 2024", "15 Jan 2025", "2023-06-30"],
            "updated_at": ["2024-05-01 00:00:00", "2022-12-31 00:00:00", "2025-02-01 00:00:00", "2023-07-01 00:00:00"],
        }
    )
    res = clean_customers(raw)
    df = res.data.set_index("customer_id")

    assert list(df.index) == ["C1", "C2"]
    assert res.duplicates_removed == 1
    assert df.loc["C1", "first_name"] == "Ada"  # latest record wins, trimmed + title-cased
    assert df.loc["C1", "email"] == "ada@example.com"
    assert df.loc["C1", "country"] == "GB"  # alias uk -> GB
    assert df.loc["C2", "country"] == "UNKNOWN"
    assert df.loc["C2", "segment"] == "SMB"
    assert str(df.loc["C2", "signup_date"]) == "2025-01-15"
    assert res.rejects["reject_reason"].tolist() == ["invalid_email"]


def test_clean_orders_rejects_bad_rows_and_dedupes_cdc_redelivery():
    raw = pd.DataFrame(
        {
            "order_id": ["SO1", "SO1", "SO2", "SO3", "SO4"],
            "customer_id": ["C1", "C1", "C1", "C404", "C1"],
            "order_ts": [
                "2025-01-01T10:00:00Z",
                "2025-01-01 10:00:00",
                None,
                "2025-01-02T10:00:00Z",
                "2025-01-03T10:00:00Z",
            ],
            "currency": ["usd", "USD", "USD", "USD", "XYZ"],
            "status": ["COMPLETED", "refunded", "completed", "completed", "completed"],
            "sales_channel": ["web", "web", "web", "web", "web"],
            "discount_pct": [0.1, 0.1, 0, 0, 0.9],
            "ingested_at": [
                "2025-01-01T11:00:00Z",
                "2025-01-05T00:00:00Z",
                "2025-01-01T11:00:00Z",
                "2025-01-02T11:00:00Z",
                "2025-01-03T11:00:00Z",
            ],
        }
    )
    res = clean_orders(raw, pd.Series(["C1"]), pd.Series(["USD"]))

    assert res.data["order_id"].tolist() == ["SO1"]
    assert res.data.loc[0, "status"] == "refunded"  # later CDC delivery wins
    assert res.duplicates_removed == 1
    assert dict(zip(res.rejects["order_id"], res.rejects["reject_reason"], strict=True)) == {
        "SO2": "missing_order_ts",
        "SO3": "orphan_customer",
        "SO4": "unknown_currency",
    }


def test_clean_order_items_rejects_invalid_lines():
    raw = pd.DataFrame(
        {
            "order_id": ["SO1", "SO1", "SO1", "SO9", "SO1"],
            "line_number": ["1", "2", "3", "1", "1"],
            "product_id": ["p0001", "P0001", "P0001", "P0001", "P0001"],
            "quantity": ["2", "0", "1", "1", "2"],
            "unit_price": ["10.5", "10", None, "3", "10.5"],
        }
    )
    res = clean_order_items(raw, pd.Series(["SO1"]), pd.Series(["P0001"]))

    assert len(res.data) == 1 and res.data.loc[0, "product_id"] == "P0001"
    assert res.duplicates_removed == 1
    assert sorted(res.rejects["reject_reason"]) == ["invalid_unit_price", "non_positive_quantity", "orphan_order"]
