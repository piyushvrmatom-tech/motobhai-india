"""OTP send + verify endpoints — MSG91 + Firestore + signed JWT."""
from __future__ import annotations

import logging

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
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not ok:
        log.warning("OTP send refused: %s", msg)
        raise HTTPException(status_code=502, detail="sms_provider_error")
    return {"ok": True}


@router.post("/api/otp/verify")
def verify_otp(req: OtpVerifyRequest):
    try:
        ok = otp_service.verify(req.phone, req.code)
    except otp_service.OtpError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=401, detail="invalid_or_expired")
    # Hash the phone for the JWT subject — we never put raw PII in the token.
    sub = otp_service._phone_hash(req.phone)
    token = jwt_service.sign({"sub": sub})
    return {"ok": True, "token": token}
