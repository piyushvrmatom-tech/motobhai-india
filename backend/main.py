"""
Moto Bhai India - Route Engine (FastAPI)
v0.2.0 - Adds destination, stops[], daily_limit_km, and Google Directions API
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import googlemaps
import os
import math

app = FastAPI(title="Moto Bhai India - Route Engine", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

GMAPS_API_KEY = os.getenv("GMAPS_API_KEY", "")
gmaps = googlemaps.Client(key=GMAPS_API_KEY) if GMAPS_API_KEY else None


class RouteRequest(BaseModel):
    origin: str
    destination: Optional[str] = None
    stops: Optional[List[str]] = Field(default_factory=list)
    trip_type: str = "round_trip"
    preferences: List[str] = Field(default_factory=list)
    motorcycle_brand: Optional[str] = None
    motorcycle_model: Optional[str] = None
    motorcycle_economy_kmpl: float = 30.0
    riders: int = 1
    days: int = 3
    daily_limit_km: Optional[int] = 250
    budget_tier: str = "standard"


PLACES_DB = {
    "mountain twisties": ["Shimla", "Manali", "Spiti Valley", "Munnar"],
    "scenic": ["Narkanda", "Sangla", "Coorg", "Ooty"],
    "offroad": ["Spiti Valley", "Ladakh", "Sandakphu"],
    "highway": ["Jaipur", "Udaipur", "Ahmedabad"],
    "plains tarmac": ["Agra", "Lucknow", "Bhopal"],
    "beaches": ["Goa", "Gokarna", "Pondicherry"],
    "food": ["Amritsar", "Lucknow", "Hyderabad"],
    "heritage": ["Jaipur", "Hampi", "Khajuraho"],
    "nature": ["Jim Corbett", "Valley of Flowers", "Coorg"],
    "city": ["Mumbai", "Bengaluru", "Delhi"],
    "sightseeing": ["Agra", "Jaipur", "Varanasi"],
}
BUDGET = {"economy": 1200, "standard": 2800, "premium": 6000, "luxury": 12000}
PETROL = 105


def pick_preference_stops(prefs, n):
    picked = []
    for p in prefs:
        for place in PLACES_DB.get(p, []):
            if place not in picked:
                picked.append(place)
            if len(picked) >= n:
                return picked
    return picked


def compute_directions(origin, destination, waypoints):
    if not gmaps:
        return None
    try:
        result = gmaps.directions(
            origin=origin,
            destination=destination,
            waypoints=waypoints or None,
            mode="driving",
            units="metric",
            region="in",
        )
        if not result:
            return None
        legs = result[0].get("legs", [])
        total_m = sum(l["distance"]["value"] for l in legs)
        total_s = sum(l["duration"]["value"] for l in legs)
        return {
            "total_km": round(total_m / 1000, 2),
            "total_hours": round(total_s / 3600, 2),
            "legs": [
                {
                    "from": l["start_address"],
                    "to": l["end_address"],
                    "distance_km": round(l["distance"]["value"] / 1000, 2),
                    "duration_hours": round(l["duration"]["value"] / 3600, 2),
                }
                for l in legs
            ],
            "polyline": result[0].get("overview_polyline", {}).get("points", ""),
        }
    except Exception as e:
        raise HTTPException(502, f"Google Directions error: {e}")


@app.get("/")
def root():
    return {"app": "Moto Bhai India", "version": "0.2.0", "status": "running", "gmaps_enabled": bool(gmaps)}


@app.post("/api/generate-itinerary")
def generate(req: RouteRequest):
    # Destination resolution
    if req.trip_type == "round_trip":
        destination = req.origin
    elif req.destination:
        destination = req.destination
    elif req.stops:
        destination = req.stops[-1]
    else:
        raise HTTPException(400, "destination or stops[] required for non-round-trip")

    # Waypoints = user stops + preference fill
    waypoints = list(req.stops or [])
    if req.trip_type != "round_trip" and waypoints and waypoints[-1] == destination:
        waypoints = waypoints[:-1]
    target_extra = max(0, req.days - 1 - len(waypoints))
    waypoints.extend(p for p in pick_preference_stops(req.preferences, target_extra) if p not in waypoints)
    waypoints = waypoints[:23]

    # Real distance via Directions API or fallback
    directions = compute_directions(req.origin, destination, waypoints)
    if directions is None:
        total_km = (req.daily_limit_km or 250) * req.days
        total_hours = total_km / 50
        legs, polyline = [], ""
    else:
        total_km = directions["total_km"]
        total_hours = directions["total_hours"]
        legs = directions["legs"]
        polyline = directions["polyline"]

    daily_avg = total_km / req.days
    limit = req.daily_limit_km or 250
    over = daily_avg > limit
    suggested_days = math.ceil(total_km / limit) if limit else req.days

    litres = total_km / req.motorcycle_economy_kmpl if req.motorcycle_economy_kmpl else 0
    fuel_cost = round(litres * PETROL, 2)
    nightly = BUDGET.get(req.budget_tier, 2800)
    hotel_cost = nightly * max(req.days - 1, 0) * req.riders

    stops_for_url = [req.origin] + waypoints + [destination]
    maps_url = "https://www.google.com/maps/dir/" + "/".join(s.replace(" ", "+") for s in stops_for_url)

    return {
        "status": "success",
        "trip_name": f"Moto Bhai - {req.origin} to {destination}",
        "trip_type": req.trip_type,
        "origin": req.origin,
        "destination": destination,
        "waypoints": waypoints,
        "maps_url": maps_url,
        "distance": {
            "total_km": total_km,
            "daily_avg_km": round(daily_avg, 2),
            "daily_limit_km": limit,
            "exceeds_daily_limit": over,
            "suggested_days": suggested_days,
        },
        "duration": {
            "total_hours": total_hours,
            "daily_avg_hours": round(total_hours / req.days, 2) if req.days else 0,
        },
        "legs": legs,
        "polyline": polyline,
        "fuel": {"litres": round(litres, 2), "price_per_litre_inr": PETROL, "cost_inr": fuel_cost},
        "accommodation": {
            "tier": req.budget_tier,
            "nightly_inr": nightly,
            "nights": max(req.days - 1, 0),
            "total_inr": hotel_cost,
        },
        "total_trip_cost_inr": round(fuel_cost + hotel_cost, 2),
        "meta": {
            "gmaps_enabled": bool(gmaps),
            "riders": req.riders,
            "motorcycle": (f"{req.motorcycle_brand or ''} {req.motorcycle_model or ''}".strip() or None),
        },
    }
