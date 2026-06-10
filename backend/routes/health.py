"""GET /healthz — Render auto-deploys hit this every 60s."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Response

from backend.services import firestore_client, gemini, routes_api

router = APIRouter()

VERSION = "1.1.0"


@router.get("/healthz")
def healthz(response: Response, deep: bool = False) -> dict[str, Any]:
    """Shallow check by default (config presence only). Pass `?deep=1` for live probes.

    Render's auto-health-check should use the shallow path so we don't burn
    Gemini quota on every 60s ping. The deep variant is for our own ops.
    """
    payload: dict[str, Any] = {
        "ok": True,
        "version": VERSION,
        "env": os.getenv("ENV", "production"),
        "config": {
            "gemini_key": bool(os.getenv("GEMINI_API_KEY")),
            "routes_key": bool(os.getenv("GOOGLE_ROUTES_API_KEY")),
            "sheets_webhook": bool(os.getenv("SHEETS_WEBHOOK_URL")),
            "firestore_creds": bool(os.getenv("FIRESTORE_CREDENTIALS_B64")),
            "sentry_dsn": bool(os.getenv("SENTRY_DSN")),
        },
        "firestore": firestore_client.is_enabled(),
    }
    required_keys = {k: v for k, v in payload["config"].items() if k != "sentry_dsn"}
    if not all(required_keys.values()):
        payload["ok"] = False
        response.status_code = 503

    if deep:
        payload["gemini"] = "up" if gemini.ping() else "down"
        payload["routes"] = "up" if routes_api.ping() else "down"
        if payload["gemini"] == "down" or payload["routes"] == "down":
            payload["ok"] = False
            response.status_code = 503
    return payload


@router.get("/healthz/firestore-test")
def firestore_test() -> dict[str, Any]:
    """Debug endpoint: write + read + delete a test doc via REST API."""
    import traceback
    from datetime import datetime, timezone

    if not firestore_client.is_enabled():
        return {"ok": False, "error": "Firestore not enabled (is_enabled=False)"}

    sdk = "REST" if firestore_client._REST_READY else ("firebase-admin" if firestore_client._USE_ADMIN_SDK else "none")
    doc_id = "_healthz_test"
    try:
        # Write
        wrote = firestore_client.set_doc("trips", doc_id, {
            "test": True,
            "ts": datetime.now(tz=timezone.utc).isoformat(),
        })
        # Read back
        data = firestore_client.get_doc("trips", doc_id)
        # Cleanup
        firestore_client.delete_doc("trips", doc_id)
        return {"ok": wrote, "sdk": sdk, "wrote": wrote, "read_back": data}
    except Exception as exc:
        return {
            "ok": False,
            "sdk": sdk,
            "error": str(exc),
            "type": type(exc).__name__,
            "traceback": traceback.format_exc()[-500:],
        }

