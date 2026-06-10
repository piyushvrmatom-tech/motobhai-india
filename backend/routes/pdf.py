"""GET /api/plan/{trip_id}/pdf — timetable-style PDF using fpdf2.

Produces a professional itinerary document with:
- Branded header with trip title
- Trip summary info table
- Per-day timetable (Time | Activity | Location) with orange headers
- Hotel/stay info per day
- Cost summary and safety banner

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

# ── Color palette ─────────────────────────────────────────────────────────────
ORANGE      = (232, 117, 26)     # Brand orange
DARK_ORANGE = (200, 95, 15)      # Darker accent
DARK        = (30, 30, 30)       # Near-black text
MUTED       = (110, 110, 110)    # Secondary text
WHITE       = (255, 255, 255)
LIGHT_BG    = (250, 246, 240)    # Warm off-white
ROW_ALT     = (255, 250, 245)    # Alternating row
HEADER_BG   = (245, 130, 32)    # Table header (warm orange)
HEADER_TXT  = (255, 255, 255)    # Table header text
BORDER_GRAY = (220, 215, 210)    # Table borders
WARN_BG     = (255, 248, 225)    # Warning background
WARN_BORDER = (255, 193, 7)      # Warning accent
SAFETY_BG   = (26, 26, 26)      # Safety banner dark


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


def _safe(text, maxlen: int = 200) -> str:
    """Strip non-latin chars fpdf2 can't render; truncate."""
    out = ""
    for ch in str(text or ""):
        if ord(ch) < 256:
            out += ch
        else:
            out += "?"
    return out[:maxlen]


def _build_schedule(day: dict) -> list[tuple[str, str, str]]:
    """Build a (Time, Activity, Location) schedule from day data.

    Estimates realistic times based on riding hours, stops, etc.
    """
    rows: list[tuple[str, str, str]] = []

    from_d = _safe(day.get("from") or day.get("origin", ""))
    to_d = _safe(day.get("to") or day.get("destination", ""))
    km = day.get("km", 0)
    hrs = day.get("eta_hours", 0) or 0
    fuel_stops = day.get("fuel_stops", [])
    food_stops = day.get("food_stops", [])
    hotel = day.get("hotel_suggestion") or {}
    tip = _safe(day.get("bhai_tip", ""))

    # Morning prep
    rows.append(("06:00", "Wake up, final bike check & gear up.", from_d))
    rows.append(("06:30", "Light breakfast at a local dhaba.", from_d))
    rows.append(("07:00", f"Flag off towards {to_d}.", from_d))

    # Distribute fuel + food stops across the ride
    hour_cursor = 7.0  # Start at 07:00
    total_stops = []

    # Add fuel stops
    for f in fuel_stops:
        fname = _safe(f.get("name", "Fuel station"))
        fkm = f.get("km_from_start", 0)
        # Estimate time based on km proportion
        if km > 0 and fkm > 0:
            ratio = fkm / km
            stop_hour = 7.0 + ratio * hrs
        else:
            stop_hour = hour_cursor + 1.5
        total_stops.append((stop_hour, f"Fuel stop & quick refreshment.", fname))

    # Add food stops
    for i, food in enumerate(food_stops):
        food_name = _safe(food if isinstance(food, str) else food.get("name", ""))
        if i == 0 and hrs > 3:
            # First food stop as mid-morning/lunch break
            stop_hour = 7.0 + hrs * 0.45
            total_stops.append((stop_hour, "Lunch/Brunch break.", food_name))
        elif i == 1 and hrs > 5:
            stop_hour = 7.0 + hrs * 0.7
            total_stops.append((stop_hour, "Tea break & light snack.", food_name))

    # Sort by time and add to rows
    total_stops.sort(key=lambda x: x[0])
    for stop_hour, activity, location in total_stops:
        h = int(stop_hour)
        m = int((stop_hour - h) * 60)
        m = (m // 30) * 30  # Round to nearest 30 min
        time_str = f"{h:02d}:{m:02d}"
        rows.append((time_str, activity, location))

    # Resume ride after stops
    if total_stops:
        last_stop_hour = total_stops[-1][0] + 0.5
        h = int(last_stop_hour)
        m = int((last_stop_hour - h) * 60)
        m = (m // 30) * 30
        rows.append((f"{h:02d}:{m:02d}", f"Resume ride towards {to_d}.", ""))

    # Arrival
    arrival_hour = 7.0 + hrs + len(total_stops) * 0.5  # Add 30min per stop
    if arrival_hour > 20:
        arrival_hour = 19.0
    h = int(arrival_hour)
    rows.append((f"{h:02d}:00", f"Arrive in {to_d}, check into hotel.", to_d))

    # Evening
    dinner_hour = max(h + 1, 19)
    if dinner_hour <= 21:
        hotel_name = _safe(hotel.get("name", "the hotel"))
        rows.append((f"{dinner_hour:02d}:00", "Dinner at the hotel or a local restaurant.", hotel_name))

    return rows


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
    fuel_cost = summary.get("est_fuel_cost_inr", 0)
    hotel_cost = summary.get("est_hotel_cost_inr", 0)
    gen_date  = datetime.now(tz=timezone.utc).strftime("%d %b %Y")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    # ── PAGE 1: COVER ─────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_margins(14, 12, 14)

    # Brand name
    pdf.set_y(18)
    pdf.set_font("Helvetica", "BI", 28)
    pdf.set_text_color(*ORANGE)
    pdf.cell(0, 14, "Moto Bhai India", ln=True, align="C")

    # Trip title
    pdf.set_y(36)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*DARK)
    title = f"{from_city} to {to_city}"
    if total_days > 1:
        title = f"{total_days}-Day Ride: {title}"
    pdf.cell(0, 10, _safe(title), ln=True, align="C")

    # Thin orange line
    pdf.set_y(50)
    pdf.set_draw_color(*ORANGE)
    pdf.set_line_width(0.8)
    pdf.line(14, 50, 196, 50)

    # ── TRIP INFO TABLE ───────────────────────────────────────────────
    y = 56
    pdf.set_y(y)
    info_rows = [
        ("Origin", from_city, "Destination", to_city),
        ("Motorcycle", _safe(bike_label), "Distance", f"{total_km} km"),
        ("Budget", doc.get("budget_tier", "standard").title(), "Days", str(total_days)),
        ("Fuel Cost", f"Rs {fuel_cost:,}", "Hotel Cost", f"Rs {hotel_cost:,}"),
    ]
    col_w = [35, 55, 35, 55]  # label, value, label, value

    pdf.set_draw_color(*BORDER_GRAY)
    pdf.set_line_width(0.3)

    for row in info_rows:
        x = 15
        for i, cell in enumerate(row):
            pdf.set_xy(x, y)
            if i % 2 == 0:  # Label
                pdf.set_font("Helvetica", "B", 9)
                pdf.set_text_color(*DARK)
                pdf.set_fill_color(*LIGHT_BG)
                pdf.cell(col_w[i], 8, f" {cell}", border=1, fill=True)
            else:  # Value
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(60, 60, 60)
                pdf.cell(col_w[i], 8, f" {cell}", border=1)
            x += col_w[i]
        y += 8

    # ── ROUTE WARNINGS ────────────────────────────────────────────────
    y += 6
    if warnings:
        pdf.set_xy(14, y)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*DARK_ORANGE)
        pdf.cell(0, 6, "Route Notes:", ln=True)
        y += 7
        for w_txt in warnings[:4]:
            pdf.set_xy(16, y)
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(*MUTED)
            pdf.cell(0, 5, f"  - {_safe(w_txt, 120)}", ln=True)
            y += 5.5
        y += 4

    # ── DAY-BY-DAY ITINERARY ──────────────────────────────────────────
    for day in days:
        from_d  = _safe(day.get("from") or day.get("origin", ""))
        to_d    = _safe(day.get("to") or day.get("destination", ""))
        km_d    = day.get("km", 0)
        day_n   = day.get("day", "?")
        tip     = _safe(day.get("bhai_tip", ""))
        hotel   = day.get("hotel_suggestion") or {}
        schedule = _build_schedule(day)

        # Estimate card height
        schedule_h = 9 + len(schedule) * 7 + 12 + (8 if tip else 0)
        if y + schedule_h + 30 > 275:
            pdf.add_page()
            y = 14

        # Day heading
        pdf.set_xy(14, y)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(*ORANGE)
        day_title = f"Day {day_n}: {from_d} -> {to_d}"
        pdf.cell(0, 8, _safe(day_title), ln=True)
        y += 9

        # Route subtitle
        pdf.set_xy(14, y)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 5, f"{from_d} -> {to_d} | {km_d} km", ln=True)
        y += 7

        # Schedule table header
        time_w = 18
        activity_w = 108
        location_w = 56

        pdf.set_xy(14, y)
        pdf.set_fill_color(*HEADER_BG)
        pdf.set_text_color(*HEADER_TXT)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_draw_color(*HEADER_BG)
        pdf.cell(time_w, 7, " Time", border=1, fill=True)
        pdf.cell(activity_w, 7, " Activity", border=1, fill=True)
        pdf.cell(location_w, 7, " Location", border=1, fill=True)
        y += 7

        # Schedule rows
        for idx, (time_str, activity, location) in enumerate(schedule):
            if y + 7 > 275:
                pdf.add_page()
                y = 14
                # Re-draw header on new page
                pdf.set_xy(14, y)
                pdf.set_fill_color(*HEADER_BG)
                pdf.set_text_color(*HEADER_TXT)
                pdf.set_font("Helvetica", "B", 8)
                pdf.set_draw_color(*HEADER_BG)
                pdf.cell(time_w, 7, " Time", border=1, fill=True)
                pdf.cell(activity_w, 7, " Activity", border=1, fill=True)
                pdf.cell(location_w, 7, " Location", border=1, fill=True)
                y += 7

            pdf.set_xy(14, y)
            if idx % 2 == 1:
                pdf.set_fill_color(*ROW_ALT)
            else:
                pdf.set_fill_color(*WHITE)
            pdf.set_text_color(*DARK)
            pdf.set_font("Helvetica", "", 8)
            pdf.set_draw_color(*BORDER_GRAY)
            pdf.cell(time_w, 7, f" {time_str}", border=1, fill=True, align="C")
            pdf.cell(activity_w, 7, f" {_safe(activity, 85)}", border=1, fill=True)
            pdf.set_font("Helvetica", "", 7.5)
            pdf.set_text_color(80, 80, 80)
            pdf.cell(location_w, 7, f" {_safe(location, 45)}", border=1, fill=True)
            y += 7

        # Stay info
        y += 3
        if hotel.get("name"):
            pdf.set_xy(14, y)
            pdf.set_font("Helvetica", "B", 8.5)
            pdf.set_text_color(*DARK)
            price = hotel.get("price_range_inr", "")
            stay_text = f"Stay: {_safe(hotel['name'])}"
            if hotel.get("area"):
                stay_text += f", {_safe(hotel['area'])}"
            if price:
                stay_text += f" ~ Rs {price}"
            pdf.cell(0, 6, stay_text, ln=True)
            y += 7

        # Bhai tip
        if tip:
            pdf.set_xy(14, y)
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(140, 90, 20)
            pdf.cell(0, 5, f"Bhai Tip: {tip[:130]}", ln=True)
            y += 7

        y += 6

    # ── COST SUMMARY ──────────────────────────────────────────────────
    if y + 35 > 275:
        pdf.add_page()
        y = 14

    pdf.set_xy(14, y)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*ORANGE)
    pdf.cell(0, 8, "Trip Cost Summary", ln=True)
    y += 10

    pdf.set_draw_color(*BORDER_GRAY)
    cost_items = [
        ("Fuel Estimate", f"Rs {fuel_cost:,}"),
        ("Hotel Estimate", f"Rs {hotel_cost:,}"),
        ("Total Estimate", f"Rs {fuel_cost + hotel_cost:,}"),
    ]
    for i, (lbl, val) in enumerate(cost_items):
        pdf.set_xy(14, y)
        bg = LIGHT_BG if i < 2 else ORANGE
        txt = DARK if i < 2 else WHITE
        pdf.set_fill_color(*bg)
        pdf.set_text_color(*txt)
        pdf.set_font("Helvetica", "B" if i == 2 else "", 9)
        pdf.cell(90, 8, f"  {lbl}", border=1, fill=True)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(90, 8, f"  {val}", border=1, fill=True, align="R")
        y += 8

    # ── SAFETY BANNER ─────────────────────────────────────────────────
    y += 8
    if y + 14 > 275:
        pdf.add_page()
        y = 14
    pdf.set_fill_color(*SAFETY_BG)
    pdf.rect(12, y, 186, 13, "F")
    pdf.set_xy(12, y + 2)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(*WHITE)
    pdf.cell(186, 9, "ATGATT: All The Gear, All The Time.  Helmet | Jacket | Gloves | Boots | Riding Pants | Every ride.", align="C")
    y += 18

    # ── FOOTER ────────────────────────────────────────────────────────
    pdf.set_xy(14, y)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 6, f"Generated by Moto Bhai India & curated by Piyush Verma  |  motobhai.app  |  {gen_date}  |  {trip_id}", align="C")

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
