"""OTP send + verify endpoints — MSG91 OTP API + signed JWT."""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException

from backend.models.user import OtpSendRequest, OtpVerifyRequest
from backend.services import jwt_service, otp_service

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/otp/send")
def send_otp(req: OtpSendRequest):
    try:
        ok, msg = otp_service.send(req.phone)
    except otp_service.OtpError as exc:
        log.error("OTP send error: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not ok:
        log.warning("OTP send refused: %s", msg)
        raise HTTPException(status_code=502, detail=f"sms_provider_error: {msg}")
    return {"ok": True}


@router.post("/api/otp/verify")
def verify_otp(req: OtpVerifyRequest):
    try:
        ok = otp_service.verify(req.phone, req.code)
    except otp_service.OtpError as exc:
        log.error("OTP verify error: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=401, detail="invalid_or_expired")
    # Hash the phone for the JWT subject — we never put raw PII in the token.
    sub = otp_service._phone_hash(req.phone)
    token = jwt_service.sign({"sub": sub})
    return {"ok": True, "token": token}


@router.get("/api/otp/debug")
def otp_debug():
    """Non-sensitive debug info for OTP configuration."""
    auth_key = os.getenv("MSG91_AUTH_KEY", "").strip()
    template_id = os.getenv("MSG91_TEMPLATE_ID", "").strip()
    return {
        "auth_key_set": bool(auth_key),
        "auth_key_prefix": auth_key[:6] + "..." if len(auth_key) > 6 else "too_short",
        "template_id_set": bool(template_id),
        "template_id": template_id if template_id else "NOT_SET",
        "otp_secret_set": bool(os.getenv("OTP_SECRET", "").strip()),
        "api_endpoint": "https://control.msg91.com/api/v5/otp",
    }
