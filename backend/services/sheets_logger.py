"""Fire-and-forget logger to the Apps Script webhook.

The webhook URL itself acts as the bearer token (kept in env, never in code).
We never block on this — failures are swallowed so analytics outages can't
take down /api/plan.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.request
from typing import Any

log = logging.getLogger(__name__)


def _post(url: str, body: dict[str, Any]) -> None:
    try:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=4).read()  # noqa: S310
    except Exception as exc:  # pragma: no cover - swallowed by design
        log.warning("Sheets log forward failed: %s", exc)


async def log_event(event_name: str, **fields: Any) -> None:
    url = os.getenv("SHEETS_WEBHOOK_URL", "").strip()
    if not url:
        return
    payload = {"event": event_name, **fields}
    # Run blocking urllib on a thread so we don't stall the event loop.
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _post, url, payload)


def log_event_sync(event_name: str, **fields: Any) -> None:
    """Sync variant for non-async call sites."""
    url = os.getenv("SHEETS_WEBHOOK_URL", "").strip()
    if not url:
        return
    _post(url, {"event": event_name, **fields})
