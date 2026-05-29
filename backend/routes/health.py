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
            "msg91_key": bool(os.getenv("MSG91_AUTH_KEY")),
            "otp_secret": bool(os.getenv("OTP_SECRET")),
            "jwt_secret": bool(os.getenv("JWT_SECRET")),
            "sheets_webhook": bool(os.getenv("SHEETS_WEBHOOK_URL")),
            "firestore_creds": bool(os.getenv("FIRESTORE_CREDENTIALS_B64")),
            "sentry_dsn": bool(os.getenv("SENTRY_DSN")),
        },
        "firestore": firestore_client.is_enabled(),
    }
    if not all(payload["config"].values()):
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
    """Debug endpoint: write + read + delete a test doc in Firestore."""
    import traceback
    from datetime import datetime, timezone

    db = firestore_client.get_db()
    if db is None:
        return {"ok": False, "error": "get_db() returned None", "sdk": "unknown"}

    sdk = "firebase-admin" if firestore_client._USE_ADMIN_SDK else "google-cloud-firestore"
    doc_id = "_healthz_test"
    try:
        # Write
        db.collection("trips").document(doc_id).set({
            "test": True,
            "ts": datetime.now(tz=timezone.utc).isoformat(),
        })
        # Read back
        snap = db.collection("trips").document(doc_id).get()
        data = snap.to_dict() if snap.exists else None
        # Cleanup
        db.collection("trips").document(doc_id).delete()
        return {"ok": True, "sdk": sdk, "wrote": True, "read_back": data}
    except Exception as exc:
        return {
            "ok": False,
            "sdk": sdk,
            "error": str(exc),
            "type": type(exc).__name__,
            "traceback": traceback.format_exc()[-500:],
        }

