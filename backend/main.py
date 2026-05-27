"""Moto Bhai India - Route Engine (FastAPI) v1.0.0 - Full Trip Planner"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional
import googlemaps
import google.generativeai as genai
import os, json, math, re, io, requests
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT

app = FastAPI(title="Moto Bhai India - Route Engine", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

GMAPS_API_KEY = os.getenv("GMAPS_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OWM_API_KEY = os.getenv("OWM_API_KEY", "")
gmaps = googlemaps.Client(key=GMAPS_API_KEY) if GMAPS_API_KEY else None
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
GEMINI_MODEL = "gemini-2.5-flash"

PETROL = 105
BUDGET_MAP = {"economy": 1200, "standard": 2800, "premium": 6000, "luxury": 12000}

MOTORCYCLES = {
    "Royal Enfield Himalayan": {"cc": 411, "mileage": 30},
    "Royal Enfield Classic 350": {"cc": 350, "mileage": 35},
    "Royal Enfield Hunter 350": {"cc": 349, "mileage": 36},
    "KTM 390 Adventure": {"cc": 373, "mileage": 30},
    "KTM 250 Adventure": {"cc": 248, "mileage": 35},
    "Bajaj Dominar 400": {"cc": 373, "mileage": 28},
    "Hero Xpulse 200": {"cc": 199, "mileage": 40},
    "Jawa 42": {"cc": 294, "mileage": 33},
    "Honda CB350": {"cc": 348, "mileage": 35},
    "Suzuki V-Strom 250": {"cc": 248, "mileage": 35},
    "BMW G310 GS": {"cc": 313, "mileage": 30},
    "Kawasaki Versys 650": {"cc": 649, "mileage": 22},
    "Triumph Speed 400": {"cc": 398, "mileage": 30},
    "Yezdi Adventure": {"cc": 334, "mileage": 30},
    "Custom / Other": {"cc": 0, "mileage": 30}
}

GEAR_LINKS = {
    "Helmet (ISI/ECE)": "https://www.amazon.in/s?k=motorcycle+helmet+ISI+ECE",
    "Riding Jacket": "https://www.amazon.in/s?k=motorcycle+riding+jacket+CE+armor",
    "Riding Pants": "https://www.amazon.in/s?k=motorcycle+riding+pants+kevlar",
    "Riding Gloves": "https://www.amazon.in/s?k=motorcycle+riding+gloves",
    "Riding Boots": "https://www.amazon.in/s?k=motorcycle+riding+boots+ankle",
    "Hydration Pack": "https://www.amazon.in/s?k=hydration+backpack+motorcycle",
    "Action Camera": "https://www.amazon.in/s?k=action+camera+motorcycle+helmet+mount",
    "Bluetooth Intercom": "https://www.amazon.in/s?k=motorcycle+bluetooth+intercom",
    "Tank Bag": "https://www.amazon.in/s?k=motorcycle+tank+bag+magnetic",
    "Saddlebags": "https://www.amazon.in/s?k=motorcycle+saddlebags",
    "Phone Mount": "https://www.amazon.in/s?k=motorcycle+phone+mount+vibration+dampener",
    "USB Charger": "https://www.amazon.in/s?k=motorcycle+usb+charger+handlebar",
    "Crash Guard": "https://www.amazon.in/s?k=motorcycle+crash+guard+leg+guard",
    "Top Rack + Box": "https://www.amazon.in/s?k=motorcycle+top+rack+box",
    "Tyre Pressure Monitor": "https://www.amazon.in/s?k=motorcycle+tyre+pressure+monitor",
    "Rain Suit": "https://www.amazon.in/s?k=motorcycle+rain+suit+waterproof",
    "Bungee Net": "https://www.amazon.in/s?k=motorcycle+bungee+net+cargo"
}

class TripRequest(BaseModel):
    origin: str
    destination: str
    stops: List[str] = Field(default_factory=list)
    end_point: str = ""
    days: int = Field(default=3, ge=1, le=30)
    budget: str = Field(default="standard")
    motorcycle: str = Field(default="Royal Enfield Himalayan")
    mileage_override: Optional[float] = None
    fuel_price: float = Field(default=105)
    preferences: List[str] = Field(default_factory=lambda: ["scenic", "food", "culture"])
    trip_type: str = "round_trip"


@app.get("/")
def root():
    return {
        "service": "Moto Bhai India - Route Engine",
        "version": "1.0.0",
        "gmaps_enabled": bool(GMAPS_API_KEY),
        "gemini_enabled": bool(GEMINI_API_KEY),
        "weather_enabled": bool(OWM_API_KEY)
    }


@app.get("/api/motorcycles")
def get_motorcycles():
    return {"motorcycles": MOTORCYCLES}


@app.get("/api/gear")
def get_gear():
    return {"gear_links": GEAR_LINKS, "safety_message": "ATGATT - All The Gear, All The Time. Always wear full protective gear on every ride."}


@app.get("/api/place-info")
def place_info(q: str):
    result = {"place": q, "wikipedia": None, "location": None, "photos": []}
    if gmaps:
        try:
            geo = gmaps.geocode(q + ", India")
            if geo:
                loc = geo[0]["geometry"]["location"]
                result["location"] = loc
                result["formatted_address"] = geo[0].get("formatted_address", "")
        except Exception:
            pass
    try:
        wiki_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{q.replace(' ', '_')}"
        wr = requests.get(wiki_url, timeout=5)
        if wr.status_code == 200:
            wd = wr.json()
            result["wikipedia"] = {
                "title": wd.get("title", ""),
                "extract": wd.get("extract", ""),
                "thumbnail": wd.get("thumbnail", {}).get("source", ""),
                "page_url": wd.get("content_urls", {}).get("desktop", {}).get("page", "")
            }
    except Exception:
        pass
    return result


@app.get("/api/weather")
def get_weather(place: str):
    checklist = {"always": ["Full-face helmet (ISI/ECE)", "Riding jacket with CE armor", "Riding gloves", "Riding boots (ankle protection)", "Riding pants (kevlar/CE)", "First aid kit", "Tool kit", "Documents (DL, RC, Insurance)"], "seasonal": [], "season": "unknown"}
    if not OWM_API_KEY:
        checklist["note"] = "Weather API not configured - showing default summer checklist"
        checklist["seasonal"] = ["Dry-fit T-shirts", "Sunscreen SPF 50+", "Hydration pack", "UV arm sleeves", "Cooling towel", "Sunglasses"]
        checklist["season"] = "summer"
        return checklist
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={place},IN&appid={OWM_API_KEY}&units=metric"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            temp = data["main"]["temp"]
            desc = data["weather"][0]["main"].lower()
            checklist["temp_c"] = temp
            checklist["description"] = data["weather"][0]["description"]
            if temp > 30:
                checklist["season"] = "summer"
                checklist["seasonal"] = ["Dry-fit T-shirts", "Sunscreen SPF 50+", "Hydration pack (3L)", "UV arm sleeves", "Cooling towel", "Electrolyte sachets", "Light-colored gear", "Mesh jacket preferred"]
            elif temp < 15:
                checklist["season"] = "winter"
                checklist["seasonal"] = ["Fleece jacket / thermal inner", "Balaclava / neck warmer", "Heated grips (if available)", "Thermal gloves", "Woollen socks", "Hand warmers", "Hot water flask", "Fog-free visor"]
            else:
                checklist["season"] = "pleasant"
                checklist["seasonal"] = ["Light layers", "Rain liner (just in case)", "Arm sleeves"]
            if "rain" in desc or "drizzle" in desc:
                checklist["season"] = "monsoon"
                checklist["seasonal"].extend(["Full rain suit", "Waterproof boot covers", "Anti-fog visor spray", "Dry bags for luggage", "Waterproof phone pouch"])
    except Exception:
        checklist["seasonal"] = ["Dry-fit T-shirts", "Sunscreen SPF 50+", "Hydration pack"]
        checklist["season"] = "summer"
    return checklist


def _calc_fuel(distance_km: float, mileage: float, price: float):
    litres = distance_km / mileage
    cost = litres * price
    return {"distance_km": round(distance_km, 1), "litres": round(litres, 1), "cost_inr": round(cost)}


def _get_distance(origin: str, destination: str, waypoints: list = None):
    if not gmaps:
        return 0
    try:
        args = {"origin": origin, "destination": destination, "mode": "driving"}
        if waypoints:
            args["waypoints"] = waypoints
        result = gmaps.directions(**args)
        if result:
            total = sum(leg["distance"]["value"] for leg in result[0]["legs"])
            return total / 1000
    except Exception:
        pass
    return 0


def _maps_url(origin, destination, stops):
    base = "https://www.google.com/maps/dir/"
    parts = [origin] + stops + [destination]
    return base + "/".join(p.replace(" ", "+") for p in parts)


@app.post("/api/generate-itinerary")
def generate_itinerary(req: TripRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Gemini API key not configured")
    end = req.end_point or (req.origin if req.trip_type == "round_trip" else req.destination)
    all_points = [req.origin] + req.stops + [req.destination]
    if req.trip_type == "round_trip" and end == req.origin:
        all_points.append(req.origin)
    mileage = req.mileage_override or MOTORCYCLES.get(req.motorcycle, {}).get("mileage", 30)
    distance = _get_distance(req.origin, end, req.stops if req.stops else None)
    fuel = _calc_fuel(distance if distance else 500, mileage, req.fuel_price)
    budget_per_day = BUDGET_MAP.get(req.budget, 2800)
    maps_link = _maps_url(req.origin, req.destination, req.stops)
    prompt = f"""You are Moto Bhai, an expert motorcycle trip planner for India.
Plan a detailed {req.days}-day motorcycle trip:
- Origin: {req.origin}
- Destination: {req.destination}
- Stops: {', '.join(req.stops) if req.stops else 'None specified'}
- End point: {end}
- Motorcycle: {req.motorcycle} ({mileage} kmpl)
- Budget: {req.budget} (approx Rs {budget_per_day}/day for stay+food)
- Distance: ~{distance:.0f} km
- Preferences: {', '.join(req.preferences)}

Return ONLY valid JSON (no markdown) with this structure:
{{
  "trip_name": "...",
  "total_distance_km": {distance:.0f},
  "total_days": {req.days},
  "days": [
    {{
      "day": 1,
      "title": "Day title",
      "from": "...",
      "to": "...",
      "distance_km": 0,
      "schedule": [
        {{"time": "06:00", "activity": "...", "location": "...", "tip": "..."}}
      ],
      "stay": {{"name": "...", "type": "hotel/dhaba/camp", "cost_approx": 0}},
      "meals": [{{"type": "breakfast/lunch/dinner", "place": "...", "cuisine": "...", "cost_approx": 0}}],
      "fuel_stop": {{"location": "...", "km_from_start": 0}},
      "highlights": ["..."]
    }}
  ],
  "tips": ["..."],
  "emergency_numbers": {{"highway_patrol": "1033", "ambulance": "108", "police": "100"}},
  "estimated_budget": {{"fuel": {fuel['cost_inr']}, "stay": {budget_per_day * req.days}, "food": {budget_per_day * req.days // 2}, "misc": {budget_per_day * req.days // 4}, "total": 0}}
}}
Fill total = fuel + stay + food + misc. Be specific with real place names, real dhaba/hotel names, real fuel stations. Include hour-by-hour schedule for each day."""
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt)
        text = response.text.strip()
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        itinerary = json.loads(text)
    except json.JSONDecodeError:
        itinerary = {"raw_response": text, "parse_error": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "trip_name": itinerary.get("trip_name", f"{req.origin} to {req.destination}"),
        "origin": req.origin,
        "destination": req.destination,
        "stops": req.stops,
        "end_point": end,
        "motorcycle": req.motorcycle,
        "mileage_kmpl": mileage,
        "fuel": fuel,
        "budget_tier": req.budget,
        "maps_url": maps_link,
        "itinerary": itinerary,
        "gear_links": GEAR_LINKS
    }


@app.post("/api/itinerary/pdf")
def itinerary_pdf(req: TripRequest):
    data = generate_itinerary(req)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20*mm, bottomMargin=15*mm, leftMargin=15*mm, rightMargin=15*mm)
    styles = getSampleStyleSheet()
    orange = HexColor('#E8751A')
    title_style = ParagraphStyle('TripTitle', parent=styles['Title'], textColor=orange, fontSize=22, spaceAfter=12)
    h2 = ParagraphStyle('H2', parent=styles['Heading2'], textColor=orange, fontSize=14, spaceAfter=6)
    body = styles['BodyText']
    elements = []
    elements.append(Paragraph(f"Moto Bhai India", title_style))
    elements.append(Paragraph(f"{data.get('trip_name', 'Trip Itinerary')}", styles['Heading1']))
    elements.append(Spacer(1, 6*mm))
    info_data = [
        ["Origin", data['origin'], "Destination", data['destination']],
        ["Motorcycle", data['motorcycle'], "Mileage", f"{data['mileage_kmpl']} kmpl"],
        ["Budget", data['budget_tier'].title(), "Distance", f"{data['fuel']['distance_km']} km"],
        ["Fuel Cost", f"Rs {data['fuel']['cost_inr']}", "Fuel Litres", f"{data['fuel']['litres']} L"]
    ]
    t = Table(info_data, colWidths=[80, 140, 80, 140])
    t.setStyle(TableStyle([('BACKGROUND', (0,0), (0,-1), HexColor('#FFF3E8')), ('BACKGROUND', (2,0), (2,-1), HexColor('#FFF3E8')), ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'), ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'), ('GRID', (0,0), (-1,-1), 0.5, HexColor('#DDD')), ('PADDING', (0,0), (-1,-1), 6)]))
    elements.append(t)
    elements.append(Spacer(1, 6*mm))
    itin = data.get('itinerary', {})
    days = itin.get('days', [])
    for day in days:
        elements.append(Paragraph(f"Day {day.get('day', '?')}: {day.get('title', '')}", h2))
        elements.append(Paragraph(f"{day.get('from', '')} -> {day.get('to', '')} | {day.get('distance_km', 0)} km", body))
        schedule = day.get('schedule', [])
        if schedule:
            sched_data = [["Time", "Activity", "Location"]]
            for s in schedule:
                sched_data.append([s.get('time', ''), s.get('activity', ''), s.get('location', '')])
            st = Table(sched_data, colWidths=[50, 220, 160])
            st.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), orange), ('TEXTCOLOR', (0,0), (-1,0), HexColor('#FFF')), ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'), ('GRID', (0,0), (-1,-1), 0.5, HexColor('#DDD')), ('FONTSIZE', (0,0), (-1,-1), 8), ('PADDING', (0,0), (-1,-1), 4)]))
            elements.append(st)
        stay = day.get('stay', {})
        if stay:
            elements.append(Paragraph(f"Stay: {stay.get('name', 'N/A')} ({stay.get('type', '')}) ~ Rs {stay.get('cost_approx', 0)}", body))
        elements.append(Spacer(1, 4*mm))
    budget = itin.get('estimated_budget', {})
    if budget:
        elements.append(Paragraph("Estimated Budget", h2))
        for k, v in budget.items():
            elements.append(Paragraph(f"{k.title()}: Rs {v}", body))
    tips = itin.get('tips', [])
    if tips:
        elements.append(Spacer(1, 4*mm))
        elements.append(Paragraph("Tips & Tricks", h2))
        for tip in tips:
            elements.append(Paragraph(f"* {tip}", body))
    elements.append(Spacer(1, 6*mm))
    elements.append(Paragraph(f"Google Maps: {data['maps_url']}", body))
    elements.append(Paragraph("ATGATT - All The Gear, All The Time. Ride safe!", ParagraphStyle('Safety', parent=body, textColor=orange, fontName='Helvetica-Bold')))
    doc.build(elements)
    buf.seek(0)
    filename = f"motobhai_{data['origin']}_{data['destination']}_{req.days}days.pdf".replace(' ', '_')
    return StreamingResponse(buf, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={filename}"})
