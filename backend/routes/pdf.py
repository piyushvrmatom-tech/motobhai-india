"""POST /api/pdf — generate PDF for an existing trip and return signed Cloud Storage URL.

CTO spec §4.1: request body is `{ trip_id }`, response is `{ pdf_url }`.

Behaviour:
  1. Load the trip from Firestore (must exist; otherwise 404).
  2. Render the PDF via WeasyPrint.
  3. Upload to GCS bucket → 7-day signed URL.
  4. Update the trip doc with `pdf_url` so subsequent /api/share/{id} reads include it.

If GCS isn't configured we fall back to streaming the PDF directly so the
endpoint never silently 5xxs.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from backend.services import bikes, firestore_client, pdf_renderer, storage

log = logging.getLogger(__name__)
router = APIRouter()


class PdfRequest(BaseModel):
    trip_id: str


@router.post("/api/pdf")
def generate_pdf(req: PdfRequest):
    trip = firestore_client.load_trip(req.trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="trip not found")

    # Pull the bike label from the original request if we stored it; otherwise infer.
    bike_label = trip.get("_bike_label") or bikes.label_for(
        trip.get("_bike_id"), trip.get("_bike_custom")
    )
    vibe = trip.get("_vibe", "standard")

    try:
        pdf_bytes = pdf_renderer.render_trip_pdf(trip, bike_label=bike_label, vibe=vibe)
    except pdf_renderer.PdfRenderError as exc:
        log.exception("PDF render failed for %s", req.trip_id)
        raise HTTPException(status_code=502, detail=f"pdf_render: {exc}") from exc

    signed_url = storage.upload_pdf(req.trip_id, pdf_bytes)
    if signed_url:
        # Persist the URL back onto the trip so share view + future calls reuse it.
        try:
            db = firestore_client.get_db()
            if db is not None:
                db.collection("trips").document(req.trip_id).update({"pdf_url": signed_url})
        except Exception:
            log.exception("failed to update trip with pdf_url")
        return {"pdf_url": signed_url}

    # Storage unavailable → stream PDF inline so the rider still gets it.
    log.warning("GCS disabled — streaming PDF directly for %s", req.trip_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="motobhai_{req.trip_id}.pdf"',
            "Cache-Control": "private, max-age=0, no-cache",
        },
    )
