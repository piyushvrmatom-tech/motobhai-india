"""GET /s/{short_id} — server-rendered share page with per-trip OG meta.

WhatsApp / Twitter / Facebook crawlers don't run JavaScript, so the `og:image`
needs to be in the initial HTML response. Firebase Hosting can't customise meta
per URL on a static site, so we let the backend serve `/s/**` directly. The
Firebase rewrite for /s/** is changed to proxy here instead of returning the
static share.html.

The page is fully self-contained: full trip data is rendered server-side, so
there's no client-side fetch round-trip and the page is usable before any JS
loads (works on cheap 2G phones too — CTO spec §D).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from backend.services import firestore_client

log = logging.getLogger(__name__)
router = APIRouter()

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


@router.get("/s/{short_id}", response_class=HTMLResponse)
def serve_share_page(short_id: str):
    trip_id = short_id if short_id.startswith("mb_") else f"mb_{short_id}"
    trip = firestore_client.load_trip(trip_id)
    if not trip:
        # Lightweight 404 page that still links home — better UX than raw JSON.
        return HTMLResponse(
            status_code=404,
            content=_render_404(short_id),
        )

    firestore_client.increment_share_view(trip_id)

    # asset_base hosts the CSS/JS/icons (Firebase Hosting).
    # api_base hosts the OG endpoint + this share page itself.
    asset_base = os.getenv("FRONTEND_ORIGIN", "https://motobhai-india.web.app").rstrip("/")
    api_base = os.getenv("API_BASE_URL", "https://motobhai-api.onrender.com").rstrip("/")

    og_image_url = trip.get("og_image_url") or f"{api_base}/api/og/{short_id.removeprefix('mb_')}.png"
    share_url = trip.get("share_url") or f"{api_base}/s/{short_id.removeprefix('mb_')}"

    # Escape </script> so a malicious city name can't break out of the seed script tag.
    # Also escape <!-- which would terminate the script block in older parsers.
    safe_json = (
        json.dumps(trip, default=str)
        .replace("</", "<\\/")
        .replace("<!--", "<\\!--")
    )
    template = _env.get_template("share.html")
    html = template.render(
        summary=trip.get("summary", {}),
        days_plan=trip.get("days_plan", []),
        bike_label=trip.get("_bike_label", "motorcycle"),
        og_image_url=og_image_url,
        share_url=share_url,
        asset_base=asset_base,
        trip_json=safe_json,
    )
    return HTMLResponse(
        content=html,
        headers={
            # No cache on HTML so the latest trip data shows up immediately,
            # but the OG image (cached separately) gets re-fetched only on TTL.
            "Cache-Control": "public, max-age=0, must-revalidate",
        },
    )


def _render_404(short_id: str) -> str:
    return f"""<!doctype html><html><head>
<title>Ride not found · Moto Bhai</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body{{font-family:system-ui,sans-serif;background:#0B0B0F;color:#F5F5F7;margin:0;padding:60px 20px;text-align:center;min-height:100vh}}
  h1{{font-size:28px;margin:0 0 12px}}
  p{{color:#C4C4CE}}
  a{{display:inline-block;margin-top:24px;background:#FF6A1A;color:#110800;padding:14px 28px;border-radius:99px;text-decoration:none;font-weight:700}}
</style></head><body>
<h1>Ride not found</h1>
<p>The link <code>/s/{short_id}</code> expired or never existed.</p>
<a href="/">Plan your own ride</a>
</body></html>"""
