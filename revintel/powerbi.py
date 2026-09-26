"""Trigger and monitor a Power BI dataset refresh with a service principal."""

from __future__ import annotations

import logging
import time

import requests

from revintel.config import Settings

log = logging.getLogger(__name__)

API = "https://api.powerbi.com/v1.0/myorg"


def _token(settings: Settings) -> str:
    assert settings.powerbi_client_secret is not None
    resp = requests.post(
        f"https://login.microsoftonline.com/{settings.powerbi_tenant_id}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": settings.powerbi_client_id,
            "client_secret": settings.powerbi_client_secret.get_secret_value(),
            "scope": "https://analysis.windows.net/powerbi/api/.default",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def refresh_dataset(settings: Settings, timeout_s: int = 1800, poll_s: int = 30) -> str:
    settings.require(
        "powerbi_tenant_id", "powerbi_client_id", "powerbi_client_secret", "powerbi_workspace_id", "powerbi_dataset_id"
    )
    headers = {"Authorization": f"Bearer {_token(settings)}"}
    url = f"{API}/groups/{settings.powerbi_workspace_id}/datasets/{settings.powerbi_dataset_id}/refreshes"

    requests.post(url, headers=headers, json={"notifyOption": "NoNotification"}, timeout=30).raise_for_status()
    log.info("Power BI refresh requested for dataset %s", settings.powerbi_dataset_id)

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(poll_s)
        latest = requests.get(url, headers=headers, params={"$top": 1}, timeout=30).json()["value"][0]
        status = latest.get("status")
        if status == "Completed":
            log.info("Power BI refresh completed")
            return status
        if status == "Failed":
            raise RuntimeError(f"Power BI refresh failed: {latest.get('serviceExceptionJson')}")
    raise TimeoutError("Power BI refresh did not finish in time")
