"""GET /api/og/{short_id}.png — public OG image for a trip.

Used by the share.html `<meta property="og:image">` tag. If we already
generated and uploaded the image at plan time, we 302 to the GCS URL.
If not (legacy trip, GCS unavailable, etc.), we render on the fly and
stream the PNG with a 24h cache.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse, Response

from backend.services import firestore_client, og_image

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/og/{short_id}.png")
def get_og(short_id: str):
    trip_id = short_id if short_id.startswith("mb_") else f"mb_{short_id}"
    trip = firestore_client.load_trip(trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="trip not found")

    # Cached path — redirect to GCS public URL.
    existing = trip.get("og_image_url")
    if existing:
        return RedirectResponse(url=existing, status_code=302)

    # Render on the fly.
    summary = trip.get("summary") or {}
    png = og_image.render_trip_og(
        origin=summary.get("from", ""),
        destination=summary.get("to", ""),
        days=int(summary.get("total_days") or 0),
        total_km=float(summary.get("total_km") or 0),
        bike_label=trip.get("_bike_label", ""),
    )
    if png is None:
        raise HTTPException(status_code=503, detail="og_image_unavailable")
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
