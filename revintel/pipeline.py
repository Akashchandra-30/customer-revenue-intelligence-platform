"""End-to-end pipeline: extract -> clean -> validate -> stage (Azure) -> load/model (Snowflake or DuckDB).

Examples:
    python -m revintel.pipeline --target local --generate
    python -m revintel.pipeline --target snowflake --upload-azure --via-azure-stage
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import pandas as pd

from revintel import config
from revintel.extract import extract_all
from revintel.generate_data import generate
from revintel.transform import transform_all
from revintel.validate import assert_passed, reconciliation, run_checks

log = logging.getLogger("revintel")


def write_layers(results, clean_dir: Path, rejects_dir: Path) -> None:
    clean_dir.mkdir(parents=True, exist_ok=True)
    rejects_dir.mkdir(parents=True, exist_ok=True)
    for old in rejects_dir.glob("*.csv"):
        old.unlink()
    for name, res in results.items():
        res.data.to_parquet(clean_dir / f"{name}.parquet", index=False)
        if len(res.rejects):
            res.rejects.to_csv(rejects_dir / f"{name}_rejects.csv", index=False)


def run(target: str = "local", generate_data: bool = False, n_customers: int = 5000, seed: int = 42,
        upload_azure: bool = False, via_azure_stage: bool = False,
        raw_dir: Path = config.RAW_DIR, clean_dir: Path = config.CLEAN_DIR,
        rejects_dir: Path = config.REJECTS_DIR, output_dir: Path = config.OUTPUT_DIR) -> dict:
    started = time.perf_counter()

    if generate_data or not (raw_dir / "crm" / "customers.csv").exists():
        generate(raw_dir, n_customers, seed)

    log.info("Extracting source files from %s", raw_dir)
    raw = extract_all(raw_dir)

    log.info("Cleaning and conforming")
    results = transform_all(raw)
    clean = {name: res.data for name, res in results.items()}

    checks = run_checks(clean) + reconciliation(raw, results)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "checks": [c.to_dict() for c in checks],
        "rejects_by_reason": {
            name: res.rejects["reject_reason"].value_counts().to_dict() for name, res in results.items()
            if len(res.rejects)
        },
        "duplicates_removed": {name: res.duplicates_removed for name, res in results.items()},
    }
    (output_dir / "data_quality_report.json").write_text(json.dumps(report, indent=2, default=str))
    passed = sum(c.passed for c in checks)
    log.info("Data quality: %d/%d checks passed", passed, len(checks))
    for c in checks:
        if not c.passed:
            log.warning("  [%s] %s %s: %s", c.severity, c.table, c.name, c.detail)
    assert_passed(checks)

    write_layers(results, clean_dir, rejects_dir)

    if upload_azure:
        from revintel.azure_storage import upload_layers
        upload_layers(clean_dir, rejects_dir, config.AzureSettings.from_env())

    if target == "snowflake":
        from revintel.snowflake_loader import load_to_snowflake
        summary = {"row_counts": load_to_snowflake(clean, config.SnowflakeSettings.from_env(), config.SQL_DIR,
                                                   via_azure_stage=via_azure_stage)}
    else:
        from revintel.local_warehouse import build_local_warehouse
        summary = build_local_warehouse(clean_dir, config.SQL_DIR, output_dir / "revintel.duckdb",
                                        export_dir=output_dir / "powerbi")

    summary["elapsed_seconds"] = round(time.perf_counter() - started, 1)
    summary["clean_rows"] = {name: len(df) for name, df in clean.items()}
    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", choices=["local", "snowflake"], default="local",
                        help="local = DuckDB running the Snowflake SQL; snowflake = real warehouse")
    parser.add_argument("--generate", action="store_true", help="(re)generate synthetic source extracts")
    parser.add_argument("--customers", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--upload-azure", action="store_true", help="upload clean/reject layers to Azure Blob")
    parser.add_argument("--via-azure-stage", action="store_true",
                        help="load Snowflake with COPY INTO from the Azure external stage")
    args = parser.parse_args()
    if args.via_azure_stage and not args.upload_azure:
        parser.error("--via-azure-stage requires --upload-azure")

    summary = run(args.target, args.generate, args.customers, args.seed, args.upload_azure, args.via_azure_stage)
    pd.set_option("display.width", 120)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
