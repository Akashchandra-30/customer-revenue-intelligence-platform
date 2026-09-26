"""Command-line interface.

revintel run       --target local --generate        # everything, end to end
revintel ingest    --target prod --upload-azure --load-mode stage
revintel transform --target prod [--full-refresh] [--select marts.analytics]
revintel publish   --target prod
revintel generate  --customers 5000
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from revintel.config import get_settings
from revintel.generate_data import generate
from revintel.observability import run_id_var, send_alert, setup_logging
from revintel.pipeline import ingest, new_run_id, publish, transform

log = logging.getLogger("revintel")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="revintel", description="Customer & Revenue Intelligence Platform")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--target",
            choices=["local", "dev", "prod"],
            default="local",
            help="local = DuckDB; dev/prod = Snowflake (matching dbt targets)",
        )
        p.add_argument("--run-id", help="correlation id (Airflow passes its run_id); generated if omitted")

    def add_ingest(p: argparse.ArgumentParser) -> None:
        p.add_argument("--generate", action="store_true", help="(re)generate synthetic source extracts")
        p.add_argument("--customers", type=int, default=5000)
        p.add_argument("--seed", type=int, default=42)
        p.add_argument("--upload-azure", action="store_true", help="upload the batch to Azure Data Lake")
        p.add_argument(
            "--load-mode",
            choices=["direct", "stage"],
            default="direct",
            help="direct = write_pandas/DuckDB insert; stage = COPY INTO from the Azure stage",
        )

    def add_transform(p: argparse.ArgumentParser) -> None:
        p.add_argument("--full-refresh", action="store_true", help="rebuild incremental models from scratch")
        p.add_argument("--select", help="dbt selector, e.g. 'marts.analytics' or '+customer_ltv'")

    p_gen = sub.add_parser("generate", help="generate synthetic source extracts")
    p_gen.add_argument("--customers", type=int, default=5000)
    p_gen.add_argument("--seed", type=int, default=42)

    p_ing = sub.add_parser("ingest", help="extract, clean, validate and load a batch into RAW")
    add_common(p_ing)
    add_ingest(p_ing)

    p_tr = sub.add_parser("transform", help="dbt build: staging, snapshots, marts and tests")
    add_common(p_tr)
    add_transform(p_tr)

    p_pub = sub.add_parser("publish", help="refresh Power BI (cloud) or export CSVs (local)")
    add_common(p_pub)

    p_run = sub.add_parser("run", help="ingest + transform + publish")
    add_common(p_run)
    add_ingest(p_run)
    add_transform(p_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    setup_logging(settings.log_format, settings.log_level)

    if args.command == "generate":
        print(json.dumps(generate(n_customers=args.customers, seed=args.seed)))
        return 0

    run_id_var.set(args.run_id or new_run_id())
    summary: dict[str, object] = {"run_id": run_id_var.get()}
    try:
        if args.command in ("ingest", "run"):
            summary["ingest"] = ingest(
                args.target,
                settings,
                generate_data=args.generate,
                n_customers=args.customers,
                seed=args.seed,
                upload_azure=args.upload_azure,
                load_mode=args.load_mode,
            )
        if args.command in ("transform", "run"):
            summary["transform"] = transform(args.target, settings, full_refresh=args.full_refresh, select=args.select)
        if args.command in ("publish", "run"):
            summary["publish"] = publish(args.target, settings)
    except Exception as exc:
        log.exception("Pipeline failed")
        send_alert(
            settings.alert_webhook_url.get_secret_value() if settings.alert_webhook_url else None,
            f"revintel {args.command} failed ({args.target})",
            f"{type(exc).__name__}: {exc}",
        )
        return 1
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
