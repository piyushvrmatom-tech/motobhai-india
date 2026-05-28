"""Firestore wrapper — initialised once at module import, all reads/writes go through here.

Uses the **firebase-admin** SDK (not google-cloud-firestore directly).
firebase-admin is the recommended server-side SDK — it bypasses Firestore
security rules and uses a more reliable connection mechanism.

Credentials are loaded from `FIRESTORE_CREDENTIALS_B64` (base64-encoded
service-account JSON). If the env var is missing or invalid, `db` will be
None and callers must degrade gracefully (return 503, log a Sentry event).

Collections (CTO spec §4.5):
    trips          : doc_id = trip_id (mb_<6char>)
    users          : doc_id = phone_hash
    otp_codes      : doc_id = phone_hash
    share_views    : doc_id = trip_id
    location_intel : doc_id = slugified location name (legacy v0.9)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import string
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger(__name__)

_db = None
FIRESTORE_AVAILABLE = False

try:
    import firebase_admin  # type: ignore
    from firebase_admin import credentials as fb_credentials  # type: ignore
    from firebase_admin import firestore as fb_firestore  # type: ignore

    FIRESTORE_AVAILABLE = True
except ImportError:  # pragma: no cover
    log.warning("firebase-admin not installed; Firestore disabled")


def _init_client():
    """Initialise firebase-admin and return a Firestore client."""
    if not FIRESTORE_AVAILABLE:
        log.warning("firebase-admin not installed; Firestore disabled")
        return None

    b64 = os.getenv("FIRESTORE_CREDENTIALS_B64", "").strip()
    if b64:
        try:
            info = json.loads(base64.b64decode(b64).decode("utf-8"))
            cred = fb_credentials.Certificate(info)
            project_id = info.get("project_id") or os.getenv("GCP_PROJECT", "motobhai-india")
            # Initialize only once — firebase_admin raises if called twice
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred, {"projectId": project_id})
            return fb_firestore.client()
        except Exception as exc:
            log.exception("Failed to init Firestore via firebase-admin: %s", exc)
            return None

    # Fallback to ADC (works locally via `gcloud auth application-default login`).
    try:
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        return fb_firestore.client()
    except Exception as exc:
        log.warning("Firestore ADC init failed: %s", exc)
        return None


def get_db():
    global _db
    if _db is None:
        _db = _init_client()
    return _db


def is_enabled() -> bool:
    return get_db() is not None


# ─── Trip persistence (CTO §4.5) ─────────────────────────────────────────────

_TRIP_ID_ALPHABET = string.ascii_lowercase + string.digits


def new_trip_id() -> str:
    """Return a new short trip id like `mb_a3f9k2` (6 chars, base36)."""
    return "mb_" + "".join(secrets.choice(_TRIP_ID_ALPHABET) for _ in range(6))


def save_trip(trip_id: str, payload: dict[str, Any], *, ttl_days: int = 30) -> bool:
    """Write a full trip document to `trips/<trip_id>`.

    For anonymous riders we set a TTL field; a scheduled Firestore TTL policy
    can reap stale documents (configure once in console: ttl on field `expires_at`).
    """
    db = get_db()
    if db is None:
        return False
    doc = dict(payload)
    doc["trip_id"] = trip_id
    doc["created_at"] = datetime.now(tz=timezone.utc)
    if ttl_days:
        from datetime import timedelta

        doc["expires_at"] = doc["created_at"] + timedelta(days=ttl_days)
    db.collection("trips").document(trip_id).set(doc)
    return True


def load_trip(trip_id: str) -> Optional[dict[str, Any]]:
    db = get_db()
    if db is None:
        return None
    try:
        snap = db.collection("trips").document(trip_id).get()
        return snap.to_dict() if snap.exists else None
    except Exception:
        log.exception("load_trip failed for %s", trip_id)
        return None


def increment_share_view(trip_id: str) -> None:
    """Best-effort view counter. Never raises — view counts must not block reads."""
    db = get_db()
    if db is None:
        return
    try:
        from google.cloud.firestore_v1 import Increment  # type: ignore

        ref = db.collection("share_views").document(trip_id)
        ref.set(
            {
                "view_count": Increment(1),
                "last_viewed_at": datetime.now(tz=timezone.utc),
            },
            merge=True,
        )
    except Exception:
        log.exception("share_views increment failed for %s", trip_id)
