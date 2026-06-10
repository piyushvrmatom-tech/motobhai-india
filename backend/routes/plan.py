"""POST /api/plan — the heart of the product. CTO spec §4.1."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from backend.models.trip import (
    DayPlan,
    FuelStop,
    HotelSuggestion,
    PlanRequest,
    PlanResponse,
    ReceiptRequest,
    TripSummary,
)
from backend.services import bikes, firestore_client, gemini, routes_api, sheets_logger
from backend.services.splitter import SplitterRejection, split

log = logging.getLogger(__name__)
router = APIRouter()


def _current_season(now: datetime) -> str:
    m = now.month
    if m in (3, 4, 5):
        return "summer"
    if m in (6, 7, 8, 9):
        return "monsoon"
    if m in (10, 11):
        return "post-monsoon"
    return "winter"


@router.post("/api/plan", response_model=PlanResponse)
def create_plan(req: PlanRequest) -> PlanResponse:
    # Normalise frontend vibe synonyms → canonical 3 Gemini values
    _VIBE_MAP = {
        "scenic": "chill", "chill": "chill",
        "express": "standard", "standard": "standard",
        "offroad": "hardcore", "adventure": "hardcore", "hardcore": "hardcore",
    }
    vibe = _VIBE_MAP.get(req.vibe, "standard")

    # 1. Get route distance via Routes API.
    try:
        route = routes_api.compute(req.origin, req.destination, req.waypoints)
    except routes_api.RoutesApiError as exc:
        log.exception("Routes API failed")
        raise HTTPException(status_code=502, detail=f"routes_api: {exc}") from exc

    # 2. Split into legs under the 350km cap.
    split_waypoints = []
    if req.waypoints and len(route.legs) > 1:
        cum_km = 0.0
        for idx, leg in enumerate(route.legs[:-1]):
            if idx < len(req.waypoints):
                cum_km += leg.distance_m / 1000.0
                split_waypoints.append((req.waypoints[idx], cum_km))

    try:
        plan = split(route.distance_km, req.days, req.origin, req.destination, split_waypoints)
    except SplitterRejection as rej:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "trip_too_long_for_days",
                "total_km": rej.total_km,
                "requested_days": rej.requested_days,
                "suggested_days": rej.suggested_days,
                "message": str(rej),
            },
        )

    legs_payload = [
        {"day": leg.day, "from": leg.origin, "to": leg.destination, "km": leg.km}
        for leg in plan.legs
    ]

    # 3. Gemini fills in the colour (fuel stops, hotels, tips).
    bike_label = bikes.label_for(req.bike_id, req.bike_custom)
    season = _current_season(datetime.now(tz=timezone.utc))
    try:
        ai = gemini.generate_itinerary(
            origin=req.origin,
            destination=req.destination,
            days=req.days,
            legs=legs_payload,
            bike_label=bike_label,
            vibe=vibe,
            budget_tier=req.budget_tier,
            season=season,
        )
    except Exception as exc:
        log.exception("Gemini failed")
        raise HTTPException(status_code=502, detail=f"gemini: {exc}") from exc

    # 4. Merge splitter legs (authoritative) with Gemini's colour.
    ai_days = {d.get("day"): d for d in (ai.get("days_plan") or [])}
    days_plan: list[DayPlan] = []
    for leg in plan.legs:
        ai_day = ai_days.get(leg.day, {})
        days_plan.append(
            DayPlan(
                day=leg.day,
                **{
                    "from": leg.origin,
                    "to": leg.destination,
                },
                km=leg.km,
                eta_hours=float(ai_day.get("eta_hours", round(leg.km / 50, 1))),
                elevation_gain_m=int(ai_day.get("elevation_gain_m", 0)),
                route_polyline=route.polyline if leg.day == 1 else "",
                fuel_stops=[FuelStop(**fs) for fs in (ai_day.get("fuel_stops") or [])],
                hotel_suggestion=(
                    HotelSuggestion(**ai_day["hotel_suggestion"])
                    if ai_day.get("hotel_suggestion")
                    else None
                ),
                food_stops=list(ai_day.get("food_stops") or []),
                bhai_tip=str(ai_day.get("bhai_tip", "")),
                warnings=list(ai_day.get("warnings") or []),
            )
        )

    # 5. Persist + build response.
    trip_id = firestore_client.new_trip_id()
    share_base = os.getenv("SHARE_BASE_URL", "https://motobhai.app").rstrip("/")
    share_url = f"{share_base}/s/{trip_id.removeprefix('mb_')}"

    summary = TripSummary(
        **{"from": req.origin, "to": req.destination},
        total_km=plan.total_km,
        total_days=req.days,
        est_fuel_cost_inr=int(ai.get("est_fuel_cost_inr", 0)),
        est_hotel_cost_inr=int(ai.get("est_hotel_cost_inr", 0)),
        max_day_km=plan.max_day_km,
    )
    warnings = list(plan.warnings) + list(ai.get("warnings") or []) + list(route.warnings or [])

    response = PlanResponse(
        trip_id=trip_id,
        created_at=datetime.now(tz=timezone.utc),
        summary=summary,
        days_plan=days_plan,
        warnings=warnings,
        share_url=share_url,
        pdf_url=None,
    )

    # Persist (best-effort) + log (fire-and-forget).
    try:
        saved = firestore_client.save_trip(trip_id, response.model_dump(mode="json", by_alias=True))
        if not saved:
            log.warning("Firestore save_trip returned False for %s (db=None?)", trip_id)
    except Exception as _fs_err:
        log.exception("Firestore save_trip failed (non-fatal) for %s: %s", trip_id, _fs_err)
    sheets_logger.log_event_sync(
        "plan_created",
        trip_id=trip_id,
        origin=req.origin,
        destination=req.destination,
        days=req.days,
        total_km=plan.total_km,
        vibe=vibe,
        bike_id=req.bike_id or "custom",
    )

    return response


@router.get("/api/motorcycles")
def list_motorcycles():
    return {"motorcycles": bikes.all_bikes()}


@router.post("/api/analyze-receipt")
def analyze_receipt(req: ReceiptRequest):
    try:
        result = gemini.analyze_receipt(req.base64_data, req.mime_type)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
