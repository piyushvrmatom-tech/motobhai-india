"""Loads `data/motorcycles_2026.json` once at import. Provides lookup by `bike_id`."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "motorcycles_2026.json"

_bikes: List[Dict[str, Any]] = []
_by_id: Dict[str, Dict[str, Any]] = {}


def _load() -> None:
    global _bikes, _by_id
    if not DATA_PATH.exists():
        log.warning("motorcycles_2026.json not found at %s — bikes DB empty", DATA_PATH)
        _bikes = []
        _by_id = {}
        return
    try:
        with DATA_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("motorcycles_2026.json must be a top-level array")
        _bikes = data
        _by_id = {b["bike_id"]: b for b in data if "bike_id" in b}
        log.info("Loaded %d motorcycles from data file", len(_bikes))
    except Exception:
        log.exception("Failed to load motorcycles_2026.json")
        _bikes = []
        _by_id = {}


_load()


def all_bikes() -> List[Dict[str, Any]]:
    return _bikes


def get_bike(bike_id: str) -> Optional[Dict[str, Any]]:
    return _by_id.get(bike_id)


def label_for(bike_id: Optional[str], bike_custom: Optional[str]) -> str:
    """Human-readable bike label for the Gemini prompt."""
    if bike_id:
        b = get_bike(bike_id)
        if b:
            return (
                f"{b.get('make','')} {b.get('model','')} "
                f"({b.get('mileage_kmpl', 30)} kmpl, {b.get('fuel_tank_l', 15)}L tank)"
            ).strip()
    if bike_custom:
        return f"{bike_custom} (custom, assume 30 kmpl, 15L tank)"
    return "Generic 350cc tourer (30 kmpl, 15L tank)"


def mileage_for(bike_id: Optional[str], bike_custom: Optional[str]) -> int:
    if bike_id:
        b = get_bike(bike_id)
        if b:
            return int(b.get("mileage_kmpl", 30))
    return 30
