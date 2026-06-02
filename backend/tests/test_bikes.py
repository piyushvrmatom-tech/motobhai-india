"""Schema + integrity tests for backend/data/motorcycles_2026.json."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.services import bikes

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "motorcycles_2026.json"
REQUIRED = {
    "bike_id", "make", "model", "year", "engine_cc", "mileage_kmpl",
    "fuel_tank_l", "segment", "seat_height_mm", "kerb_weight_kg", "abs",
    "tubeless_tyres", "ex_showroom_inr_lakh", "touring_score",
    "good_for_pillion", "bs6_phase2_oba", "notes",
}
ALLOWED_SEGMENTS = {
    "commuter", "sport", "naked", "cruiser", "adventure",
    "tourer", "scrambler", "retro",
}
ALLOWED_ABS = {"single_channel", "dual_channel", "none"}


@pytest.fixture(scope="module")
def db():
    with DATA_PATH.open() as f:
        return json.load(f)


def test_data_file_exists():
    assert DATA_PATH.exists(), f"missing {DATA_PATH}"


def test_is_a_list(db):
    assert isinstance(db, list)


def test_exactly_117_models(db):
    assert len(db) == 117


def test_bike_ids_unique(db):
    ids = [b["bike_id"] for b in db]
    assert len(set(ids)) == len(ids)


def test_every_bike_has_required_fields(db):
    for b in db:
        missing = REQUIRED - set(b.keys())
        assert not missing, f"{b.get('bike_id')} missing: {missing}"


def test_segments_are_valid(db):
    for b in db:
        assert b["segment"] in ALLOWED_SEGMENTS, f"{b['bike_id']}: bad segment {b['segment']}"


def test_abs_values_are_valid(db):
    for b in db:
        assert b["abs"] in ALLOWED_ABS, f"{b['bike_id']}: bad abs {b['abs']}"


def test_touring_score_in_range(db):
    for b in db:
        assert 1 <= b["touring_score"] <= 10, f"{b['bike_id']}: touring_score {b['touring_score']}"


def test_engine_cc_realistic(db):
    for b in db:
        assert 50 <= b["engine_cc"] <= 1300, f"{b['bike_id']}: cc {b['engine_cc']}"


def test_mileage_positive(db):
    for b in db:
        assert b["mileage_kmpl"] > 0


def test_bikes_service_loads(db):
    """The service module must successfully load the same file."""
    assert len(bikes.all_bikes()) == 117


def test_lookup_by_id(db):
    sample = db[0]["bike_id"]
    found = bikes.get_bike(sample)
    assert found is not None
    assert found["bike_id"] == sample


def test_lookup_missing_returns_none():
    assert bikes.get_bike("no_such_bike_id") is None


def test_label_for_known_bike(db):
    sample = db[0]
    label = bikes.label_for(sample["bike_id"], None)
    assert sample["make"] in label
    assert sample["model"] in label
    assert "kmpl" in label


def test_label_for_custom_bike():
    label = bikes.label_for(None, "Vintage Yezdi 250")
    assert "Vintage Yezdi 250" in label


def test_label_fallback():
    assert "350cc" in bikes.label_for(None, None)
