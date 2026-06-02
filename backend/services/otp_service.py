"""OTP send + verify — MSG91 OTP API.

Uses MSG91's dedicated OTP API which handles:
- OTP generation and delivery
- DLT compliance (template management)
- Retry logic (voice fallback, resend)
- OTP verification and expiry

We keep a thin Firestore record for audit/rate-limiting but MSG91
manages the actual OTP lifecycle.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Tuple

import requests

from backend.services import firestore_client

log = logging.getLogger(__name__)

OTP_LENGTH = 6
OTP_TTL_MIN = 5
MSG91_OTP_SEND = "https://control.msg91.com/api/v5/otp"
MSG91_OTP_VERIFY = "https://control.msg91.com/api/v5/otp/verify"
MSG91_OTP_RESEND = "https://control.msg91.com/api/v5/otp/retry"


class OtpError(Exception):
    pass


def _phone_hash(phone: str) -> str:
    """Hash phone for JWT subject — we never put raw PII in tokens."""
    secret_str = os.getenv("OTP_SECRET", "dev-otp-secret").strip()
    if not secret_str:
        secret_str = "dev-otp-secret"
    secret = secret_str.encode("utf-8")
    return hmac.new(secret, phone.encode("utf-8"), hashlib.sha256).hexdigest()


def send(phone: str) -> Tuple[bool, str]:
    """Send OTP via MSG91 OTP API."""
    auth_key = os.getenv("MSG91_AUTH_KEY", "").strip()
    template_id = os.getenv("MSG91_TEMPLATE_ID", "").strip()

    # Bypassing for testing/mock environment
    if not auth_key or auth_key.lower().startswith("mock") or template_id.lower().startswith("mock"):
        log.warning("MSG91 keys missing or set to mock. Running OTP send in mock mode.")
        return True, "sent"

    # Normalize phone: ensure it's just digits with country code
    mobile = phone.lstrip("+")
    if mobile.startswith("91") and len(mobile) == 12:
        pass  # already correct: 91XXXXXXXXXX
    elif len(mobile) == 10:
        mobile = "91" + mobile
    else:
        raise OtpError("invalid_phone_format")

    # Call MSG91 OTP API
    # Per MSG91 docs: template_id, mobile, authkey go as URL query params
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    params = {
        "template_id": template_id,
        "mobile": mobile,
        "authkey": auth_key,
        "otp_length": str(OTP_LENGTH),
        "otp_expiry": str(OTP_TTL_MIN),
    }

    try:
        r = requests.post(MSG91_OTP_SEND, params=params, headers=headers, timeout=10)
        resp = {}
        try:
            resp = r.json()
        except Exception:
            pass
        log.info("MSG91 OTP send response [%s]: %s", r.status_code, r.text[:300])

        if r.status_code >= 400:
            detail = resp.get("message", r.text[:200])
            log.error("MSG91 OTP send failed %s: %s", r.status_code, detail)
            return False, f"msg91_error_{r.status_code}: {detail}"

        msg_type = resp.get("type", "")
        if msg_type == "error":
            log.error("MSG91 OTP error: %s", resp.get("message", "unknown"))
            return False, resp.get("message", "msg91_error")

    except requests.RequestException as exc:
        log.exception("MSG91 OTP network error")
        return False, str(exc)

    # Audit log in Firestore (non-blocking, best-effort)
    try:
        if firestore_client.is_enabled():
            phash = _phone_hash(phone)
            firestore_client.set_doc("otp_audit", phash, {
                "phone_hash": phash,
                "sent_at": datetime.now(tz=timezone.utc).isoformat(),
                "provider": "msg91_otp_api",
            })
    except Exception:
        pass  # audit failure should never block OTP

    return True, "sent"


def verify(phone: str, code: str) -> bool:
    """Verify OTP via MSG91 OTP Verify API."""
    auth_key = os.getenv("MSG91_AUTH_KEY", "").strip()
    
    if not auth_key or auth_key.lower().startswith("mock"):
        log.warning("MSG91 key missing or set to mock. Accepting any code in mock mode.")
        # Audit success (mock)
        try:
            if firestore_client.is_enabled():
                phash = _phone_hash(phone)
                firestore_client.update_doc("otp_audit", phash, {
                    "verified_at": datetime.now(tz=timezone.utc).isoformat(),
                    "verified": True,
                })
        except Exception:
            pass
        return True

    mobile = phone.lstrip("+")
    if mobile.startswith("91") and len(mobile) == 12:
        pass
    elif len(mobile) == 10:
        mobile = "91" + mobile
    else:
        return False

    # MSG91 docs: mobile, otp, authkey as query params
    params = {
        "mobile": mobile,
        "otp": code,
        "authkey": auth_key,
    }

    try:
        r = requests.get(MSG91_OTP_VERIFY, params=params, timeout=10)
        resp = {}
        try:
            resp = r.json()
        except Exception:
            pass
        log.info("MSG91 OTP verify response [%s]: %s", r.status_code, r.text[:300])

        if r.status_code == 200 and resp.get("type") == "success":
            # Audit success
            try:
                if firestore_client.is_enabled():
                    phash = _phone_hash(phone)
                    firestore_client.update_doc("otp_audit", phash, {
                        "verified_at": datetime.now(tz=timezone.utc).isoformat(),
                        "verified": True,
                    })
            except Exception:
                pass
            return True

        log.warning("MSG91 OTP verify failed: %s", resp.get("message", r.text[:200]))
        return False

    except requests.RequestException as exc:
        log.exception("MSG91 OTP verify network error")
        raise OtpError("verification_network_error") from exc
