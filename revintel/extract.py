"""Extract raw source-system files into DataFrames (all as strings; typing happens in transform)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

SOURCES = {
    "customers": ("crm", "customers.csv"),
    "orders": ("erp", "orders.jsonl"),
    "order_items": ("erp", "order_items.csv"),
    "products": ("catalog", "products.csv"),
    "fx_rates": ("finance", "fx_rates.csv"),
}


def extract_all(raw_dir: Path) -> dict[str, pd.DataFrame]:
    frames = {}
    for name, (system, filename) in SOURCES.items():
        path = raw_dir / system / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing source extract: {path}")
        if path.suffix == ".jsonl":
            df = pd.read_json(path, lines=True, dtype=False, convert_dates=False)
            df = df.astype(object).where(df.notna(), None)
        else:
            df = pd.read_csv(path, dtype=str, keep_default_na=True)
        frames[name] = df
    return frames
