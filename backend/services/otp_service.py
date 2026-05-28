"""OTP send + verify — MSG91 transactional SMS + Firestore-backed code store.

Codes are never stored in plaintext. We hash the phone number to form the
document id, and HMAC-SHA256 the OTP code with `OTP_SECRET` so that a leaked
Firestore dump cannot be replayed.

DLT template (MSG91, sender MOTBHA, route 4):
    "Your Moto Bhai verification code is {{var1}}. Valid for 5 minutes. Do not share with anyone."
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

from backend.services.firestore_client import get_db

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
    # Cryptographically-strong 6-digit code, no leading-zero ambiguity issue.
    return f"{secrets.randbelow(10**OTP_LENGTH):0{OTP_LENGTH}d}"


def send(phone: str) -> Tuple[bool, str]:
    """Generate a fresh OTP, persist its hash, dispatch via MSG91.

    Returns `(ok, message)`. On failure `message` is human-readable for logs;
    callers should NOT surface it to clients verbatim.
    """
    if not os.getenv("OTP_SECRET"):
        raise OtpError("OTP_SECRET not configured")

    db = get_db()
    if db is None:
        raise OtpError("Firestore unavailable")

    phash = _phone_hash(phone)
    code = _generate_code()
    expires = datetime.now(tz=timezone.utc) + timedelta(minutes=OTP_TTL_MIN)

    try:
        db.collection("otp_codes").document(phash).set(
            {
                "phone_hash": phash,
                "code_hash": _code_hash(code),
                "expires_at": expires,
                "attempts": 0,
                "used": False,
                "created_at": datetime.now(tz=timezone.utc),
            }
        )
    except Exception as exc:
        log.exception("OTP Firestore write failed for %s", phash[:8])
        raise OtpError(f"otp_store_failed: {exc}") from exc

    auth_key = os.getenv("MSG91_AUTH_KEY", "").strip()
    if not auth_key or not DLT_TEMPLATE_ID:
        # In staging without keys we still return ok so the flow is testable.
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
    """Verify a submitted code. Constant-time compare. Burns the doc on success.

    Returns True on success, False on any failure mode (expired, wrong code,
    too many attempts, no record). Does not leak which mode failed.
    """
    db = get_db()
    if db is None:
        raise OtpError("Firestore unavailable")

    phash = _phone_hash(phone)
    try:
        ref = db.collection("otp_codes").document(phash)
        snap = ref.get()
    except Exception as exc:
        log.exception("OTP Firestore read failed")
        raise OtpError(f"otp_read_failed: {exc}") from exc

    if not snap.exists:
        return False
    rec = snap.to_dict() or {}

    if rec.get("used"):
        return False
    if rec.get("attempts", 0) >= MAX_ATTEMPTS:
        return False
    expires = rec.get("expires_at")
    if expires and expires < datetime.now(tz=timezone.utc):
        return False

    expected = rec.get("code_hash", "")
    actual = _code_hash(code)
    ok = hmac.compare_digest(expected, actual)

    # Atomic-ish update: read-then-write is racy but acceptable here.
    try:
        if ok:
            ref.update({"used": True, "verified_at": datetime.now(tz=timezone.utc)})
        else:
            ref.update({"attempts": rec.get("attempts", 0) + 1})
    except Exception:
        log.warning("OTP Firestore update failed (non-fatal)")
    return ok
