"""Upload the clean Parquet layer to Azure Blob Storage / ADLS Gen2.

Layout inside the container:
    clean/<table>/<table>.parquet                    <- current snapshot (Snowflake stage reads this)
    archive/load_date=YYYY-MM-DD/<table>.parquet     <- immutable history for audit/replay
    rejects/load_date=YYYY-MM-DD/<table>_rejects.csv <- quarantined records
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from revintel.config import TABLES, AzureSettings

log = logging.getLogger(__name__)


def upload_layers(clean_dir: Path, rejects_dir: Path, settings: AzureSettings, load_date: date | None = None) -> list[str]:
    from azure.storage.blob import BlobServiceClient

    load_date = load_date or date.today()
    service = BlobServiceClient.from_connection_string(settings.connection_string)
    container = service.get_container_client(settings.container)
    if not container.exists():
        container.create_container()

    uploads: list[tuple[Path, str]] = []
    for table in TABLES:
        path = clean_dir / f"{table}.parquet"
        uploads.append((path, f"clean/{table}/{table}.parquet"))
        uploads.append((path, f"archive/load_date={load_date:%Y-%m-%d}/{table}.parquet"))
    for path in sorted(rejects_dir.glob("*.csv")):
        uploads.append((path, f"rejects/load_date={load_date:%Y-%m-%d}/{path.name}"))

    blobs = []
    for path, blob_name in uploads:
        with path.open("rb") as fh:
            container.upload_blob(blob_name, fh, overwrite=True)
        blobs.append(blob_name)
    log.info("Uploaded %d blobs to container '%s'", len(blobs), settings.container)
    return blobs
