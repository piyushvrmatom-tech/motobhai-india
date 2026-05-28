"""GET /api/plan/{trip_id}/pdf — pure-Python PDF using fpdf2.

fpdf2 has zero system dependencies — works on Render free tier.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from io import BytesIO

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.services import firestore_client
from backend.services.bikes import get_bike

log = logging.getLogger(__name__)
router = APIRouter()

ORANGE = (232, 117, 26)
DARK   = (26, 26, 26)
MUTED  = (120, 120, 120)
LIGHT  = (253, 248, 243)
WHITE  = (255, 255, 255)
WARN   = (255, 248, 225)
WARN_B = (255, 193, 7)


def _sanitize(obj):
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(i) for i in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "seconds"):
        return datetime.fromtimestamp(obj.seconds, tz=timezone.utc).isoformat()
    return obj


def _safe(text: str, maxlen: int = 120) -> str:
    """Strip non-latin chars fpdf2 can't render; truncate."""
    out = ""
    for ch in str(text or ""):
        if ord(ch) < 256:
            out += ch
        else:
            out += "?"
    return out[:maxlen]


def build_pdf(doc: dict) -> bytes:
    from fpdf import FPDF

    summary  = doc.get("summary") or {}
    days     = doc.get("days_plan") or []
    warnings = doc.get("warnings") or []
    trip_id  = doc.get("trip_id", "")

    bike_id = doc.get("bike_id") or "re_himalayan_450"
    try:
        bike = get_bike(bike_id)
        bike_label = f"{bike.make} {bike.model} {bike.year}"
    except Exception:
        bike_label = bike_id.replace("_", " ").title()

    from_city = _safe(summary.get("from", ""))
    to_city   = _safe(summary.get("to", ""))
    total_km  = round(summary.get("total_km", 0))
    total_days = summary.get("total_days", len(days))
    max_day   = summary.get("max_day_km", "?")
    fuel_cost = summary.get("est_fuel_cost_inr", 0)
    hotel_cost = summary.get("est_hotel_cost_inr", 0)
    gen_date  = datetime.now(tz=timezone.utc).strftime("%d %b %Y")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_margins(0, 0, 0)

    # ── COVER BANNER ────────────────────────────────────────────────
    pdf.set_fill_color(*ORANGE)
    pdf.rect(0, 0, 210, 54, "F")
    pdf.set_text_color(*WHITE)

    pdf.set_xy(14, 8)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Moto Bhai India", ln=True)

    pdf.set_xy(14, 20)
    pdf.set_font("Helvetica", "B", 22)
    pdf.cell(0, 10, f"{from_city}  ->  {to_city}", ln=True)

    pdf.set_xy(14, 33)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 8, f"{total_days}-day motorcycle itinerary  |  {_safe(bike_label)}  |  {gen_date}", ln=True)

    pdf.set_xy(14, 43)
    pdf.set_font("Helvetica", "B", 9)
    for badge in [f"{total_km} km total", f"{total_days} days", f"Max {max_day} km/day"]:
        pdf.set_fill_color(255, 255, 255)
        pdf.set_text_color(*ORANGE)
        w = pdf.get_string_width(badge) + 8
        pdf.cell(w, 7, badge, border=0, fill=True, ln=0)
        pdf.cell(3, 7, "", ln=0)

    # ── SUMMARY BAR ─────────────────────────────────────────────────
    pdf.set_y(56)
    col_w = 42
    items = [
        (str(total_km), "Total km"),
        (str(total_days), "Days"),
        (str(max_day), "Max km/day"),
        (f"Rs {fuel_cost:,}", "Fuel est."),
        (f"Rs {hotel_cost:,}", "Hotel est."),
    ]
    for i, (val, lbl) in enumerate(items):
        x = i * col_w
        pdf.set_xy(x, 56)
        pdf.set_fill_color(*LIGHT)
        pdf.rect(x, 56, col_w, 20, "F")
        pdf.set_text_color(*ORANGE)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_xy(x, 59)
        pdf.cell(col_w, 8, val, align="C", ln=False)
        pdf.set_xy(x, 67)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(*MUTED)
        pdf.cell(col_w, 5, lbl, align="C", ln=False)

    # Orange underline
    pdf.set_fill_color(*ORANGE)
    pdf.rect(0, 76, 210, 1.5, "F")

    # ── WARNINGS ────────────────────────────────────────────────────
    y = 82
    if warnings:
        pdf.set_xy(14, y)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*ORANGE)
        pdf.cell(0, 7, "Route Warnings", ln=True)
        y += 8
        for w_txt in warnings:
            pdf.set_fill_color(*WARN)
            pdf.rect(12, y, 186, 8, "F")
            pdf.set_fill_color(*WARN_B)
            pdf.rect(12, y, 2.5, 8, "F")
            pdf.set_xy(17, y + 1)
            pdf.set_font("Helvetica", "", 8.5)
            pdf.set_text_color(*DARK)
            pdf.cell(0, 6, _safe(f"  {w_txt}"), ln=True)
            y += 10

    # ── ITINERARY ───────────────────────────────────────────────────
    pdf.set_xy(14, y)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*ORANGE)
    pdf.cell(0, 8, "Day-by-Day Itinerary", ln=True)
    y += 9

    for day in days:
        from_d  = _safe(day.get("from") or day.get("origin", ""))
        to_d    = _safe(day.get("to") or day.get("destination", ""))
        km_d    = day.get("km", 0)
        hrs_d   = day.get("eta_hours", "?")
        elev_d  = day.get("elevation_gain_m", 0)
        tip     = _safe(day.get("bhai_tip", ""))
        fuel_s  = day.get("fuel_stops", [])
        food_s  = day.get("food_stops", [])
        hotel   = day.get("hotel_suggestion") or {}
        day_w   = day.get("warnings", [])
        day_n   = day.get("day", "?")

        # Calculate card height
        rows = len(fuel_s) + len(food_s) + (1 if hotel.get("name") else 0) + len(day_w) + (1 if tip else 0)
        card_h = 22 + rows * 8 + (10 if tip else 0)

        # Page break check
        if y + card_h > 275:
            pdf.add_page()
            y = 14

        # Day card background
        pdf.set_fill_color(255, 250, 245)
        pdf.rect(12, y, 186, card_h, "F")
        pdf.set_fill_color(*ORANGE)
        pdf.rect(12, y, 4, card_h, "F")

        # Day header
        pdf.set_xy(20, y + 3)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*DARK)
        pdf.cell(130, 7, f"Day {day_n}: {from_d}  ->  {to_d}", ln=False)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(*ORANGE)
        pdf.cell(0, 7, f"{km_d} km", align="R", ln=True)

        pdf.set_xy(20, y + 11)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 5, f"{hrs_d}h riding  |  Elevation gain: {elev_d}m", ln=True)

        row_y = y + 18

        for f in fuel_s:
            pdf.set_xy(22, row_y)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*DARK)
            fname = _safe(f.get("name", ""))
            fkm   = f.get("km_from_start", "?")
            pdf.cell(0, 7, f"  Fuel: {fname}  @  {fkm} km from start", ln=True)
            row_y += 7

        for r in food_s:
            pdf.set_xy(22, row_y)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*DARK)
            pdf.cell(0, 7, f"  Food: {_safe(r)}", ln=True)
            row_y += 7

        if hotel.get("name"):
            pdf.set_xy(22, row_y)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*DARK)
            area  = _safe(hotel.get("area", ""))
            price = hotel.get("price_range_inr", "")
            pdf.cell(0, 7, f"  Stay: {_safe(hotel['name'])}  |  {area}  |  Rs {price}", ln=True)
            row_y += 7

        for dw in day_w:
            pdf.set_xy(22, row_y)
            pdf.set_font("Helvetica", "I", 8.5)
            pdf.set_text_color(120, 80, 0)
            pdf.cell(0, 6, f"  ! {_safe(dw)}", ln=True)
            row_y += 6

        if tip:
            pdf.set_xy(22, row_y)
            pdf.set_font("Helvetica", "I", 8.5)
            pdf.set_text_color(100, 60, 0)
            pdf.cell(0, 7, f"  Tip: {tip[:110]}", ln=True)
            row_y += 7

        y = y + card_h + 6

    # ── COST SUMMARY ────────────────────────────────────────────────
    if y + 40 > 275:
        pdf.add_page()
        y = 14

    pdf.set_xy(14, y)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*ORANGE)
    pdf.cell(0, 8, "Cost Estimate", ln=True)
    y += 9

    cost_items = [
        ("Fuel", f"Rs {fuel_cost:,}"),
        ("Hotels", f"Rs {hotel_cost:,}"),
        ("Total", f"Rs {fuel_cost + hotel_cost:,}"),
    ]
    cw = 60
    for i, (lbl, val) in enumerate(cost_items):
        cx = 14 + i * (cw + 4)
        pdf.set_fill_color(*LIGHT)
        pdf.rect(cx, y, cw, 20, "F")
        pdf.set_text_color(*ORANGE)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_xy(cx, y + 2)
        pdf.cell(cw, 8, val, align="C", ln=False)
        pdf.set_xy(cx, y + 11)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*MUTED)
        pdf.cell(cw, 5, lbl, align="C", ln=False)
    y += 26

    # ── SAFETY BANNER ───────────────────────────────────────────────
    if y + 14 > 275:
        pdf.add_page()
        y = 14
    pdf.set_fill_color(*ORANGE)
    pdf.rect(12, y, 186, 13, "F")
    pdf.set_xy(12, y + 2)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*WHITE)
    pdf.cell(186, 9, "ATGATT: All The Gear, All The Time. Helmet  Jacket  Gloves  Boots  Riding Pants  Every ride.", align="C")
    y += 18

    # ── FOOTER ──────────────────────────────────────────────────────
    pdf.set_xy(14, y)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 6, f"Generated by Moto Bhai India  |  motobhai-india.web.app  |  {gen_date}  |  Trip ID: {trip_id}", align="C")

    return bytes(pdf.output())


@router.get("/api/plan/{trip_id}/pdf")
def download_pdf(trip_id: str):
    doc = firestore_client.load_trip(trip_id)
    if not doc:
        raise HTTPException(status_code=404, detail="trip not found")
    doc = _sanitize(doc)

    try:
        pdf_bytes = build_pdf(doc)
    except Exception as exc:
        log.exception("PDF build failed for %s", trip_id)
        raise HTTPException(status_code=500, detail=f"pdf generation failed: {exc}") from exc

    summary = doc.get("summary") or {}
    from_city = (summary.get("from") or "trip").replace(" ", "_")
    to_city   = (summary.get("to") or "").replace(" ", "_")
    filename  = f"motobhai_{from_city}_{to_city}_{trip_id}.pdf"

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
