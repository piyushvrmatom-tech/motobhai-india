"""Firestore wrapper — initialised once at module import.

Supports BOTH firebase-admin (preferred) and google-cloud-firestore (fallback).
firebase-admin is more reliable for server-side access. Falls back to
google-cloud-firestore if firebase-admin is not installed.

Credentials are loaded from `FIRESTORE_CREDENTIALS_B64` (base64-encoded
service-account JSON).

Collections (CTO spec §4.5):
    trips          : doc_id = trip_id (mb_<6char>)
    users          : doc_id = phone_hash
    otp_codes      : doc_id = phone_hash
    share_views    : doc_id = trip_id
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
_USE_ADMIN_SDK = False

# ── SDK detection ─────────────────────────────────────────────────────────────
try:
    import firebase_admin  # type: ignore
    from firebase_admin import credentials as fb_credentials  # type: ignore
    from firebase_admin import firestore as fb_firestore  # type: ignore
    _USE_ADMIN_SDK = True
    log.info("Firestore: using firebase-admin SDK")
except ImportError:
    _USE_ADMIN_SDK = False
    log.info("firebase-admin not found, trying google-cloud-firestore")

if not _USE_ADMIN_SDK:
    try:
        from google.cloud import firestore  # type: ignore
        from google.oauth2 import service_account  # type: ignore
        log.info("Firestore: using google-cloud-firestore SDK")
    except ImportError:
        firestore = None  # type: ignore
        log.warning("No Firestore SDK available")


def _init_client():
    """Initialise Firestore client using whichever SDK is available."""
    b64 = os.getenv("FIRESTORE_CREDENTIALS_B64", "").strip()

    if _USE_ADMIN_SDK:
        if b64:
            try:
                info = json.loads(base64.b64decode(b64).decode("utf-8"))
                cred = fb_credentials.Certificate(info)
                project_id = info.get("project_id") or os.getenv("GCP_PROJECT", "motobhai-india")
                if not firebase_admin._apps:
                    firebase_admin.initialize_app(cred, {"projectId": project_id})
                return fb_firestore.client()
            except Exception as exc:
                log.exception("Failed to init Firestore via firebase-admin: %s", exc)
                return None
        try:
            if not firebase_admin._apps:
                firebase_admin.initialize_app()
            return fb_firestore.client()
        except Exception as exc:
            log.warning("Firestore ADC init (firebase-admin) failed: %s", exc)
            return None

    # Fallback: google-cloud-firestore
    if firestore is None:
        log.warning("No Firestore SDK available")
        return None

    if b64:
        try:
            info = json.loads(base64.b64decode(b64).decode("utf-8"))
            creds = service_account.Credentials.from_service_account_info(info)
            project_id = info.get("project_id") or os.getenv("GCP_PROJECT", "motobhai-india")
            return firestore.Client(project=project_id, credentials=creds)
        except Exception as exc:
            log.exception("Failed to init Firestore from FIRESTORE_CREDENTIALS_B64: %s", exc)
            return None

    try:
        return firestore.Client(project=os.getenv("GCP_PROJECT", "motobhai-india"))
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
    """Write a full trip document to `trips/<trip_id>`."""
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
    log.info("Saved trip %s to Firestore", trip_id)
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
    """Best-effort view counter."""
    db = get_db()
    if db is None:
        return
    try:
        from google.cloud.firestore_v1 import Increment
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
