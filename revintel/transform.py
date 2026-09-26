"""Clean, standardise and conform raw extracts with Pandas/NumPy.

Every cleaner returns a ``CleanResult`` with the conformed rows, the rejected
rows (with a ``reject_reason``) and how many duplicates were collapsed, so the
pipeline can reconcile raw counts against clean + rejected + deduplicated.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

EMAIL_PATTERN = r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$"
VALID_STATUSES = ("completed", "refunded", "cancelled")
SEGMENT_MAP = {"consumer": "Consumer", "smb": "SMB", "enterprise": "Enterprise"}
COUNTRY_ALIASES = {"UK": "GB"}


@dataclass
class CleanResult:
    data: pd.DataFrame
    rejects: pd.DataFrame
    duplicates_removed: int = 0


def _strip(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for col in cols:
        df[col] = df[col].astype("string").str.strip().replace("", pd.NA)
    return df


def _split(df: pd.DataFrame, rules: dict[str, pd.Series]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply reject rules in order; the first failing rule becomes the reject reason."""
    reason = pd.Series(pd.NA, index=df.index, dtype="object")
    for name, failed in rules.items():
        reason = reason.mask(reason.isna() & failed.fillna(True).astype(bool), name)
    bad = reason.notna()
    rejects = df[bad].assign(reject_reason=reason[bad])
    return df[~bad].copy(), rejects


def _dedupe(df: pd.DataFrame, keys: list[str], order_by: str | None = None) -> tuple[pd.DataFrame, int]:
    if order_by:
        df = df.sort_values(order_by, kind="stable")
    deduped = df.drop_duplicates(subset=keys, keep="last")
    return deduped.sort_values(keys, ignore_index=True), len(df) - len(deduped)


def clean_fx_rates(raw: pd.DataFrame) -> CleanResult:
    df = _strip(raw.copy(), ["currency"])
    df["currency"] = df["currency"].str.upper()
    df["rate_to_usd"] = pd.to_numeric(df["rate_to_usd"], errors="coerce")
    df, rejects = _split(df, {
        "missing_currency": df["currency"].isna(),
        "invalid_rate": ~(df["rate_to_usd"] > 0),
    })
    df, dupes = _dedupe(df, ["currency"])
    df["currency"] = df["currency"].astype(str)
    return CleanResult(df, rejects, dupes)


def clean_products(raw: pd.DataFrame) -> CleanResult:
    df = _strip(raw.copy(), ["product_id", "product_name", "category"])
    df["product_id"] = df["product_id"].str.upper()
    df["category"] = df["category"].str.title()
    df["list_price_usd"] = pd.to_numeric(df["list_price_usd"], errors="coerce").round(2)
    df, rejects = _split(df, {
        "missing_product_id": df["product_id"].isna(),
        "invalid_price": ~(df["list_price_usd"] > 0),
    })
    df, dupes = _dedupe(df, ["product_id"])
    return CleanResult(df, rejects, dupes)


def clean_customers(raw: pd.DataFrame) -> CleanResult:
    text_cols = ["customer_id", "first_name", "last_name", "email", "country", "segment", "acquisition_channel"]
    df = _strip(raw.copy(), text_cols)
    df["customer_id"] = df["customer_id"].str.upper()
    df["first_name"] = df["first_name"].str.title()
    df["last_name"] = df["last_name"].str.title()
    df["email"] = df["email"].str.lower()
    df["country"] = df["country"].str.upper().replace(COUNTRY_ALIASES).fillna("UNKNOWN")
    df["segment"] = df["segment"].str.lower().map(SEGMENT_MAP)
    df["acquisition_channel"] = df["acquisition_channel"].fillna("Unknown")
    # The CRM migration left two date formats behind ("2024-03-01" and "01 Mar 2024")
    df["signup_date"] = pd.to_datetime(df["signup_date"], format="mixed", errors="coerce").dt.date
    df["updated_at"] = pd.to_datetime(df["updated_at"], errors="coerce")

    df, rejects = _split(df, {
        "missing_customer_id": df["customer_id"].isna(),
        "invalid_email": ~df["email"].str.match(EMAIL_PATTERN),
        "invalid_signup_date": df["signup_date"].isna(),
        "unknown_segment": df["segment"].isna(),
    })
    # Keep the most recently updated version of each customer
    df, dupes = _dedupe(df, ["customer_id"], order_by="updated_at")
    return CleanResult(df.drop(columns="updated_at"), rejects, dupes)


def clean_orders(raw: pd.DataFrame, valid_customer_ids: pd.Series, valid_currencies: pd.Series) -> CleanResult:
    df = _strip(raw.copy(), ["order_id", "customer_id", "status", "currency", "sales_channel"])
    df["order_id"] = df["order_id"].str.upper()
    df["customer_id"] = df["customer_id"].str.upper()
    df["status"] = df["status"].str.lower()
    df["currency"] = df["currency"].str.upper()
    df["sales_channel"] = df["sales_channel"].str.lower().fillna("unknown")
    # Normalise to naive UTC so it maps cleanly to TIMESTAMP_NTZ
    df["order_ts"] = pd.to_datetime(df["order_ts"], format="mixed", utc=True, errors="coerce").dt.tz_convert(None)
    df["ingested_at"] = pd.to_datetime(df["ingested_at"], format="mixed", utc=True, errors="coerce")
    df["discount_pct"] = pd.to_numeric(df["discount_pct"], errors="coerce").fillna(0).clip(0, 0.5)

    df, rejects = _split(df, {
        "missing_order_id": df["order_id"].isna(),
        "missing_order_ts": df["order_ts"].isna(),
        "invalid_status": ~df["status"].isin(VALID_STATUSES),
        "unknown_currency": ~df["currency"].isin(valid_currencies),
        "orphan_customer": ~df["customer_id"].isin(valid_customer_ids),
    })
    # CDC feed can redeliver an order; the latest delivery wins
    df, dupes = _dedupe(df, ["order_id"], order_by="ingested_at")
    return CleanResult(df.drop(columns="ingested_at"), rejects, dupes)


def clean_order_items(raw: pd.DataFrame, valid_order_ids: pd.Series, valid_product_ids: pd.Series) -> CleanResult:
    df = _strip(raw.copy(), ["order_id", "product_id"])
    df["order_id"] = df["order_id"].str.upper()
    df["product_id"] = df["product_id"].str.upper()
    df["line_number"] = pd.to_numeric(df["line_number"], errors="coerce").astype("Int64")
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").astype("Int64")
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce").round(2)

    df, rejects = _split(df, {
        "orphan_order": ~df["order_id"].isin(valid_order_ids),
        "unknown_product": ~df["product_id"].isin(valid_product_ids),
        "missing_line_number": df["line_number"].isna(),
        "non_positive_quantity": ~(df["quantity"] > 0),
        "invalid_unit_price": ~(df["unit_price"] > 0),
    })
    df, dupes = _dedupe(df, ["order_id", "line_number"])
    df["line_number"] = df["line_number"].astype(np.int64)
    df["quantity"] = df["quantity"].astype(np.int64)
    return CleanResult(df, rejects, dupes)


def transform_all(raw: dict[str, pd.DataFrame]) -> dict[str, CleanResult]:
    fx = clean_fx_rates(raw["fx_rates"])
    products = clean_products(raw["products"])
    customers = clean_customers(raw["customers"])
    orders = clean_orders(raw["orders"], customers.data["customer_id"], fx.data["currency"])
    items = clean_order_items(raw["order_items"], orders.data["order_id"], products.data["product_id"])

    # An order whose every line was rejected carries no revenue we can trust
    has_items = orders.data["order_id"].isin(items.data["order_id"])
    empty = orders.data[~has_items].assign(reject_reason="no_valid_items")
    orders = CleanResult(
        orders.data[has_items].reset_index(drop=True),
        pd.concat([orders.rejects, empty], ignore_index=True),
        orders.duplicates_removed,
    )
    return {"fx_rates": fx, "products": products, "customers": customers, "orders": orders, "order_items": items}
