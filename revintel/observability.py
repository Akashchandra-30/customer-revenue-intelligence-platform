"""Logging (text or JSON), run context and failure alerting."""

from __future__ import annotations

import json
import logging
import sys
import urllib.request
from contextvars import ContextVar
from datetime import UTC, datetime

run_id_var: ContextVar[str] = ContextVar("run_id", default="-")
stage_var: ContextVar[str] = ContextVar("stage", default="-")

log = logging.getLogger(__name__)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = run_id_var.get()
        record.stage = stage_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "run_id": getattr(record, "run_id", "-"),
            "stage": getattr(record, "stage", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def setup_logging(fmt: str = "text", level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_ContextFilter())
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s [%(run_id)s %(stage)s] %(name)s: %(message)s")
        )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("snowflake.connector", "azure.core", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def send_alert(webhook_url: str | None, title: str, detail: str) -> None:
    """Post a failure message to a Slack/Teams incoming webhook. Never raises."""
    if not webhook_url:
        return
    body = json.dumps({"text": f"*{title}*\nrun_id={run_id_var.get()} stage={stage_var.get()}\n{detail[:3000]}"})
    req = urllib.request.Request(webhook_url, data=body.encode(), headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10).close()
    except Exception as exc:  # alerting must not mask the original failure
        log.warning("Failed to send alert: %s", exc)
