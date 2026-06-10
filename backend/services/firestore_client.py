"""Firestore wrapper — uses REST API to bypass gRPC 'database not found' bug.

The google-cloud-firestore gRPC endpoint returns 'The database (default)
does not exist' for project motobhai-india, even though the database is
confirmed to exist via gcloud CLI and the REST API. This is a known
propagation issue with newly created Firestore databases.

Solution: Use the Firestore REST API directly via `requests` + service
account credentials. Proven to work via manual testing.

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
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests as http_requests

log = logging.getLogger(__name__)

# ── Credentials ───────────────────────────────────────────────────────────────
_creds = None
_project_id: str = ""
_BASE_URL = ""

_USE_ADMIN_SDK = False
_admin_db = None


def _init_rest():
    """Load service account credentials for REST API access."""
    global _creds, _project_id, _BASE_URL

    b64 = os.getenv("FIRESTORE_CREDENTIALS_B64", "").strip()
    if not b64:
        log.warning("FIRESTORE_CREDENTIALS_B64 not set; Firestore disabled")
        return False

    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests

        info = json.loads(base64.b64decode(b64).decode("utf-8"))
        _project_id = info.get("project_id") or os.getenv("GCP_PROJECT", "motobhai-app")
        scopes = ["https://www.googleapis.com/auth/datastore"]
        _creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        _BASE_URL = f"https://firestore.googleapis.com/v1/projects/{_project_id}/databases/default/documents"
        log.info("Firestore REST client ready for project=%s", _project_id)
        return True
    except Exception as exc:
        log.exception("Failed to init Firestore REST credentials: %s", exc)
        return False


def _init_admin():
    """Try firebase-admin SDK as alternative."""
    global _admin_db, _USE_ADMIN_SDK
    try:
        import firebase_admin
        from firebase_admin import credentials as fb_credentials, firestore as fb_firestore

        b64 = os.getenv("FIRESTORE_CREDENTIALS_B64", "").strip()
        if not b64:
            return False
        info = json.loads(base64.b64decode(b64).decode("utf-8"))
        cred = fb_credentials.Certificate(info)
        project_id = info.get("project_id", "motobhai-india")
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {"projectId": project_id})
        _admin_db = fb_firestore.client()
        _USE_ADMIN_SDK = True
        return True
    except Exception as exc:
        log.warning("firebase-admin init failed: %s", exc)
        return False


def _get_headers() -> dict:
    """Get auth headers, refreshing token if needed."""
    import google.auth.transport.requests
    if _creds is None:
        return {}
    if not _creds.valid:
        _creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {_creds.token}",
        "Content-Type": "application/json",
    }


# ── REST helpers ──────────────────────────────────────────────────────────────

def _python_to_firestore_value(val: Any) -> dict:
    """Convert a Python value to Firestore REST API value format."""
    if val is None:
        return {"nullValue": None}
    if isinstance(val, bool):
        return {"booleanValue": val}
    if isinstance(val, int):
        return {"integerValue": str(val)}
    if isinstance(val, float):
        return {"doubleValue": val}
    if isinstance(val, str):
        return {"stringValue": val}
    if isinstance(val, datetime):
        return {"stringValue": val.isoformat()}
    if isinstance(val, list):
        return {"arrayValue": {"values": [_python_to_firestore_value(v) for v in val]}}
    if isinstance(val, dict):
        return {"mapValue": {"fields": {k: _python_to_firestore_value(v) for k, v in val.items()}}}
    # Fallback: stringify
    return {"stringValue": str(val)}


def _firestore_value_to_python(val: dict) -> Any:
    """Convert a Firestore REST API value to Python."""
    if "nullValue" in val:
        return None
    if "booleanValue" in val:
        return val["booleanValue"]
    if "integerValue" in val:
        return int(val["integerValue"])
    if "doubleValue" in val:
        return val["doubleValue"]
    if "stringValue" in val:
        return val["stringValue"]
    if "timestampValue" in val:
        return val["timestampValue"]
    if "arrayValue" in val:
        return [_firestore_value_to_python(v) for v in val.get("arrayValue", {}).get("values", [])]
    if "mapValue" in val:
        fields = val.get("mapValue", {}).get("fields", {})
        return {k: _firestore_value_to_python(v) for k, v in fields.items()}
    return None


def _doc_to_dict(doc: dict) -> dict:
    """Convert a Firestore REST document to a Python dict."""
    fields = doc.get("fields", {})
    return {k: _firestore_value_to_python(v) for k, v in fields.items()}


# ── Public API ────────────────────────────────────────────────────────────────

_REST_READY = False


def _ensure_init():
    global _REST_READY
    if _REST_READY:
        return True
    _REST_READY = _init_rest()
    if not _REST_READY:
        # Try admin SDK as fallback
        _init_admin()
    return _REST_READY or _USE_ADMIN_SDK


def get_db():
    """For compatibility with code that calls get_db(). Returns admin SDK client or a marker."""
    _ensure_init()
    if _USE_ADMIN_SDK and _admin_db:
        return _admin_db
    if _REST_READY:
        return True  # Non-None marker: REST is ready
    return None


def is_enabled() -> bool:
    return get_db() is not None


# ─── Trip persistence ─────────────────────────────────────────────────────────

_TRIP_ID_ALPHABET = string.ascii_lowercase + string.digits


def new_trip_id() -> str:
    return "mb_" + "".join(secrets.choice(_TRIP_ID_ALPHABET) for _ in range(6))


def save_trip(trip_id: str, payload: dict[str, Any], *, ttl_days: int = 30) -> bool:
    """Write a full trip document to `trips/<trip_id>`."""
    _ensure_init()

    doc = dict(payload)
    doc["trip_id"] = trip_id
    doc["created_at"] = datetime.now(tz=timezone.utc).isoformat()
    if ttl_days:
        doc["expires_at"] = (datetime.now(tz=timezone.utc) + timedelta(days=ttl_days)).isoformat()

    if _REST_READY:
        return _save_trip_rest(trip_id, doc)
    if _USE_ADMIN_SDK and _admin_db:
        return _save_trip_admin(trip_id, doc)
    return False


def _save_trip_rest(trip_id: str, doc: dict) -> bool:
    """Save via Firestore REST API."""
    url = f"{_BASE_URL}/trips?documentId={trip_id}"
    fields = {k: _python_to_firestore_value(v) for k, v in doc.items()}
    body = {"fields": fields}

    try:
        resp = http_requests.patch(
            f"{_BASE_URL}/trips/{trip_id}",
            headers=_get_headers(),
            json=body,
            timeout=10,
        )
        if resp.status_code in (200, 201):
            log.info("Saved trip %s via REST API", trip_id)
            return True
        else:
            log.warning("Firestore REST save failed for %s: %s %s", trip_id, resp.status_code, resp.text[:200])
            return False
    except Exception as exc:
        log.exception("Firestore REST save_trip error for %s: %s", trip_id, exc)
        return False


def _save_trip_admin(trip_id: str, doc: dict) -> bool:
    """Save via firebase-admin SDK (may fail with gRPC issues)."""
    try:
        _admin_db.collection("trips").document(trip_id).set(doc)
        log.info("Saved trip %s via firebase-admin", trip_id)
        return True
    except Exception as exc:
        log.exception("firebase-admin save_trip failed for %s: %s", trip_id, exc)
        return False


def load_trip(trip_id: str) -> Optional[dict[str, Any]]:
    _ensure_init()

    if _REST_READY:
        return _load_trip_rest(trip_id)
    if _USE_ADMIN_SDK and _admin_db:
        return _load_trip_admin(trip_id)
    return None


def _load_trip_rest(trip_id: str) -> Optional[dict[str, Any]]:
    """Load via Firestore REST API."""
    url = f"{_BASE_URL}/trips/{trip_id}"
    try:
        resp = http_requests.get(url, headers=_get_headers(), timeout=10)
        if resp.status_code == 200:
            return _doc_to_dict(resp.json())
        elif resp.status_code == 404:
            return None
        else:
            log.warning("Firestore REST load failed for %s: %s", trip_id, resp.status_code)
            return None
    except Exception as exc:
        log.exception("Firestore REST load_trip error for %s: %s", trip_id, exc)
        return None


def _load_trip_admin(trip_id: str) -> Optional[dict[str, Any]]:
    """Load via firebase-admin SDK."""
    try:
        snap = _admin_db.collection("trips").document(trip_id).get()
        return snap.to_dict() if snap.exists else None
    except Exception:
        log.exception("firebase-admin load_trip failed for %s", trip_id)
        return None


def increment_share_view(trip_id: str) -> None:
    """Best-effort view counter via REST."""
    _ensure_init()
    if not _REST_READY:
        return
    try:
        url = f"{_BASE_URL}/share_views/{trip_id}"
        # Read current, increment, write back (REST doesn't have atomic increment)
        resp = http_requests.get(url, headers=_get_headers(), timeout=5)
        count = 0
        if resp.status_code == 200:
            data = _doc_to_dict(resp.json())
            count = data.get("view_count", 0)
        fields = {
            "view_count": _python_to_firestore_value(count + 1),
            "last_viewed_at": _python_to_firestore_value(datetime.now(tz=timezone.utc).isoformat()),
        }
        http_requests.patch(
            url,
            headers=_get_headers(),
            json={"fields": fields},
            timeout=5,
        )
    except Exception:
        log.exception("share_views increment failed for %s", trip_id)


# ── Generic CRUD helpers (used by OTP service, etc.) ──────────────────────────

def set_doc(collection: str, doc_id: str, data: dict[str, Any]) -> bool:
    """Write a document (create or overwrite)."""
    _ensure_init()
    if _REST_READY:
        url = f"{_BASE_URL}/{collection}/{doc_id}"
        fields = {k: _python_to_firestore_value(v) for k, v in data.items()}
        try:
            resp = http_requests.patch(url, headers=_get_headers(), json={"fields": fields}, timeout=10)
            return resp.status_code in (200, 201)
        except Exception as exc:
            log.exception("set_doc REST error (%s/%s): %s", collection, doc_id, exc)
            return False
    if _USE_ADMIN_SDK and _admin_db:
        try:
            _admin_db.collection(collection).document(doc_id).set(data)
            return True
        except Exception as exc:
            log.exception("set_doc admin error (%s/%s): %s", collection, doc_id, exc)
            return False
    return False


def get_doc(collection: str, doc_id: str) -> Optional[dict[str, Any]]:
    """Read a document. Returns None if not found."""
    _ensure_init()
    if _REST_READY:
        url = f"{_BASE_URL}/{collection}/{doc_id}"
        try:
            resp = http_requests.get(url, headers=_get_headers(), timeout=10)
            if resp.status_code == 200:
                return _doc_to_dict(resp.json())
            return None
        except Exception as exc:
            log.exception("get_doc REST error (%s/%s): %s", collection, doc_id, exc)
            return None
    if _USE_ADMIN_SDK and _admin_db:
        try:
            snap = _admin_db.collection(collection).document(doc_id).get()
            return snap.to_dict() if snap.exists else None
        except Exception:
            log.exception("get_doc admin error (%s/%s)", collection, doc_id)
            return None
    return None


def update_doc(collection: str, doc_id: str, updates: dict[str, Any]) -> bool:
    """Merge-update specific fields on a document."""
    _ensure_init()
    if _REST_READY:
        url = f"{_BASE_URL}/{collection}/{doc_id}"
        # Build updateMask for partial update
        mask = "&".join(f"updateMask.fieldPaths={k}" for k in updates.keys())
        fields = {k: _python_to_firestore_value(v) for k, v in updates.items()}
        try:
            resp = http_requests.patch(
                f"{url}?{mask}",
                headers=_get_headers(),
                json={"fields": fields},
                timeout=10,
            )
            return resp.status_code in (200, 201)
        except Exception as exc:
            log.exception("update_doc REST error (%s/%s): %s", collection, doc_id, exc)
            return False
    if _USE_ADMIN_SDK and _admin_db:
        try:
            _admin_db.collection(collection).document(doc_id).update(updates)
            return True
        except Exception as exc:
            log.exception("update_doc admin error (%s/%s): %s", collection, doc_id, exc)
            return False
    return False


def delete_doc(collection: str, doc_id: str) -> bool:
    """Delete a document."""
    _ensure_init()
    if _REST_READY:
        url = f"{_BASE_URL}/{collection}/{doc_id}"
        try:
            resp = http_requests.delete(url, headers=_get_headers(), timeout=10)
            return resp.status_code in (200, 204)
        except Exception:
            return False
    if _USE_ADMIN_SDK and _admin_db:
        try:
            _admin_db.collection(collection).document(doc_id).delete()
            return True
        except Exception:
            return False
    return False

