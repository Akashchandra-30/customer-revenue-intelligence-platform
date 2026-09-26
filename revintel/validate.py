"""Data-quality gate run on the cleaned tables before anything is loaded to Snowflake."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from revintel.transform import VALID_STATUSES, CleanResult


class DataQualityError(RuntimeError):
    pass


@dataclass
class Check:
    name: str
    table: str
    passed: bool
    detail: str
    severity: str = "error"

    def to_dict(self) -> dict:
        return asdict(self)


def unique(df: pd.DataFrame, table: str, cols: list[str]) -> Check:
    dupes = int(df.duplicated(subset=cols).sum())
    return Check(f"unique({', '.join(cols)})", table, dupes == 0, f"{dupes} duplicate keys")


def not_null(df: pd.DataFrame, table: str, cols: list[str]) -> Check:
    nulls = {c: int(df[c].isna().sum()) for c in cols}
    bad = {c: n for c, n in nulls.items() if n}
    return Check(f"not_null({', '.join(cols)})", table, not bad, f"nulls: {bad}" if bad else "no nulls")


def accepted_values(df: pd.DataFrame, table: str, col: str, allowed) -> Check:
    bad = sorted(set(df[col].dropna()) - set(allowed))
    return Check(f"accepted_values({col})", table, not bad, f"unexpected: {bad}" if bad else "all valid")


def relationship(child: pd.DataFrame, table: str, col: str, parent: pd.DataFrame, parent_col: str) -> Check:
    orphans = int((~child[col].isin(parent[parent_col])).sum())
    return Check(f"relationship({col} -> {parent_col})", table, orphans == 0, f"{orphans} orphan rows")


def positive(df: pd.DataFrame, table: str, col: str) -> Check:
    bad = int((df[col] <= 0).sum())
    return Check(f"positive({col})", table, bad == 0, f"{bad} non-positive values")


def min_rows(df: pd.DataFrame, table: str, n: int) -> Check:
    return Check(f"min_rows({n})", table, len(df) >= n, f"{len(df)} rows")


def reconciliation(raw: dict[str, pd.DataFrame], results: dict[str, CleanResult]) -> list[Check]:
    checks = []
    for name, res in results.items():
        accounted = len(res.data) + len(res.rejects) + res.duplicates_removed
        checks.append(
            Check(
                "row_reconciliation",
                name,
                accounted == len(raw[name]),
                f"raw={len(raw[name])} clean={len(res.data)} rejected={len(res.rejects)} "
                f"deduped={res.duplicates_removed}",
            )
        )
        reject_rate = len(res.rejects) / max(len(raw[name]), 1)
        checks.append(Check("reject_rate<5%", name, reject_rate < 0.05, f"{reject_rate:.2%} rejected", "warning"))
    return checks


def run_checks(tables: dict[str, pd.DataFrame]) -> list[Check]:
    c, o, i, p, fx = (tables[k] for k in ("customers", "orders", "order_items", "products", "fx_rates"))
    return [
        min_rows(c, "customers", 1),
        unique(c, "customers", ["customer_id"]),
        not_null(c, "customers", ["customer_id", "email", "signup_date", "segment"]),
        unique(p, "products", ["product_id"]),
        positive(p, "products", "list_price_usd"),
        unique(fx, "fx_rates", ["currency"]),
        min_rows(o, "orders", 1),
        unique(o, "orders", ["order_id"]),
        not_null(o, "orders", ["order_id", "customer_id", "order_ts", "status", "currency"]),
        accepted_values(o, "orders", "status", VALID_STATUSES),
        relationship(o, "orders", "customer_id", c, "customer_id"),
        relationship(o, "orders", "currency", fx, "currency"),
        unique(i, "order_items", ["order_id", "line_number"]),
        relationship(i, "order_items", "order_id", o, "order_id"),
        relationship(i, "order_items", "product_id", p, "product_id"),
        positive(i, "order_items", "quantity"),
        positive(i, "order_items", "unit_price"),
    ]


def assert_passed(checks: list[Check]) -> None:
    failed = [c for c in checks if not c.passed and c.severity == "error"]
    if failed:
        lines = "\n".join(f"  - [{c.table}] {c.name}: {c.detail}" for c in failed)
        raise DataQualityError(f"{len(failed)} data-quality check(s) failed:\n{lines}")
