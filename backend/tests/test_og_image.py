"""Tests for the dynamic OG image generator.

PIL is the only heavy dep — these tests verify dimensions, content type,
and that the renderer handles edge cases without throwing.
"""
from __future__ import annotations

import io

import pytest

from backend.services import og_image


@pytest.fixture
def pil_available():
    if not og_image.PIL_AVAILABLE:
        pytest.skip("Pillow not installed")


def test_renders_canonical(pil_available):
    png = og_image.render_trip_og(
        origin="Gurugram",
        destination="Manali",
        days=3,
        total_km=538,
        bike_label="Royal Enfield Himalayan 450",
    )
    assert png is not None
    assert png.startswith(b"\x89PNG")
    # Sanity-check dimensions via PIL
    from PIL import Image

    img = Image.open(io.BytesIO(png))
    assert img.size == (1200, 630)
    assert img.mode == "RGB"


def test_renders_short_trip(pil_available):
    png = og_image.render_trip_og(
        origin="Delhi",
        destination="Agra",
        days=1,
        total_km=230,
        bike_label="Hero Splendor",
    )
    assert png is not None
    assert png.startswith(b"\x89PNG")


def test_handles_long_city_names(pil_available):
    """Truncation must not throw and must produce a valid PNG."""
    png = og_image.render_trip_og(
        origin="Thiruvananthapuram",
        destination="Kanniyakumari Cape Comorin Point",
        days=2,
        total_km=88,
        bike_label="KTM 390 Adventure",
    )
    assert png is not None
    assert png.startswith(b"\x89PNG")


def test_handles_empty_bike_label(pil_available):
    png = og_image.render_trip_og(
        origin="Mumbai",
        destination="Goa",
        days=2,
        total_km=580,
        bike_label="",
    )
    assert png is not None


def test_handles_zero_km(pil_available):
    """Edge: a same-city loop or geocode failure that returns 0 km."""
    png = og_image.render_trip_og(
        origin="Pune",
        destination="Pune",
        days=1,
        total_km=0,
    )
    assert png is not None


def test_renders_within_reasonable_time(pil_available):
    import time
    t0 = time.time()
    og_image.render_trip_og(origin="A", destination="B", days=1, total_km=100, bike_label="X")
    elapsed = time.time() - t0
    # ~150ms expected on typical hardware; allow 2s for slow CI runners.
    assert elapsed < 2.0, f"OG render took {elapsed:.2f}s (>2s)"


def test_output_under_200kb(pil_available):
    """OG images must be small — WhatsApp/Twitter strip preview if > a few MB,
    but we keep ours under 200KB for snappy WhatsApp previews."""
    png = og_image.render_trip_og(
        origin="Gurugram", destination="Manali", days=3, total_km=538, bike_label="RE Himalayan 450"
    )
    assert len(png) < 200_000


def test_truncate_helper():
    assert og_image._truncate("Hello", 10) == "Hello"
    assert og_image._truncate("Hello world", 8) == "Hello w…"
    assert og_image._truncate("", 5) == ""
    assert og_image._truncate(None, 5) == ""  # type: ignore[arg-type]
