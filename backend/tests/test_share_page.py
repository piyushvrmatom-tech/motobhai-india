"""Tests for the server-rendered share page at GET /s/{short_id}.

Most of the value here is verifying that the OG meta tags are correctly
populated and that the page is crawler-friendly (no JS needed for OG).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def trip_doc():
    return {
        "trip_id": "mb_a3f9k2",
        "share_url": "https://motobhai-india.web.app/s/a3f9k2",
        "og_image_url": "https://storage.googleapis.com/motobhai-pdf-files/og/mb_a3f9k2.png",
        "_bike_label": "Royal Enfield Himalayan 450 (30 kmpl, 17L tank)",
        "summary": {
            "from": "Gurugram", "to": "Manali",
            "total_km": 538, "total_days": 3, "max_day_km": 248,
            "est_fuel_cost_inr": 2400, "est_hotel_cost_inr": 7500,
        },
        "warnings": ["Rohtang Pass closed before 9 AM"],
        "days_plan": [
            {
                "day": 1, "from": "Gurugram", "to": "Chandigarh", "km": 248,
                "eta_hours": 5.5,
                "bhai_tip": "Leave by 6 AM. NH-44 truck traffic builds up by 10.",
                "hotel_suggestion": {"name": "Hotel Mountview", "area": "Sector 10, Chandigarh", "price_range_inr": "2500-4000"},
            },
            {
                "day": 2, "from": "Chandigarh", "to": "Mandi", "km": 200,
                "eta_hours": 5.0,
                "bhai_tip": "Fill up at Bilaspur \u2014 next reliable pump is past Pandoh.",
                "hotel_suggestion": {"name": "Hotel Riverbank", "area": "Mandi", "price_range_inr": "1800-3000"},
            },
            {
                "day": 3, "from": "Mandi", "to": "Manali", "km": 90,
                "eta_hours": 3.0,
                "bhai_tip": "Aut tunnel saves 30 min.",
                "hotel_suggestion": {"name": "Sunshine Hostel", "area": "Vashisht", "price_range_inr": "1200-2500"},
            },
        ],
    }


@pytest.fixture
def client():
    from backend.main import app
    return TestClient(app)


def test_share_page_renders_canonical(client, trip_doc):
    with patch("backend.routes.share_page.firestore_client.load_trip", return_value=trip_doc), \
         patch("backend.routes.share_page.firestore_client.increment_share_view"):
        r = client.get("/s/a3f9k2")
    assert r.status_code == 200
    html = r.text
    # OG meta has the right image URL
    assert 'property="og:image"' in html
    assert "motobhai-pdf-files/og/mb_a3f9k2.png" in html
    # Headline rendered server-side (crawler-readable)
    assert "Gurugram" in html
    assert "Manali" in html
    # All three days rendered server-side
    assert "Day 1" in html
    assert "Day 2" in html
    assert "Day 3" in html
    # Bhai tips appear
    assert "Leave by 6 AM" in html
    assert "Bilaspur" in html
    # Hotel suggestions appear
    assert "Hotel Mountview" in html
    assert "Sunshine Hostel" in html


def test_share_page_404_when_missing(client):
    with patch("backend.routes.share_page.firestore_client.load_trip", return_value=None):
        r = client.get("/s/nosuch")
    assert r.status_code == 404
    assert "Ride not found" in r.text
    assert "Plan your own ride" in r.text


def test_share_page_handles_legacy_trip_without_og_url(client, trip_doc):
    """Old trips planned before PR #5 won't have og_image_url stashed.
    Page should fall back to /api/og/{id}.png URL."""
    trip = {**trip_doc}
    trip.pop("og_image_url")
    with patch("backend.routes.share_page.firestore_client.load_trip", return_value=trip), \
         patch("backend.routes.share_page.firestore_client.increment_share_view"):
        r = client.get("/s/a3f9k2")
    assert r.status_code == 200
    # Should reference the /api/og endpoint
    assert "/api/og/a3f9k2.png" in r.text


def test_share_page_increments_view_count(client, trip_doc):
    with patch("backend.routes.share_page.firestore_client.load_trip", return_value=trip_doc), \
         patch("backend.routes.share_page.firestore_client.increment_share_view") as inc:
        r = client.get("/s/a3f9k2")
    assert r.status_code == 200
    inc.assert_called_once_with("mb_a3f9k2")


def test_share_page_normalises_short_id(client, trip_doc):
    """Both /s/a3f9k2 and /s/mb_a3f9k2 should work and look up the same doc."""
    with patch("backend.routes.share_page.firestore_client.load_trip", return_value=trip_doc) as load, \
         patch("backend.routes.share_page.firestore_client.increment_share_view"):
        r = client.get("/s/mb_a3f9k2")
    assert r.status_code == 200
    load.assert_called_once_with("mb_a3f9k2")


def test_share_page_html_escapes_user_input(client, trip_doc):
    """If a city name has <script>, the rendered HTML must escape it."""
    trip = {**trip_doc, "summary": {**trip_doc["summary"], "from": "<script>alert(1)</script>"}}
    with patch("backend.routes.share_page.firestore_client.load_trip", return_value=trip), \
         patch("backend.routes.share_page.firestore_client.increment_share_view"):
        r = client.get("/s/a3f9k2")
    assert r.status_code == 200
    # The unescaped script tag must NOT appear in the rendered HTML body
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text
