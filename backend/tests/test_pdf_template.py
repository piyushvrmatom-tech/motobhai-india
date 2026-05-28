"""Tests for the Jinja2 template that feeds WeasyPrint.

These tests verify the template renders to valid HTML for representative
trip payloads. They do NOT exercise WeasyPrint itself (which has heavy
native deps unsuitable for CI matrix runs).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


@pytest.fixture(scope="module")
def template():
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template("itinerary.html")


@pytest.fixture
def trip_minimum():
    """Smallest valid trip — 1 day, no warnings, no hotel, no tips."""
    return {
        "trip_id": "mb_test01",
        "share_url": "https://motobhai-india.web.app/s/test01",
        "summary": {
            "from": "Delhi", "to": "Agra",
            "total_km": 230, "total_days": 1, "max_day_km": 230,
            "est_fuel_cost_inr": 800, "est_hotel_cost_inr": 0,
        },
        "warnings": [],
        "days_plan": [
            {
                "day": 1, "from": "Delhi", "to": "Agra", "km": 230,
                "eta_hours": 4.5, "elevation_gain_m": 0,
                "fuel_stops": [], "food_stops": [], "warnings": [],
                "hotel_suggestion": None, "bhai_tip": "",
            }
        ],
    }


@pytest.fixture
def trip_canonical():
    """The Gurugram → Manali 3-day acceptance test trip, fully populated."""
    return {
        "trip_id": "mb_a3f9k2",
        "share_url": "https://motobhai-india.web.app/s/a3f9k2",
        "summary": {
            "from": "Gurugram", "to": "Manali",
            "total_km": 538, "total_days": 3, "max_day_km": 248,
            "est_fuel_cost_inr": 2400, "est_hotel_cost_inr": 7500,
        },
        "warnings": ["Rohtang Pass closed before 9 AM", "Atal Tunnel two-wheelers 9-5 only"],
        "days_plan": [
            {
                "day": 1, "from": "Gurugram", "to": "Chandigarh", "km": 248,
                "eta_hours": 5.5, "elevation_gain_m": 120,
                "fuel_stops": [
                    {"name": "Murthal IOC", "km_from_start": 65, "type": "petrol"},
                    {"name": "Karnal HP", "km_from_start": 132, "type": "petrol"},
                ],
                "food_stops": ["Amrik Sukhdev Dhaba, Murthal"],
                "hotel_suggestion": {
                    "name": "Hotel Mountview",
                    "area": "Sector 10, Chandigarh",
                    "price_range_inr": "2500-4000",
                },
                "bhai_tip": "Leave by 6 AM. NH-44 truck traffic builds up by 10.",
                "warnings": [],
            },
            {
                "day": 2, "from": "Chandigarh", "to": "Mandi", "km": 200,
                "eta_hours": 5.0, "elevation_gain_m": 700,
                "fuel_stops": [{"name": "Bilaspur BP", "km_from_start": 100, "type": "petrol"}],
                "food_stops": ["Sundernagar dhaba"],
                "hotel_suggestion": {
                    "name": "Hotel Riverbank",
                    "area": "Mandi town",
                    "price_range_inr": "1800-3000",
                },
                "bhai_tip": "Fill up at Bilaspur — next reliable pump is past Pandoh.",
                "warnings": ["Hairpins begin past Sundernagar"],
            },
            {
                "day": 3, "from": "Mandi", "to": "Manali", "km": 90,
                "eta_hours": 3.0, "elevation_gain_m": 900,
                "fuel_stops": [],
                "food_stops": ["Drifters Cafe, Old Manali"],
                "hotel_suggestion": {
                    "name": "Sunshine Himalayan Adventure Hostel",
                    "area": "Vashisht",
                    "price_range_inr": "1200-2500",
                },
                "bhai_tip": "Aut tunnel saves 30 min over the old highway.",
                "warnings": [],
            },
        ],
    }


def test_template_renders_minimum(template, trip_minimum):
    html = template.render(trip=trip_minimum, bike_label="RE Hunter 350", vibe="chill", generated_at="28 May 2026")
    assert "Delhi" in html
    assert "Agra" in html
    assert "230" in html  # total km
    assert "Pre-ride checklist" in html
    assert "ATGATT" in html


def test_template_renders_canonical(template, trip_canonical):
    html = template.render(trip=trip_canonical, bike_label="Royal Enfield Himalayan 450", vibe="standard", generated_at="28 May 2026")
    # Cover
    assert "Gurugram" in html
    assert "Manali" in html
    assert "538" in html  # total km
    assert "248" in html  # longest day
    # Warnings
    assert "Rohtang Pass" in html
    assert "Atal Tunnel" in html
    # Day-by-day data
    assert "Chandigarh" in html
    assert "Mandi" in html
    assert "Murthal" in html
    assert "Karnal" in html
    assert "Bilaspur" in html
    assert "Drifters" in html
    # Bhai tips
    assert "Leave by 6 AM" in html
    assert "Bilaspur" in html
    # Appendix
    assert "Cloud Datastore" not in html  # not a secret leak
    assert "Police" in html  # emergency table
    assert "1033" in html  # NH patrol


def test_template_escapes_html(template, trip_minimum):
    # If a malicious city name slips in, it must be escaped.
    trip_minimum["summary"]["from"] = "<script>alert(1)</script>"
    html = template.render(trip=trip_minimum, bike_label="X", vibe="standard", generated_at="now")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_template_a4_landscape_size_declared(template, trip_minimum):
    html = template.render(trip=trip_minimum, bike_label="X", vibe="standard", generated_at="now")
    assert "size: A4 landscape" in html


def test_template_has_signal_orange_accent(template, trip_minimum):
    html = template.render(trip=trip_minimum, bike_label="X", vibe="standard", generated_at="now")
    assert "#FF6A1A" in html


def test_template_empty_warnings_section_hidden(template, trip_minimum):
    """When there are no trip-wide warnings, the warning block must not render."""
    html = template.render(trip=trip_minimum, bike_label="X", vibe="standard", generated_at="now")
    assert "Trip-wide advisories" not in html


def test_template_warnings_section_visible_when_present(template, trip_canonical):
    html = template.render(trip=trip_canonical, bike_label="X", vibe="standard", generated_at="now")
    assert "Trip-wide advisories" in html


def test_template_each_day_has_a_page_break(template, trip_canonical):
    html = template.render(trip=trip_canonical, bike_label="X", vibe="standard", generated_at="now")
    # CSS class `.day` carries `page-break-after: always` for all but the last
    assert html.count('class="day"') == 3
