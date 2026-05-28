"""Gemini 2.5 Flash wrapper — versioned prompt, JSON mode, single retry.

Loads `prompts/itinerary_v3.txt` once at module import. Temperature 0.4 per
CTO §4.4. Output token cap 4096. Hard wall-clock timeout 18s.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List

import google.generativeai as genai

log = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash"
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "itinerary_v3.txt"
PROMPT_TEXT = PROMPT_PATH.read_text(encoding="utf-8") if PROMPT_PATH.exists() else ""

_configured = False


def _configure() -> bool:
    global _configured
    if _configured:
        return True
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return False
    genai.configure(api_key=api_key)
    _configured = True
    return True


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


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

    Raises `RuntimeError` if Gemini is not configured or both attempts fail.
    """
    if not _configure():
        raise RuntimeError("GEMINI_API_KEY not set")

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

    model = genai.GenerativeModel(
        MODEL_NAME,
        system_instruction=PROMPT_TEXT,
        generation_config={
            "temperature": 0.4,
            "max_output_tokens": 8192,
            "response_mime_type": "application/json",
        },
    )

    last_error: Exception | None = None
    for attempt in range(2):
        if attempt > 0:
            import time; time.sleep(3)
        try:
            resp = model.generate_content(user_msg, request_options={"timeout": 45})
            text = _strip_code_fence(resp.text)
            return json.loads(text)
        except json.JSONDecodeError as exc:
            last_error = exc
            log.warning("Gemini JSON parse failed on attempt %d: %s", attempt + 1, exc)
            # Try truncation recovery: close open brackets
            try:
                t2 = text
                open_braces = t2.count('{') - t2.count('}')
                open_brackets = t2.count('[') - t2.count(']')
                if open_braces > 0 or open_brackets > 0:
                    # Close last open array/object cleanly
                    # Strip trailing comma/partial token first
                    t2 = re.sub(r',\s*$', '', t2.rstrip())
                    t2 = re.sub(r',\s*"[^"]*$', '', t2)  # cut partial key
                    t2 += ']' * max(0, open_brackets) + '}' * max(0, open_braces)
                    result = json.loads(t2)
                    log.warning("Truncation recovery succeeded on attempt %d", attempt + 1)
                    return result
            except Exception as rec_exc:
                log.warning("Truncation recovery also failed: %s", rec_exc)
        except Exception as exc:  # network, quota, content-filter, etc.
            last_error = exc
            log.warning("Gemini call failed on attempt %d: %s", attempt + 1, exc)
            break
    raise RuntimeError(f"Gemini itinerary generation failed: {last_error}")


def ping() -> bool:
    """Liveness check used by /healthz. Cheap one-token call."""
    if not _configure():
        return False
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        resp = model.generate_content(
            "Reply with the single word: ok",
            generation_config={"temperature": 0, "max_output_tokens": 4},
            request_options={"timeout": 15},
        )
        return "ok" in (resp.text or "").lower()
    except Exception:
        return False
