"""OTP send + verify — MSG91 transactional SMS + Firestore-backed code store.

Codes are never stored in plaintext. We hash the phone number to form the
document id, and HMAC-SHA256 the OTP code with `OTP_SECRET` so that a leaked
Firestore dump cannot be replayed.

Uses the generic Firestore CRUD helpers from firestore_client (REST API based).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Tuple

import requests

from backend.services import firestore_client

log = logging.getLogger(__name__)

OTP_LENGTH = 6
OTP_TTL_MIN = 5
MAX_ATTEMPTS = 3
MSG91_API_URL = "https://control.msg91.com/api/v5/flow"
DLT_TEMPLATE_ID = os.getenv("MSG91_TEMPLATE_ID", "")
SENDER_ID = "MOTBHA"


class OtpError(Exception):
    pass


def _phone_hash(phone: str) -> str:
    secret = os.getenv("OTP_SECRET", "").encode("utf-8")
    return hmac.new(secret, phone.encode("utf-8"), hashlib.sha256).hexdigest()


def _code_hash(code: str) -> str:
    secret = os.getenv("OTP_SECRET", "").encode("utf-8")
    return hmac.new(secret, code.encode("utf-8"), hashlib.sha256).hexdigest()


def _generate_code() -> str:
    return f"{secrets.randbelow(10**OTP_LENGTH):0{OTP_LENGTH}d}"


def send(phone: str) -> Tuple[bool, str]:
    """Generate a fresh OTP, persist its hash, dispatch via MSG91."""
    if not os.getenv("OTP_SECRET"):
        raise OtpError("OTP_SECRET not configured")

    if not firestore_client.is_enabled():
        raise OtpError("Firestore unavailable")

    phash = _phone_hash(phone)
    code = _generate_code()
    expires = datetime.now(tz=timezone.utc) + timedelta(minutes=OTP_TTL_MIN)

    otp_doc = {
        "phone_hash": phash,
        "code_hash": _code_hash(code),
        "expires_at": expires.isoformat(),
        "attempts": 0,
        "used": False,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    ok = firestore_client.set_doc("otp_codes", phash, otp_doc)
    if not ok:
        raise OtpError("otp_store_failed")

    auth_key = os.getenv("MSG91_AUTH_KEY", "").strip()
    if not auth_key or not DLT_TEMPLATE_ID:
        if os.getenv("ENV", "production") != "production":
            log.warning("MSG91 not configured (staging): code for %s is %s", phone, code)
            return True, "staging-bypass"
        raise OtpError("MSG91 not configured")

    body = {
        "template_id": DLT_TEMPLATE_ID,
        "sender": SENDER_ID,
        "short_url": "0",
        "mobiles": phone.lstrip("+"),
        "var1": code,
    }
    headers = {"authkey": auth_key, "Content-Type": "application/json"}
    try:
        r = requests.post(MSG91_API_URL, json=body, headers=headers, timeout=6)
        if r.status_code >= 400:
            log.error("MSG91 send failed %s: %s", r.status_code, r.text[:200])
            return False, f"msg91 {r.status_code}"
    except requests.RequestException as exc:
        log.exception("MSG91 network error")
        return False, str(exc)
    return True, "sent"


def verify(phone: str, code: str) -> bool:
    """Verify a submitted code. Returns True on success."""
    if not firestore_client.is_enabled():
        raise OtpError("Firestore unavailable")

    phash = _phone_hash(phone)
    rec = firestore_client.get_doc("otp_codes", phash)

    if rec is None:
        return False
    if rec.get("used"):
        return False
    if rec.get("attempts", 0) >= MAX_ATTEMPTS:
        return False

    expires_str = rec.get("expires_at", "")
    if expires_str:
        try:
            expires = datetime.fromisoformat(expires_str)
            if expires < datetime.now(tz=timezone.utc):
                return False
        except (ValueError, TypeError):
            pass

    expected = rec.get("code_hash", "")
    actual = _code_hash(code)
    ok = hmac.compare_digest(expected, actual)

    if ok:
        firestore_client.update_doc("otp_codes", phash, {
            "used": True,
            "verified_at": datetime.now(tz=timezone.utc).isoformat(),
        })
    else:
        firestore_client.update_doc("otp_codes", phash, {
            "attempts": rec.get("attempts", 0) + 1,
        })
    return ok
