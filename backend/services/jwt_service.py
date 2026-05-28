"""HS256-signed JWTs issued after successful OTP verify.

We use a tiny hand-rolled implementation to avoid a third-party dep — the
encoding is standard and the surface area is small (sign + verify + exp).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Optional


JWT_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days
ALG = "HS256"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = 4 - (len(s) % 4)
    return base64.urlsafe_b64decode(s + ("=" * (pad % 4)))


def _secret() -> bytes:
    secret = os.getenv("JWT_SECRET", "").strip()
    if not secret:
        raise RuntimeError("JWT_SECRET not configured")
    return secret.encode("utf-8")


def sign(payload: dict[str, Any], *, ttl_seconds: int = JWT_TTL_SECONDS) -> str:
    header = {"alg": ALG, "typ": "JWT"}
    now = int(time.time())
    body = dict(payload)
    body.setdefault("iat", now)
    body.setdefault("exp", now + ttl_seconds)
    body.setdefault("iss", "motobhai-india")

    h_b = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p_b = _b64url(json.dumps(body, separators=(",", ":"), default=str).encode("utf-8"))
    signing_input = f"{h_b}.{p_b}".encode("ascii")
    sig = hmac.new(_secret(), signing_input, hashlib.sha256).digest()
    return f"{h_b}.{p_b}.{_b64url(sig)}"


def verify(token: str) -> Optional[dict[str, Any]]:
    """Return the payload dict if the token is valid + unexpired, else None."""
    if not token or token.count(".") != 2:
        return None
    h_b, p_b, s_b = token.split(".")
    signing_input = f"{h_b}.{p_b}".encode("ascii")
    expected = hmac.new(_secret(), signing_input, hashlib.sha256).digest()
    try:
        actual = _b64url_decode(s_b)
    except Exception:
        return None
    if not hmac.compare_digest(expected, actual):
        return None
    try:
        payload = json.loads(_b64url_decode(p_b))
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload
