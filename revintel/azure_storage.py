"""Upload a batch's lake files to Azure Data Lake Storage Gen2.

The container mirrors the local ``data/lake`` layout:
    clean/<table>/batch_id=<id>/<table>.parquet   <- Snowflake external stage reads these
    rejects/batch_id=<id>/<table>_rejects.csv     <- quarantined records for data stewards
    dq/batch_id=<id>/report.json                  <- data-quality report

Batches are immutable, so the lake doubles as the audit trail and replay source.
Auth uses managed identity (DefaultAzureCredential) when an account URL is set.
"""

from __future__ import annotations

import logging
from pathlib import Path

from tenacity import retry, stop_after_attempt, wait_exponential

from revintel.config import Settings

log = logging.getLogger(__name__)


def _container_client(settings: Settings):
    from azure.storage.blob import BlobServiceClient

    if settings.azure_storage_account_url:
        from azure.identity import DefaultAzureCredential

        service = BlobServiceClient(settings.azure_storage_account_url, credential=DefaultAzureCredential())
    elif settings.azure_storage_connection_string:
        service = BlobServiceClient.from_connection_string(settings.azure_storage_connection_string.get_secret_value())
    else:
        raise RuntimeError("Set AZURE_STORAGE_ACCOUNT_URL (managed identity) or AZURE_STORAGE_CONNECTION_STRING")
    container = service.get_container_client(settings.azure_storage_container)
    if not container.exists():
        container.create_container()
    return container


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, max=20), reraise=True)
def _upload(container, path: Path, blob_name: str) -> None:
    with path.open("rb") as fh:
        container.upload_blob(blob_name, fh, overwrite=True)


def upload_batch(lake_dir: Path, batch_id: str, settings: Settings) -> list[str]:
    container = _container_client(settings)
    files = sorted(p for p in lake_dir.rglob("*") if p.is_file() and f"batch_id={batch_id}" in p.as_posix())
    blobs = []
    for path in files:
        blob_name = path.relative_to(lake_dir).as_posix()
        _upload(container, path, blob_name)
        blobs.append(blob_name)
    log.info("Uploaded %d files for batch %s to container '%s'", len(blobs), batch_id, settings.azure_storage_container)
    return blobs
