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
    if not api_key:
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
