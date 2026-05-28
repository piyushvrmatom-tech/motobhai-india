"""Pydantic models for users + OTP flow."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class User(BaseModel):
    phone_hash: str
    created_at: datetime
    trip_ids: List[str] = Field(default_factory=list)
    last_seen_at: Optional[datetime] = None


class OtpSendRequest(BaseModel):
    phone: str = Field(pattern=r"^\+91[6-9]\d{9}$")


class OtpVerifyRequest(BaseModel):
    phone: str = Field(pattern=r"^\+91[6-9]\d{9}$")
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class OtpRecord(BaseModel):
    """Firestore document — phone is hashed, code is hashed."""

    phone_hash: str
    code_hash: str
    expires_at: datetime
    attempts: int = 0
    used: bool = False
