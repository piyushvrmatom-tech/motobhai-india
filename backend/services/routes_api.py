"""Thin wrapper around the Google **Routes API v2** (computeRoutes).

CTO §3.1 mandates this API specifically (NOT legacy Directions). We keep the
surface tiny: `compute(origin, destination, waypoints=None) -> RouteResult`.

Auth: uses `GOOGLE_ROUTES_API_KEY` (separate from the frontend Maps JS key so
we can apply IP allowlist restrictions to it).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List, Optional

import requests

log = logging.getLogger(__name__)

ROUTES_ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = (
    "routes.duration,routes.distanceMeters,"
    "routes.polyline.encodedPolyline,routes.legs.distanceMeters,"
    "routes.legs.duration,routes.warnings"
)


@dataclass
class RouteLeg:
    distance_m: int
    duration_s: int


@dataclass
class RouteResult:
    distance_km: float
    duration_hours: float
    polyline: str
    legs: List[RouteLeg]
    warnings: List[str]

    @property
    def distance_m(self) -> int:
        return int(self.distance_km * 1000)


class RoutesApiError(Exception):
    pass


def _waypoint(addr: str) -> dict:
    return {"address": addr + (", India" if "India" not in addr else "")}


def compute(
    origin: str,
    destination: str,
    waypoints: Optional[List[str]] = None,
    *,
    timeout_s: float = 8.0,
) -> RouteResult:
    """Call computeRoutes and return distance/duration/polyline.

    Raises `RoutesApiError` on any non-200 response or malformed payload.
    """
    api_key = os.getenv("GOOGLE_ROUTES_API_KEY", "").strip()
    if not api_key:
        raise RoutesApiError("GOOGLE_ROUTES_API_KEY is not set")

    body: dict = {
        "origin": _waypoint(origin),
        "destination": _waypoint(destination),
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "computeAlternativeRoutes": False,
        "languageCode": "en-IN",
        "units": "METRIC",
    }
    if waypoints:
        body["intermediates"] = [_waypoint(w) for w in waypoints]

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }

    try:
        resp = requests.post(ROUTES_ENDPOINT, json=body, headers=headers, timeout=timeout_s)
    except requests.RequestException as exc:
        raise RoutesApiError(f"network error: {exc}") from exc

    if resp.status_code != 200:
        raise RoutesApiError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    routes = data.get("routes") or []
    if not routes:
        raise RoutesApiError("no routes returned")

    r = routes[0]
    distance_m = int(r.get("distanceMeters", 0))
    # Duration comes as e.g. "12345s"
    dur_str = r.get("duration", "0s")
    duration_s = int(str(dur_str).rstrip("s") or 0)
    polyline = (r.get("polyline") or {}).get("encodedPolyline", "")
    legs = [
        RouteLeg(
            distance_m=int(leg.get("distanceMeters", 0)),
            duration_s=int(str(leg.get("duration", "0s")).rstrip("s") or 0),
        )
        for leg in r.get("legs", [])
    ]
    warnings = list(r.get("warnings") or [])

    return RouteResult(
        distance_km=round(distance_m / 1000.0, 1),
        duration_hours=round(duration_s / 3600.0, 2),
        polyline=polyline,
        legs=legs,
        warnings=warnings,
    )


def ping() -> bool:
    """Liveness check for /healthz — issues a tiny request, returns True on 200."""
    try:
        compute("Connaught Place, Delhi", "India Gate, Delhi", timeout_s=4.0)
        return True
    except Exception:
        return False
