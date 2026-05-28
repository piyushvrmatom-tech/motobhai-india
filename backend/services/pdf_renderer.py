"""WeasyPrint PDF renderer — Jinja2 template → A4 landscape PDF.

CTO spec §C.D: "Every PDF generated must open on iOS Safari, Android Chrome,
Windows Edge." WeasyPrint produces standards-compliant PDF/A which all of
these handle natively.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


class PdfRenderError(Exception):
    pass


def render_trip_pdf(trip: dict[str, Any], *, bike_label: str = "", vibe: str = "standard") -> bytes:
    """Render a complete itinerary PDF for the given trip dict.

    `trip` must match the PlanResponse JSON shape (with `by_alias=True`):
        - summary: { from, to, total_km, total_days, max_day_km, est_fuel_cost_inr, est_hotel_cost_inr }
        - days_plan: [ { day, from, to, km, eta_hours, ..., bhai_tip, hotel_suggestion, ... } ]
        - share_url, trip_id, warnings, ...
    """
    try:
        # Lazy import — WeasyPrint pulls in cairo/pango at import time which
        # we don't want hitting startup if PDFs aren't being used.
        from weasyprint import HTML  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise PdfRenderError(f"WeasyPrint not installed: {exc}") from exc

    template = _env.get_template("itinerary.html")
    html = template.render(
        trip=trip,
        bike_label=bike_label or "Motorcycle",
        vibe=vibe or "standard",
        generated_at=datetime.now(tz=timezone.utc).strftime("%d %b %Y · %H:%M UTC"),
    )

    buf = io.BytesIO()
    try:
        HTML(string=html, base_url=str(TEMPLATE_DIR)).write_pdf(target=buf)
    except Exception as exc:
        raise PdfRenderError(f"WeasyPrint render failed: {exc}") from exc
    return buf.getvalue()
