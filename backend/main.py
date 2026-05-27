"""Moto Bhai India - Route Engine (FastAPI) v2.0.0 - Production Itinerary Creator
With Firestore location intelligence, weekly data integration, and premium PDF generation.
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
import googlemaps
import google.generativeai as genai
import os, json, math, re, io, requests, hashlib
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, Color
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, Image as RLImage, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.graphics import renderPDF

try:
    from google.cloud import firestore
    FIRESTORE_AVAILABLE = True
except ImportError:
    FIRESTORE_AVAILABLE = False

# ─── App Setup ───────────────────────────────────────────────────────────────
app = FastAPI(title="Moto Bhai India - Route Engine", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── API Keys & Clients ─────────────────────────────────────────────────────
GMAPS_API_KEY = os.getenv("GMAPS_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OWM_API_KEY = os.getenv("OWM_API_KEY", "")
gmaps = googlemaps.Client(key=GMAPS_API_KEY) if GMAPS_API_KEY else None
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
GEMINI_MODEL = "gemini-2.5-flash"

# ─── Firestore Client ────────────────────────────────────────────────────────
db = None
if FIRESTORE_AVAILABLE:
    try:
        db = firestore.Client()
    except Exception:
        db = None

# ─── Constants ───────────────────────────────────────────────────────────────
PETROL = 105
BUDGET_MAP = {"economy": 1200, "standard": 2800, "premium": 6000, "luxury": 12000}
NEARBY_RADIUS_KM = 50

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
    "Rain Suit": "https://www.amazon.in/s?k=motorcycle+rain+suit+waterproof",
    "Bungee Net": "https://www.amazon.in/s?k=motorcycle+bungee+net+cargo"
}

# ─── Pydantic Models ─────────────────────────────────────────────────────────
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

class LocationIntelData(BaseModel):
    location_name: str
    state: str = ""
    lat: float = 0.0
    lng: float = 0.0
    popular_rides: List[Dict] = Field(default_factory=list)
    seasonal_events: List[Dict] = Field(default_factory=list)
    sightseeing: List[Dict] = Field(default_factory=list)
    things_to_do: List[Dict] = Field(default_factory=list)
    best_season: str = ""
    road_conditions: str = ""
    fuel_stations: List[str] = Field(default_factory=list)
    collected_at: str = ""
    source: str = "google_apps_script"

# ─── Firestore Helpers ───────────────────────────────────────────────────────
def _location_key(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', name.strip().lower())

def _haversine(lat1, lng1, lat2, lng2) -> float:
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def _get_location_coords(place: str) -> dict:
    if not gmaps:
        return {}
    try:
        geo = gmaps.geocode(place + ", India")
        if geo:
            loc = geo[0]["geometry"]["location"]
            return {"lat": loc["lat"], "lng": loc["lng"], "formatted": geo[0].get("formatted_address", "")}
    except Exception:
        pass
    return {}

def _store_location_intel(data: dict):
    if not db:
        return False
    try:
        key = _location_key(data.get("location_name", ""))
        if not key:
            return False
        data["updated_at"] = datetime.utcnow().isoformat()
        db.collection("location_intel").document(key).set(data, merge=True)
        return True
    except Exception:
        return False

def _get_location_intel(place: str) -> dict:
    if not db:
        return {}
    try:
        key = _location_key(place)
        doc = db.collection("location_intel").document(key).get()
        if doc.exists:
            return doc.to_dict()
    except Exception:
        pass
    return {}

def _find_nearby_intel(lat: float, lng: float, radius_km: float = 50) -> List[dict]:
    if not db:
        return []
    try:
        docs = db.collection("location_intel").stream()
        nearby = []
        for doc in docs:
            d = doc.to_dict()
            dlat = d.get("lat", 0)
            dlng = d.get("lng", 0)
            if dlat and dlng:
                dist = _haversine(lat, lng, dlat, dlng)
                if dist <= radius_km:
                    d["distance_km"] = round(dist, 1)
                    nearby.append(d)
        nearby.sort(key=lambda x: x.get("distance_km", 999))
        return nearby[:10]
    except Exception:
        return []

# ─── Core Utility Functions ──────────────────────────────────────────────────
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

def _get_weather_data(place: str) -> dict:
    if not OWM_API_KEY:
        return {"season": "unknown", "temp_c": None}
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={place},IN&appid={OWM_API_KEY}&units=metric"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            temp = data["main"]["temp"]
            desc = data["weather"][0]["main"].lower()
            season = "pleasant"
            if temp > 30:
                season = "summer"
            elif temp < 15:
                season = "winter"
            if "rain" in desc or "drizzle" in desc:
                season = "monsoon"
            return {"season": season, "temp_c": temp, "description": data["weather"][0]["description"], "humidity": data["main"]["humidity"]}
    except Exception:
        pass
    return {"season": "unknown", "temp_c": None}

def _enrich_with_local_intel(places: List[str]) -> dict:
    intel = {}
    for place in places:
        data = _get_location_intel(place)
        if data:
            intel[place] = data
        else:
            coords = _get_location_coords(place)
            if coords.get("lat"):
                nearby = _find_nearby_intel(coords["lat"], coords["lng"], NEARBY_RADIUS_KM)
                if nearby:
                    intel[place] = {"nearby_data": nearby, "note": f"No exact data for {place}, showing nearby locations"}
    return intel

# ─── API Endpoints ──────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "service": "Moto Bhai India - Route Engine",
        "version": "2.0.0",
        "gmaps_enabled": bool(GMAPS_API_KEY),
        "gemini_enabled": bool(GEMINI_API_KEY),
        "weather_enabled": bool(OWM_API_KEY),
        "firestore_enabled": db is not None
    }

@app.get("/api/motorcycles")
def get_motorcycles():
    return {"motorcycles": MOTORCYCLES}

@app.get("/api/gear")
def get_gear():
    return {"gear_links": GEAR_LINKS, "safety_message": "ATGATT - All The Gear, All The Time."}

@app.get("/api/place-info")
def place_info(q: str):
    result = {"place": q, "wikipedia": None, "location": None, "local_intel": None}
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
    intel = _get_location_intel(q)
    if intel:
        result["local_intel"] = intel
    return result

@app.get("/api/weather")
def get_weather(place: str):
    checklist = {"always": ["Full-face helmet (ISI/ECE)", "Riding jacket with CE armor", "Riding gloves", "Riding boots", "Riding pants (kevlar/CE)", "First aid kit", "Tool kit", "Documents (DL, RC, Insurance)"], "seasonal": [], "season": "unknown"}
    weather = _get_weather_data(place)
    checklist["season"] = weather["season"]
    checklist["temp_c"] = weather.get("temp_c")
    checklist["description"] = weather.get("description", "")
    if weather["season"] == "summer":
        checklist["seasonal"] = ["Dry-fit T-shirts", "Sunscreen SPF 50+", "Hydration pack (3L)", "UV arm sleeves", "Cooling towel", "Electrolyte sachets", "Mesh jacket preferred"]
    elif weather["season"] == "winter":
        checklist["seasonal"] = ["Fleece jacket / thermal inner", "Balaclava / neck warmer", "Thermal gloves", "Woollen socks", "Hot water flask", "Fog-free visor"]
    elif weather["season"] == "monsoon":
        checklist["seasonal"] = ["Full rain suit", "Waterproof boot covers", "Anti-fog visor spray", "Dry bags for luggage", "Waterproof phone pouch"]
    else:
        checklist["seasonal"] = ["Light layers", "Rain liner (just in case)", "Arm sleeves"]
    return checklist

# ─── Location Intel Ingestion (from Google Apps Script) ──────────────────
@app.post("/api/location-intel/ingest")
def ingest_location_intel(data: LocationIntelData):
    payload = data.dict()
    if not payload.get("lat") or not payload.get("lng"):
        coords = _get_location_coords(data.location_name)
        if coords:
            payload["lat"] = coords["lat"]
            payload["lng"] = coords["lng"]
    payload["collected_at"] = payload.get("collected_at") or datetime.utcnow().isoformat()
    success = _store_location_intel(payload)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to store location intel")
    return {"status": "stored", "location": data.location_name, "key": _location_key(data.location_name)}

@app.post("/api/location-intel/bulk-ingest")
def bulk_ingest(locations: List[LocationIntelData]):
    results = []
    for loc in locations:
        try:
            r = ingest_location_intel(loc)
            results.append(r)
        except Exception as e:
            results.append({"status": "error", "location": loc.location_name, "error": str(e)})
    return {"ingested": len([r for r in results if r.get("status") == "stored"]), "total": len(locations), "results": results}

@app.get("/api/location-intel")
def get_location_intel_api(place: str, radius_km: float = 50):
    intel = _get_location_intel(place)
    if intel:
        return {"source": "exact", "data": intel}
    coords = _get_location_coords(place)
    if coords.get("lat"):
        nearby = _find_nearby_intel(coords["lat"], coords["lng"], radius_km)
        if nearby:
            return {"source": "nearby", "data": nearby}
    return {"source": "none", "data": {}}

# ─── Itinerary Generation (Enhanced with Location Intel) ────────────────
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
    weather_origin = _get_weather_data(req.origin)
    weather_dest = _get_weather_data(req.destination)
    local_intel = _enrich_with_local_intel(list(set(all_points)))
    intel_context = ""
    for place, data in local_intel.items():
        if isinstance(data, dict) and "nearby_data" not in data:
            rides = data.get("popular_rides", [])
            events = data.get("seasonal_events", [])
            sights = data.get("sightseeing", [])
            todos = data.get("things_to_do", [])
            intel_context += f"\nLocal intel for {place}:"
            if rides:
                intel_context += f"\n  Popular rides: {json.dumps(rides[:3])}"
            if events:
                intel_context += f"\n  Seasonal events: {json.dumps(events[:3])}"
            if sights:
                intel_context += f"\n  Sightseeing: {json.dumps(sights[:5])}"
            if todos:
                intel_context += f"\n  Things to do: {json.dumps(todos[:5])}"
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
- Origin weather: {weather_origin.get('season', 'unknown')}, {weather_origin.get('temp_c', 'N/A')}C
- Destination weather: {weather_dest.get('season', 'unknown')}, {weather_dest.get('temp_c', 'N/A')}C
{intel_context}

Return ONLY valid JSON (no markdown) with this structure:
{{
  "trip_name": "...",
  "total_distance_km": {distance:.0f},
  "total_days": {req.days},
  "season_advisory": "...",
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
      "highlights": ["..."],
      "local_events": ["..."],
      "road_condition": "..."
    }}
  ],
  "sightseeing_summary": [{{"place": "...", "description": "...", "best_time": "..."}}],
  "tips": ["..."],
  "emergency_numbers": {{"highway_patrol": "1033", "ambulance": "108", "police": "100"}},
  "estimated_budget": {{"fuel": {fuel['cost_inr']}, "stay": {budget_per_day * req.days}, "food": {budget_per_day * req.days // 2}, "misc": {budget_per_day * req.days // 4}, "total": 0}}
}}

Fill total = fuel + stay + food + misc. Be specific with real place names, real dhaba/hotel names, real fuel stations. Include hour-by-hour schedule."""
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
        "weather": {"origin": weather_origin, "destination": weather_dest},
        "local_intel": local_intel,
        "itinerary": itinerary,
        "gear_links": GEAR_LINKS,
        "generated_at": datetime.utcnow().isoformat()
    }

# ─── Premium PDF Generation ─────────────────────────────────────────────────
def _build_pdf_styles():
    styles = getSampleStyleSheet()
    orange = HexColor('#E8751A')
    dark = HexColor('#1A1A2E')
    return {
        'title': ParagraphStyle('TripTitle', parent=styles['Title'], textColor=orange, fontSize=24, spaceAfter=6, fontName='Helvetica-Bold'),
        'subtitle': ParagraphStyle('SubTitle', parent=styles['Heading2'], textColor=dark, fontSize=14, spaceAfter=4),
        'h2': ParagraphStyle('H2', parent=styles['Heading2'], textColor=orange, fontSize=13, spaceAfter=4, spaceBefore=8),
        'h3': ParagraphStyle('H3', parent=styles['Heading3'], textColor=dark, fontSize=11, spaceAfter=3),
        'body': styles['BodyText'],
        'small': ParagraphStyle('Small', parent=styles['BodyText'], fontSize=8, textColor=HexColor('#666')),
        'footer': ParagraphStyle('Footer', parent=styles['BodyText'], fontSize=7, textColor=HexColor('#999'), alignment=TA_CENTER),
        'orange': orange,
        'dark': dark,
    }

def _add_header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(HexColor('#E8751A'))
    canvas.rect(0, A4[1]-8*mm, A4[0], 8*mm, fill=1, stroke=0)
    canvas.setFillColor(HexColor('#FFFFFF'))
    canvas.setFont('Helvetica-Bold', 9)
    canvas.drawString(15*mm, A4[1]-6*mm, 'MOTO BHAI INDIA')
    canvas.drawRightString(A4[0]-15*mm, A4[1]-6*mm, 'motobhai-india.web.app')
    canvas.setFillColor(HexColor('#999999'))
    canvas.setFont('Helvetica', 7)
    canvas.drawCentredString(A4[0]/2, 8*mm, f'Generated on {datetime.utcnow().strftime("%d %b %Y")} | Page {doc.page}')
    canvas.restoreState()

@app.post("/api/itinerary/pdf")
def itinerary_pdf(req: TripRequest):
    data = generate_itinerary(req)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18*mm, bottomMargin=15*mm, leftMargin=15*mm, rightMargin=15*mm)
    s = _build_pdf_styles()
    elements = []
    elements.append(Spacer(1, 4*mm))
    elements.append(Paragraph("MOTO BHAI INDIA", s['title']))
    elements.append(Paragraph(data.get('trip_name', 'Trip Itinerary'), s['subtitle']))
    elements.append(HRFlowable(width="100%", thickness=2, color=s['orange'], spaceAfter=4*mm))
    info_data = [
        ["Origin", data['origin'], "Destination", data['destination']],
        ["Motorcycle", data['motorcycle'], "Mileage", f"{data['mileage_kmpl']} kmpl"],
        ["Budget", data['budget_tier'].title(), "Distance", f"{data['fuel']['distance_km']} km"],
        ["Fuel Cost", f"Rs {data['fuel']['cost_inr']}", "Fuel Needed", f"{data['fuel']['litres']} L"]
    ]
    t = Table(info_data, colWidths=[75, 145, 75, 145])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), HexColor('#FFF3E8')),
        ('BACKGROUND', (2,0), (2,-1), HexColor('#FFF3E8')),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), 0.5, HexColor('#DDD')),
        ('PADDING', (0,0), (-1,-1), 5),
        ('FONTSIZE', (0,0), (-1,-1), 9)
    ]))
    elements.append(t)
    elements.append(Spacer(1, 4*mm))
    w = data.get('weather', {})
    wo = w.get('origin', {})
    wd = w.get('destination', {})
    if wo.get('season') or wd.get('season'):
        elements.append(Paragraph("Weather & Season", s['h2']))
        weather_text = f"Origin ({data['origin']}): {wo.get('season', 'N/A').title()}"
        if wo.get('temp_c'):
            weather_text += f" ({wo['temp_c']}\u00b0C)"
        weather_text += f" | Destination ({data['destination']}): {wd.get('season', 'N/A').title()}"
        if wd.get('temp_c'):
            weather_text += f" ({wd['temp_c']}\u00b0C)"
        elements.append(Paragraph(weather_text, s['body']))
        advisory = data.get('itinerary', {}).get('season_advisory', '')
        if advisory:
            elements.append(Paragraph(f"<i>Advisory: {advisory}</i>", s['small']))
        elements.append(Spacer(1, 3*mm))
    itin = data.get('itinerary', {})
    days = itin.get('days', [])
    for day in days:
        day_elements = []
        day_elements.append(Paragraph(f"DAY {day.get('day', '?')}: {day.get('title', '')}", s['h2']))
        day_elements.append(Paragraph(f"{day.get('from', '')} \u2192 {day.get('to', '')} | {day.get('distance_km', 0)} km", s['body']))
        rc = day.get('road_condition', '')
        if rc:
            day_elements.append(Paragraph(f"Road: {rc}", s['small']))
        schedule = day.get('schedule', [])
        if schedule:
            sched_data = [["Time", "Activity", "Location"]]
            for sc in schedule:
                sched_data.append([sc.get('time', ''), sc.get('activity', ''), sc.get('location', '')])
            st = Table(sched_data, colWidths=[45, 225, 160])
            st.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), s['orange']),
                ('TEXTCOLOR', (0,0), (-1,0), HexColor('#FFF')),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('GRID', (0,0), (-1,-1), 0.5, HexColor('#DDD')),
                ('FONTSIZE', (0,0), (-1,-1), 8),
                ('PADDING', (0,0), (-1,-1), 3),
                ('VALIGN', (0,0), (-1,-1), 'TOP')
            ]))
            day_elements.append(st)
        stay = day.get('stay', {})
        if stay:
            day_elements.append(Paragraph(f"Stay: {stay.get('name', 'N/A')} ({stay.get('type', '')}) ~ Rs {stay.get('cost_approx', 0)}", s['body']))
        meals = day.get('meals', [])
        if meals:
            meal_text = " | ".join([f"{m.get('type','').title()}: {m.get('place','')} (Rs {m.get('cost_approx',0)})" for m in meals])
            day_elements.append(Paragraph(f"Meals: {meal_text}", s['small']))
        highlights = day.get('highlights', [])
        if highlights:
            day_elements.append(Paragraph(f"Highlights: {', '.join(highlights)}", s['body']))
        events = day.get('local_events', [])
        if events and events != ['']:
            day_elements.append(Paragraph(f"Local Events: {', '.join(events)}", s['small']))
        day_elements.append(Spacer(1, 3*mm))
        elements.append(KeepTogether(day_elements))
    sights = itin.get('sightseeing_summary', [])
    if sights:
        elements.append(Paragraph("Sightseeing Guide", s['h2']))
        for sight in sights:
            elements.append(Paragraph(f"<b>{sight.get('place', '')}</b>: {sight.get('description', '')} (Best: {sight.get('best_time', 'anytime')})", s['body']))
    local_intel = data.get('local_intel', {})
    if local_intel:
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph("Local Intelligence (Weekly Updated)", s['h2']))
        for place, intel_data in local_intel.items():
            if isinstance(intel_data, dict) and 'nearby_data' not in intel_data:
                rides = intel_data.get('popular_rides', [])
                if rides:
                    ride_names = ', '.join([r.get('name', r) if isinstance(r, dict) else str(r) for r in rides[:3]])
                    elements.append(Paragraph(f"{place} - Popular Rides: {ride_names}", s['body']))
                events = intel_data.get('seasonal_events', [])
                if events:
                    ev_names = ', '.join([e.get('name', e) if isinstance(e, dict) else str(e) for e in events[:3]])
                    elements.append(Paragraph(f"{place} - Events: {ev_names}", s['small']))
    budget = itin.get('estimated_budget', {})
    if budget:
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph("Budget Breakdown", s['h2']))
        budget_data = [[k.title(), f"Rs {v}"] for k, v in budget.items()]
        bt = Table(budget_data, colWidths=[200, 200])
        bt.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, HexColor('#DDD')),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('PADDING', (0,0), (-1,-1), 4),
            ('BACKGROUND', (-1,-1), (-1,-1), HexColor('#FFF3E8')),
            ('FONTNAME', (-1,-1), (-1,-1), 'Helvetica-Bold')
        ]))
        elements.append(bt)
    tips = itin.get('tips', [])
    if tips:
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph("Tips & Safety", s['h2']))
        for tip in tips:
            elements.append(Paragraph(f"\u2022 {tip}", s['body']))
    emergency = itin.get('emergency_numbers', {})
    if emergency:
        elements.append(Spacer(1, 2*mm))
        elements.append(Paragraph("Emergency: " + " | ".join([f"{k}: {v}" for k, v in emergency.items()]), s['body']))
    elements.append(Spacer(1, 4*mm))
    elements.append(Paragraph(f"Google Maps: {data['maps_url']}", s['small']))
    elements.append(Spacer(1, 2*mm))
    elements.append(Paragraph("ATGATT - All The Gear, All The Time. Ride safe!", ParagraphStyle('Safety', parent=s['body'], textColor=s['orange'], fontName='Helvetica-Bold', fontSize=10, alignment=TA_CENTER)))
    doc.build(elements, onFirstPage=_add_header_footer, onLaterPages=_add_header_footer)
    buf.seek(0)
    filename = f"motobhai_{data['origin']}_{data['destination']}_{req.days}days.pdf".replace(' ', '_')
    return StreamingResponse(buf, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={filename}"})
