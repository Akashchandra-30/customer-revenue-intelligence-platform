"""Generate realistic, deliberately messy source-system extracts.

Simulates four upstream systems feeding the platform:
  * CRM            -> crm/customers.csv          (customer master)
  * ERP            -> erp/orders.jsonl           (order headers, JSON lines)
                   -> erp/order_items.csv        (order lines)
  * Product catalog-> catalog/products.csv
  * Finance        -> finance/fx_rates.csv       (currency -> USD rates)

Real extracts are never clean, so this injects the usual problems: duplicate
records, inconsistent casing/whitespace, mixed date formats, orphan keys,
missing values and invalid quantities. The ETL layer has to handle all of it.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from revintel.config import LANDING_DIR

log = logging.getLogger(__name__)

START = pd.Timestamp("2023-01-01")
END = pd.Timestamp("2026-08-31")

FX_RATE_TO_USD = {"USD": 1.0, "EUR": 1.09, "GBP": 1.27, "INR": 0.012, "CAD": 0.74, "AUD": 0.66}
COUNTRIES = {  # country -> (currency, weight)
    "US": ("USD", 0.38),
    "GB": ("GBP", 0.14),
    "DE": ("EUR", 0.12),
    "FR": ("EUR", 0.08),
    "IN": ("INR", 0.14),
    "CA": ("CAD", 0.08),
    "AU": ("AUD", 0.06),
}
SEGMENTS = {  # segment -> (share, monthly order rate, mean lifetime months, max qty)
    "Consumer": (0.70, 0.30, 12, 3),
    "SMB": (0.22, 0.70, 20, 8),
    "Enterprise": (0.08, 1.40, 30, 25),
}
CHANNELS = {"Organic": 0.30, "Paid Search": 0.25, "Social": 0.15, "Referral": 0.18, "Partner": 0.12}
CATALOG = {  # category -> (price range USD, product nouns)
    "Software": (
        (49, 499),
        [
            "Analytics Suite",
            "Security Pack",
            "Design Studio",
            "Dev Toolkit",
            "Backup Pro",
            "CRM Lite",
            "Invoice Manager",
            "Data Connector",
        ],
    ),
    "Hardware": (
        (99, 1499),
        [
            "Laptop Dock",
            "4K Monitor",
            "Mesh Router",
            "NAS Drive",
            "Webcam HD",
            "Mech Keyboard",
            "Thin Client",
            "POS Terminal",
        ],
    ),
    "Services": (
        (199, 2999),
        [
            "Onboarding",
            "Migration",
            "Premium Support",
            "Training Day",
            "Health Check",
            "Custom Integration",
            "Audit",
            "Advisory",
        ],
    ),
    "Subscriptions": (
        (9, 99),
        ["Cloud Storage", "Email Plus", "VPN", "Monitoring", "Password Vault", "E-Sign", "Chat Seats", "API Credits"],
    ),
    "Accessories": (
        (5, 79),
        ["USB-C Cable", "Mouse", "Headset", "Laptop Sleeve", "Stand", "Adapter", "Surge Protector", "Mouse Pad"],
    ),
}
FIRST_NAMES = [
    "James",
    "Olivia",
    "Liam",
    "Emma",
    "Noah",
    "Ava",
    "Arjun",
    "Priya",
    "Lukas",
    "Sofia",
    "Chloe",
    "Ethan",
    "Mia",
    "Rahul",
    "Ananya",
    "Jack",
    "Isla",
    "Leon",
    "Hannah",
    "Lucas",
    "Zoe",
    "Aditya",
    "Grace",
    "Oscar",
    "Amelia",
    "Mateo",
    "Ella",
    "Hugo",
    "Lea",
    "William",
]
LAST_NAMES = [
    "Smith",
    "Johnson",
    "Brown",
    "Patel",
    "Sharma",
    "Müller",
    "Schmidt",
    "Martin",
    "Bernard",
    "Wilson",
    "Taylor",
    "Singh",
    "Kumar",
    "Walker",
    "Clarke",
    "Dubois",
    "Fischer",
    "Nguyen",
    "Thompson",
    "Reddy",
    "Evans",
    "Wright",
    "Moreau",
    "Wagner",
    "Roberts",
    "Iyer",
    "Campbell",
    "Lee",
    "King",
    "Green",
]
DOMAINS = ["gmail.com", "outlook.com", "yahoo.com", "proton.me", "company.io", "corp.net"]


def _choice(rng: np.random.Generator, weights: dict, size: int) -> np.ndarray:
    keys = list(weights)
    probs = np.array([w if not isinstance(w, tuple) else w[-1] for w in weights.values()], dtype=float)
    return rng.choice(keys, size=size, p=probs / probs.sum())


def make_products(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    pid = 1
    for category, ((lo, hi), nouns) in CATALOG.items():
        for noun in nouns:
            rows.append(
                {
                    "product_id": f"P{pid:04d}",
                    "product_name": noun,
                    "category": category,
                    "list_price_usd": round(float(rng.uniform(lo, hi)), 2),
                }
            )
            pid += 1
    return pd.DataFrame(rows)


def make_customers(rng: np.random.Generator, n: int) -> pd.DataFrame:
    span_days = (END - pd.Timedelta(days=21) - START).days
    # power(1.5) skews signups toward recent dates -> a growing business
    signup = START + pd.to_timedelta((rng.power(1.5, n) * span_days).astype(int), unit="D")
    first = rng.choice(FIRST_NAMES, n)
    last = rng.choice(LAST_NAMES, n)
    ids = np.arange(100001, 100001 + n)
    emails = [
        f"{fn}.{ln}{i % 1000}@{d}".lower().replace("ü", "u")
        for fn, ln, i, d in zip(first, last, ids, rng.choice(DOMAINS, n), strict=True)
    ]
    df = pd.DataFrame(
        {
            "customer_id": [f"C{i}" for i in ids],
            "first_name": first,
            "last_name": last,
            "email": emails,
            "country": _choice(rng, {k: v[1] for k, v in COUNTRIES.items()}, n),
            "segment": _choice(rng, {k: v[0] for k, v in SEGMENTS.items()}, n),
            "acquisition_channel": _choice(rng, CHANNELS, n),
            "signup_date": signup,
        }
    )
    df["updated_at"] = (df["signup_date"] + pd.to_timedelta(rng.integers(0, 400, n), unit="D")).clip(upper=END)
    return df


def make_orders(rng: np.random.Generator, customers: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for seg, (_, rate, mean_life, _) in SEGMENTS.items():
        seg_cust = customers[customers["segment"] == seg]
        for row in seg_cust.itertuples(index=False):
            lifetime_days = int(rng.exponential(mean_life) * 30.4) + 1
            active_end = min(row.signup_date + pd.Timedelta(days=lifetime_days), END)
            active_days = max((active_end - row.signup_date).days, 1)
            n_orders = 1 + rng.poisson(rate * active_days / 30.4)
            first_order = row.signup_date + pd.Timedelta(days=int(rng.integers(0, 21)))
            offsets = np.sort(rng.integers(0, active_days, n_orders - 1)) if n_orders > 1 else np.array([], int)
            dates = [first_order] + [row.signup_date + pd.Timedelta(days=int(o)) for o in offsets]
            # Q4 seasonality: drop some non-Q4 orders
            keep = [d == first_order or d.month >= 11 or rng.random() < 0.8 for d in dates]
            dates = [d for d, k in zip(dates, keep, strict=True) if k and d <= END]
            seconds = rng.integers(8 * 3600, 23 * 3600, len(dates))
            frames.append(
                pd.DataFrame(
                    {
                        "customer_id": row.customer_id,
                        "order_ts": [d + pd.Timedelta(seconds=int(s)) for d, s in zip(dates, seconds, strict=True)],
                        "currency": COUNTRIES[row.country][0],
                        "segment": seg,
                    }
                )
            )
    orders = pd.concat(frames, ignore_index=True).sort_values("order_ts", ignore_index=True)
    n = len(orders)
    orders.insert(0, "order_id", [f"SO{1_000_000 + i}" for i in range(n)])
    orders["status"] = rng.choice(["completed", "refunded", "cancelled"], n, p=[0.9, 0.05, 0.05])
    orders["sales_channel"] = np.where(
        orders["segment"] == "Enterprise",
        rng.choice(["sales_rep", "web"], n, p=[0.7, 0.3]),
        rng.choice(["web", "mobile_app", "marketplace"], n, p=[0.55, 0.30, 0.15]),
    )
    orders["discount_pct"] = np.where(rng.random(n) < 0.3, rng.choice([0.05, 0.1, 0.15, 0.2], n), 0.0)
    orders["ingested_at"] = orders["order_ts"] + pd.to_timedelta(rng.integers(60, 86400, n), unit="s")
    return orders


def make_order_items(rng: np.random.Generator, orders: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    n_lines = rng.choice([1, 2, 3, 4], len(orders), p=[0.45, 0.30, 0.17, 0.08])
    idx = np.repeat(np.arange(len(orders)), n_lines)
    items = pd.DataFrame(
        {
            "order_id": orders["order_id"].to_numpy()[idx],
            "segment": orders["segment"].to_numpy()[idx],
            "currency": orders["currency"].to_numpy()[idx],
        }
    )
    items["line_number"] = items.groupby("order_id").cumcount() + 1
    prod_idx = rng.integers(0, len(products), len(items))
    items["product_id"] = products["product_id"].to_numpy()[prod_idx]
    max_qty = items["segment"].map({k: v[3] for k, v in SEGMENTS.items()}).to_numpy()
    items["quantity"] = rng.integers(1, max_qty + 1)
    price_usd = products["list_price_usd"].to_numpy()[prod_idx] * rng.uniform(0.95, 1.05, len(items))
    items["unit_price"] = (price_usd / items["currency"].map(FX_RATE_TO_USD).to_numpy()).round(2)
    return items[["order_id", "line_number", "product_id", "quantity", "unit_price"]]


def inject_quality_issues(
    rng: np.random.Generator, customers: pd.DataFrame, orders: pd.DataFrame, items: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    customers = customers.copy()
    n = len(customers)
    # Mixed date formats from a CRM migration
    alt = rng.random(n) < 0.25
    customers["signup_date"] = np.where(
        alt, customers["signup_date"].dt.strftime("%d %b %Y"), customers["signup_date"].dt.strftime("%Y-%m-%d")
    )
    customers["updated_at"] = customers["updated_at"].dt.strftime("%Y-%m-%d %H:%M:%S")
    # Casing / whitespace noise
    m = rng.random(n) < 0.08
    customers.loc[m, "email"] = customers.loc[m, "email"].str.upper()
    m = rng.random(n) < 0.05
    customers.loc[m, "first_name"] = "  " + customers.loc[m, "first_name"].str.lower() + " "
    m = rng.random(n) < 0.04
    customers.loc[m, "segment"] = customers.loc[m, "segment"].str.upper()
    customers.loc[customers["country"].eq("GB") & (rng.random(n) < 0.3), "country"] = "uk"
    customers.loc[rng.random(n) < 0.01, "country"] = None
    customers.loc[rng.random(n) < 0.004, "email"] = "not-an-email"
    # Duplicate customer records (stale copies with an older updated_at)
    dupes = customers.sample(frac=0.02, random_state=1).copy()
    dupes["updated_at"] = "2022-12-31 00:00:00"
    dupes["first_name"] = dupes["first_name"].str.upper()
    customers = pd.concat([customers, dupes], ignore_index=True).sample(frac=1, random_state=2)

    orders = orders.drop(columns="segment").copy()
    n_orders = len(orders)
    iso = orders["order_ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    orders["order_ts"] = np.where(rng.random(n_orders) < 0.2, orders["order_ts"].dt.strftime("%Y-%m-%d %H:%M:%S"), iso)
    orders["ingested_at"] = orders["ingested_at"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    mask = rng.random(n_orders) < 0.05
    orders.loc[mask, "currency"] = orders.loc[mask, "currency"].str.lower()
    mask = rng.random(n_orders) < 0.03
    orders.loc[mask, "status"] = orders.loc[mask, "status"].str.upper()
    orders.loc[rng.random(n_orders) < 0.003, "order_ts"] = None
    orphan = rng.random(n_orders) < 0.004
    orders.loc[orphan, "customer_id"] = [f"C9{i:05d}" for i in range(int(orphan.sum()))]
    # Re-delivered records from the ERP change-data-capture feed
    redelivered = orders.sample(frac=0.01, random_state=3).copy()
    redelivered["ingested_at"] = "2026-09-01T00:00:00Z"
    orders = pd.concat([orders, redelivered], ignore_index=True)

    items = items.copy()
    k = len(items)
    items.loc[rng.random(k) < 0.002, "quantity"] = 0
    items.loc[rng.random(k) < 0.001, "quantity"] = -1
    items["unit_price"] = items["unit_price"].astype(object)
    items.loc[rng.random(k) < 0.002, "unit_price"] = None
    items = pd.concat([items, items.sample(frac=0.005, random_state=4)], ignore_index=True)
    return customers, orders, items


def generate(out_dir: Path = LANDING_DIR, n_customers: int = 5000, seed: int = 42) -> dict[str, int]:
    rng = np.random.default_rng(seed)
    products = make_products(rng)
    customers = make_customers(rng, n_customers)
    orders = make_orders(rng, customers)
    items = make_order_items(rng, orders, products)
    customers, orders, items = inject_quality_issues(rng, customers, orders, items)
    fx = pd.DataFrame({"currency": list(FX_RATE_TO_USD), "rate_to_usd": list(FX_RATE_TO_USD.values())})

    for sub in ("crm", "erp", "catalog", "finance"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)
    customers.to_csv(out_dir / "crm" / "customers.csv", index=False)
    orders.to_json(out_dir / "erp" / "orders.jsonl", orient="records", lines=True)
    items.to_csv(out_dir / "erp" / "order_items.csv", index=False)
    products.to_csv(out_dir / "catalog" / "products.csv", index=False)
    fx.to_csv(out_dir / "finance" / "fx_rates.csv", index=False)

    counts = {
        "customers": len(customers),
        "orders": len(orders),
        "order_items": len(items),
        "products": len(products),
        "fx_rates": len(fx),
    }
    log.info("Generated raw extracts in %s: %s", out_dir, counts)
    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--customers", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=LANDING_DIR)
    args = parser.parse_args()
    generate(args.out, args.customers, args.seed)
