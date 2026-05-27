"""
Moto Bhai India - Route Engine (FastAPI)
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import googlemaps
import os

app = FastAPI(title="Moto Bhai India - Route Engine", version="0.1.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

GMAPS_API_KEY = os.getenv("GMAPS_API_KEY", "")
gmaps = googlemaps.Client(key=GMAPS_API_KEY) if GMAPS_API_KEY else None

class RouteRequest(BaseModel):
    origin: str
    trip_type: str  # round_trip | one_way | multi_stop
    preferences: List[str]
    motorcycle_brand: Optional[str] = None
    motorcycle_model: Optional[str] = None
    motorcycle_economy_kmpl: float = 30.0
    riders: int = 1
    days: int = 3
    budget_tier: str = "standard"

PLACES_DB = {
    "mountain twisties": ["Shimla", "Manali", "Spiti Valley"],
    "scenic": ["Narkanda", "Sangla", "Coorg"],
    "offroad": ["Spiti Valley", "Ladakh"],
    "highway": ["Jaipur", "Udaipur"],
    "beaches": ["Goa", "Gokarna"],
    "food": ["Amritsar", "Lucknow"],
    "heritage": ["Jaipur", "Hampi"],
    "nature": ["Jim Corbett", "Coorg"],
    "sightseeing": ["Agra", "Jaipur"],
}

BUDGET = {"economy": 1200, "standard": 2800, "premium": 6000, "luxury": 12000}

@app.get("/")
def root():
    return {"app": "Moto Bhai India", "status": "running"}

@app.post("/api/generate-itinerary")
def generate(req: RouteRequest):
    waypoints = []
    for p in req.preferences:
        if p in PLACES_DB:
            waypoints.extend(PLACES_DB[p][:2])
    waypoints = list(dict.fromkeys(waypoints))[: max(req.days, 2)]
    if not waypoints:
        waypoints = ["Chandigarh", "Shimla"]

    if gmaps:
        try:
            d = gmaps.directions(
                origin=req.origin,
                destination=req.origin if req.trip_type == "round_trip" else waypoints[-1],
                waypoints=waypoints,
                mode="driving",
            )
            total_km = sum(l["distance"]["value"] for l in d[0]["legs"]) / 1000
        except Exception as e:
            raise HTTPException(400, f"Maps error: {e}")
    else:
        total_km = 250 * req.days

    petrol = 105
    litres = total_km / req.motorcycle_economy_kmpl
    fuel_cost = round(litres * petrol, 2)
    nightly = BUDGET.get(req.budget_tier, 2800)
    hotel_cost = nightly * max(req.days - 1, 0) * req.riders

    stops = [req.origin] + waypoints
    if req.trip_type == "round_trip":
        stops.append(req.origin)
    maps_url = "https://www.google.com/maps/dir/" + "/".join(s.replace(" ", "+") for s in stops)

    return {
        "status": "success",
        "trip_name": f"Moto Bhai - {req.origin} Adventure",
        "maps_url": maps_url,
        "waypoints": waypoints,
        "total_distance_km": round(total_km, 2),
        "daily_avg_km": round(total_km / req.days, 2),
        "fuel": {"litres": round(litres, 2), "cost_inr": fuel_cost},
        "accommodation": {"tier": req.budget_tier, "nightly_inr": nightly, "total_inr": hotel_cost},
        "total_trip_cost_inr": round(fuel_cost + hotel_cost, 2),
    }
