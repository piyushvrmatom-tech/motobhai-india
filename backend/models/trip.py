"""Pydantic models for /api/plan — matches CTO doc §4.1 contract."""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


Vibe = Literal["chill", "standard", "hardcore", "scenic", "offroad", "express", "adventure"]
BudgetTier = Literal["economy", "standard", "premium", "luxury"]


class PlanRequest(BaseModel):
    """Inbound payload for POST /api/plan.

    Mirrors the contract documented in CTO spec §4.1. Field names use the
    new v1 vocabulary: `from`/`to`/`days`/`bike_id`/`vibe`. `from` is a
    reserved word in Python, so we map it via the alias mechanism.
    """

    origin: str = Field(alias="from", min_length=2, max_length=120)
    destination: str = Field(alias="to", min_length=2, max_length=120)
    days: int = Field(ge=1, le=21)
    bike_id: Optional[str] = Field(default=None, max_length=64)
    bike_custom: Optional[str] = Field(default=None, max_length=120)
    vibe: Vibe = "standard"
    budget_tier: BudgetTier = "standard"
    loop: bool = False
    user_phone_hash: Optional[str] = Field(default=None, max_length=128)

    model_config = {"populate_by_name": True}

    @field_validator("bike_id", "bike_custom")
    @classmethod
    def _strip(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if isinstance(v, str) and v.strip() else None


class FuelStop(BaseModel):
    name: str
    km_from_start: float
    type: Literal["petrol", "diesel", "cng", "ev"] = "petrol"


class HotelSuggestion(BaseModel):
    name: str
    area: str = ""
    price_range_inr: str = ""
    google_place_id: Optional[str] = None


class DayPlan(BaseModel):
    day: int
    origin: str = Field(alias="from")
    destination: str = Field(alias="to")
    km: float
    eta_hours: float = 0.0
    elevation_gain_m: int = 0
    route_polyline: str = ""
    fuel_stops: List[FuelStop] = Field(default_factory=list)
    hotel_suggestion: Optional[HotelSuggestion] = None
    food_stops: List[str] = Field(default_factory=list)
    bhai_tip: str = ""
    warnings: List[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class TripSummary(BaseModel):
    origin: str = Field(alias="from")
    destination: str = Field(alias="to")
    total_km: float
    total_days: int
    est_fuel_cost_inr: int = 0
    est_hotel_cost_inr: int = 0
    max_day_km: float

    model_config = {"populate_by_name": True}


class PlanResponse(BaseModel):
    trip_id: str
    created_at: datetime
    summary: TripSummary
    days_plan: List[DayPlan]
    warnings: List[str] = Field(default_factory=list)
    share_url: str
    pdf_url: Optional[str] = None
