"""Gemini 2.5 Flash wrapper — versioned prompt, JSON mode, single retry.

Migrated to the `google-genai` SDK (the `google-generativeai` package reached
EOL in November 2025). Uses ``genai.Client`` with ``api_key`` from env.

Loads `prompts/itinerary_v3.txt` once at module import. Temperature 0.4 per
CTO §4.4. Output token cap 8192. Hard wall-clock timeout 45s.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash"
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "itinerary_v3.txt"
PROMPT_TEXT = PROMPT_PATH.read_text(encoding="utf-8") if PROMPT_PATH.exists() else ""

_client = None


def _get_client():
    """Lazily create the genai client. Returns None if no API key."""
    global _client
    if _client is not None:
        return _client
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from google import genai
        _client = genai.Client(api_key=api_key)
        return _client
    except Exception as exc:
        log.warning("Failed to initialise google-genai Client: %s", exc)
        return None


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

    Raises ``RuntimeError`` if Gemini is not configured or both attempts fail.
    """
    client = _get_client()
    if client is None:
        raise RuntimeError("GEMINI_API_KEY not set")

    from google.genai import types

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

    config = types.GenerateContentConfig(
        system_instruction=PROMPT_TEXT,
        temperature=0.4,
        max_output_tokens=8192,
        response_mime_type="application/json",
    )

    last_error: Exception | None = None
    text = ""
    for attempt in range(2):
        if attempt > 0:
            import time; time.sleep(3)
        try:
            resp = client.models.generate_content(
                model=MODEL_NAME,
                contents=user_msg,
                config=config,
            )
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
    client = _get_client()
    if client is None:
        return False
    try:
        resp = client.models.generate_content(
            model=MODEL_NAME,
            contents="Reply with the single word: ok",
            config={
                "temperature": 0,
                "max_output_tokens": 8,
            },
        )
        text = (resp.text or "").lower().strip()
        return bool(text)  # any non-empty response = alive
    except Exception as exc:
        log.warning("Gemini ping failed: %s — %s", type(exc).__name__, exc)
        return False
