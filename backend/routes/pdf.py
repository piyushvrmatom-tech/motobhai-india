"""GET /api/plan/{trip_id}/pdf — generate and stream a PDF itinerary.

Uses WeasyPrint (already in requirements.txt) + Jinja2 to render
backend/templates/trip_pdf.html → PDF bytes → StreamingResponse.

No browser, no headless Chrome — pure Python, works on Render free tier.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from backend.services import firestore_client
from backend.services.bikes import get_bike

log = logging.getLogger(__name__)
router = APIRouter()

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _sanitize(obj):
    """Convert Firestore timestamps → strings recursively."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(i) for i in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "seconds"):
        return datetime.fromtimestamp(obj.seconds, tz=timezone.utc).isoformat()
    return obj


@router.get("/api/plan/{trip_id}/pdf")
def download_pdf(trip_id: str):
    """Fetch trip from Firestore, render HTML template, return PDF stream."""

    # 1. Load trip doc
    doc = firestore_client.load_trip(trip_id)
    if not doc:
        raise HTTPException(status_code=404, detail="trip not found")
    doc = _sanitize(doc)

    # 2. Build template context
    summary = doc.get("summary") or {}
    days_plan = doc.get("days_plan") or []
    warnings = doc.get("warnings") or []

    # Resolve bike label
    bike_id = doc.get("bike_id") or "re_himalayan_450"
    try:
        bike = get_bike(bike_id)
        bike_label = f"{bike.make} {bike.model} {bike.year}"
    except Exception:
        bike_label = bike_id.replace("_", " ").title()

    context = {
        "trip_id": trip_id,
        "summary": summary,
        "days_plan": days_plan,
        "warnings": warnings,
        "bike_label": bike_label,
        "generated_date": datetime.now(tz=timezone.utc).strftime("%d %b %Y"),
    }

    # 3. Render HTML
    try:
        template = _jinja_env.get_template("trip_pdf.html")
        html_str = template.render(**context)
    except Exception as exc:
        log.exception("Jinja2 render failed")
        raise HTTPException(status_code=500, detail="template error") from exc

    # 4. WeasyPrint → PDF bytes
    try:
        from weasyprint import HTML as WeasyprintHTML
        pdf_bytes = WeasyprintHTML(string=html_str, base_url="https://motobhai-india.web.app").write_pdf()
    except Exception as exc:
        log.exception("WeasyPrint failed")
        raise HTTPException(status_code=500, detail=f"pdf generation failed: {exc}") from exc

    # 5. Stream back
    from_city = (summary.get("from") or "trip").replace(" ", "_")
    to_city = (summary.get("to") or "").replace(" ", "_")
    filename = f"motobhai_{from_city}_{to_city}_{trip_id}.pdf"

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
