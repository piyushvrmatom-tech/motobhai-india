"""Gemini 2.5 Flash wrapper — versioned prompt, JSON mode, single retry.

Supports BOTH the new `google-genai` SDK and the legacy `google-generativeai`
SDK. Tries the new SDK first; falls back to the old one if not installed.
This ensures the code works on Render regardless of cached pip packages.

Loads `prompts/itinerary_v3.txt` once at module import. Temperature 0.4 per
CTO §4.4. Output token cap 8192.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash"
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "itinerary_v3.txt"
PROMPT_TEXT = PROMPT_PATH.read_text(encoding="utf-8") if PROMPT_PATH.exists() else ""

# ── SDK detection ─────────────────────────────────────────────────────────────
# Try new SDK first, fall back to deprecated one.
_USE_NEW_SDK = False
_client = None  # google.genai.Client  (new SDK)
_model = None   # genai.GenerativeModel (old SDK)

try:
    from google import genai as _genai_new
    _USE_NEW_SDK = True
    log.info("Using google-genai (new SDK)")
except ImportError:
    _USE_NEW_SDK = False
    log.info("google-genai not found, trying legacy google-generativeai")

if not _USE_NEW_SDK:
    try:
        import google.generativeai as _genai_old
        log.info("Using google-generativeai (legacy SDK)")
    except ImportError:
        _genai_old = None  # type: ignore
        log.warning("No Gemini SDK available")


def _ensure_client():
    """Lazily create the SDK client/model."""
    global _client, _model
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if api_key.lower().startswith("mock"):
        return True

    if not api_key:
        log.error("GEMINI_API_KEY environment variable is not set.")
        return False

    if _USE_NEW_SDK:
        if _client is None:
            _client = _genai_new.Client(api_key=api_key)
        return True
    else:
        if _genai_old is None:
            return False
        if _model is None:
            _genai_old.configure(api_key=api_key)
            _model = _genai_old.GenerativeModel(
                MODEL_NAME,
                system_instruction=PROMPT_TEXT or None,
                generation_config={
                    "temperature": 0.4,
                    "max_output_tokens": 8192,
                    "response_mime_type": "application/json",
                },
            )
        return True


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _call_new_sdk(user_msg: str) -> str:
    """Call Gemini via the new google-genai SDK."""
    from google.genai import types
    config = types.GenerateContentConfig(
        system_instruction=PROMPT_TEXT,
        temperature=0.4,
        max_output_tokens=8192,
        response_mime_type="application/json",
    )
    resp = _client.models.generate_content(
        model=MODEL_NAME,
        contents=user_msg,
        config=config,
    )
    return resp.text or ""


def _call_old_sdk(user_msg: str) -> str:
    """Call Gemini via the legacy google-generativeai SDK."""
    resp = _model.generate_content(user_msg)
    return resp.text or ""


def generate_itinerary(
    *,
    origin: str,
    destination: str,
    days: int,
    legs: List[Dict[str, Any]],
    bike_label: str,
    vibe: str,
    budget_tier: str,
    season: str,
) -> Dict[str, Any]:
    """Call Gemini and return the parsed itinerary dict.

    Raises ``RuntimeError`` if Gemini is not configured or both attempts fail.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if api_key.lower().startswith("mock"):
        log.warning("GEMINI_API_KEY is missing or set to mock. Returning mock itinerary structure.")
        mock_days_plan = []
        for leg in legs:
            day_num = leg.get("day", 1)
            km = leg.get("km", 100.0)
            mock_days_plan.append({
                "day": day_num,
                "from": leg.get("from", origin),
                "to": leg.get("to", destination),
                "km": km,
                "eta_hours": round(km / 50.0, 1),
                "elevation_gain_m": 150,
                "fuel_stops": [
                    {"name": f"NH-44 Petrol Pump KM {int(km * 0.4)}", "km_from_start": round(km * 0.4, 1), "type": "petrol"}
                ],
                "hotel_suggestion": {
                    "name": f"Biker Haven Hotel Day {day_num}",
                    "area": leg.get("to", destination),
                    "price_range_inr": "₹2,500 - ₹4,500",
                    "google_place_id": f"place_hotel_day_{day_num}"
                },
                "food_stops": [f"Highway Dhaba KM {int(km * 0.25)}", f"Local Cafe KM {int(km * 0.75)}"],
                "bhai_tip": f"Ride carefully on Day {day_num}. Keep tire pressure checked for {bike_label}.",
                "warnings": []
            })
        return {
            "est_fuel_cost_inr": days * 800,
            "est_hotel_cost_inr": days * 3000,
            "warnings": ["Mock Itinerary Enabled for Testing"],
            "days_plan": mock_days_plan
        }

    if not _ensure_client():
        raise RuntimeError("GEMINI_API_KEY not set or no SDK available")

    user_msg = json.dumps(
        {
            "origin": origin,
            "destination": destination,
            "days": days,
            "legs": legs,
            "bike": bike_label,
            "vibe": vibe,
            "budget_tier": budget_tier,
            "season": season,
        },
        ensure_ascii=False,
    )

    call_fn = _call_new_sdk if _USE_NEW_SDK else _call_old_sdk
    last_error: Exception | None = None
    text = ""

    for attempt in range(2):
        if attempt > 0:
            time.sleep(3)
        try:
            raw = call_fn(user_msg)
            text = _strip_code_fence(raw)
            return json.loads(text)
        except json.JSONDecodeError as exc:
            last_error = exc
            log.warning("Gemini JSON parse failed on attempt %d: %s", attempt + 1, exc)
            # Truncation recovery
            try:
                t2 = text
                open_braces = t2.count('{') - t2.count('}')
                open_brackets = t2.count('[') - t2.count(']')
                if open_braces > 0 or open_brackets > 0:
                    t2 = re.sub(r',\s*$', '', t2.rstrip())
                    t2 = re.sub(r',\s*"[^"]*$', '', t2)
                    t2 += ']' * max(0, open_brackets) + '}' * max(0, open_braces)
                    result = json.loads(t2)
                    log.warning("Truncation recovery succeeded on attempt %d", attempt + 1)
                    return result
            except Exception as rec_exc:
                log.warning("Truncation recovery also failed: %s", rec_exc)
        except Exception as exc:
            last_error = exc
            log.warning("Gemini call failed on attempt %d: %s — %s", attempt + 1, type(exc).__name__, exc)
            if attempt == 0:
                continue
            break

    raise RuntimeError(f"Gemini itinerary generation failed: {last_error}")


def ping() -> bool:
    """Liveness check used by /healthz. Cheap one-token call."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if api_key.lower().startswith("mock"):
        return True

    if not _ensure_client():
        return False
    try:
        if _USE_NEW_SDK:
            resp = _client.models.generate_content(
                model=MODEL_NAME,
                contents="Reply with the single word: ok",
                config={"temperature": 0, "max_output_tokens": 8},
            )
            text = (resp.text or "").lower().strip()
        else:
            model = _genai_old.GenerativeModel(MODEL_NAME)
            resp = model.generate_content(
                "Reply with the single word: ok",
                generation_config={"temperature": 0, "max_output_tokens": 8},
            )
            text = (resp.text or "").lower().strip()
        return bool(text)
    except Exception as exc:
        log.warning("Gemini ping failed: %s — %s", type(exc).__name__, exc)
        return False


def analyze_receipt(base64_data: str, mime_type: str) -> Dict[str, Any]:
    """Call Gemini to analyze a receipt image and return title, amount, category.

    Mandates return format to strictly match {"title": str, "amount": float, "category": str}.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if api_key.lower().startswith("mock"):
        log.warning("GEMINI_API_KEY is missing or set to mock. Returning mock receipt analysis.")
        return {"title": "HP Petrol Pump", "amount": 1200.0, "category": "fuel"}

    if not _ensure_client():
        raise RuntimeError("GEMINI_API_KEY not set or no SDK available")

    prompt = (
        "Analyze this receipt image. Extract:\n"
        "1. Title: The vendor name or a brief description of the expense (e.g. 'HP Petrol Pump', 'Highway Dhaba Lunch').\n"
        "2. Amount: The total amount of the transaction in INR (number).\n"
        "3. Category: Choose the most fitting category strictly from this list: 'fuel', 'stay', 'food', 'toll', 'repair', 'permit', 'misc'.\n\n"
        "Return ONLY a valid JSON object matching this structure:\n"
        "{\n"
        "  \"title\": \"string\",\n"
        "  \"amount\": number,\n"
        "  \"category\": \"string\"\n"
        "}\n"
        "Do not return any markdown code blocks, backticks, or other text."
    )

    import base64 as _base64

    try:
        raw_bytes = _base64.b64decode(base64_data)
    except Exception as exc:
        raise ValueError(f"Invalid base64 data: {exc}")

    try:
        if _USE_NEW_SDK:
            from google.genai import types
            response = _client.models.generate_content(
                model=MODEL_NAME,
                contents=[
                    types.Part.from_bytes(data=raw_bytes, mime_type=mime_type),
                    prompt
                ],
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type="application/json"
                )
            )
            text = response.text or ""
        else:
            if _genai_old is None:
                raise RuntimeError("No Gemini SDK available")
            model = _genai_old.GenerativeModel(MODEL_NAME)
            response = model.generate_content([
                {
                    "mime_type": mime_type,
                    "data": raw_bytes
                },
                prompt
            ], generation_config={"temperature": 0.2, "response_mime_type": "application/json"})
            text = response.text or ""

        text = _strip_code_fence(text)
        return json.loads(text)
    except Exception as exc:
        log.exception("Gemini receipt analysis failed")
        raise RuntimeError(f"Gemini receipt analysis failed: {exc}") from exc
