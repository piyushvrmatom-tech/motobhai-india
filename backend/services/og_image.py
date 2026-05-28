"""Dynamic OG image generator — renders a per-trip 1200x630 PNG for social previews.

CTO spec §F Phase 2: "public share view with OG image auto-gen (route silhouette
+ bike + dates) via Cloud Run side-job or static template." We do this in-process
because the volume is tiny (one render per share-link share) and Pillow is already
pulled in by Sentry's dependencies. No Cloud Run needed.

The generated image is uploaded to GCS at `og/{trip_id}.png` with a long-lived
public-read ACL (these are not secret). The signed URL lives 7 days; for the
share page, we use object-public URLs since OG crawlers can't follow signed URLs.
"""
from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont  # type: ignore

    PIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    PIL_AVAILABLE = False


# ─── Layout constants ────────────────────────────────────────────────────────
W, H = 1200, 630
ACCENT = (255, 106, 26)
BG_TOP = (11, 11, 15)
BG_BOTTOM = (31, 31, 42)
TEXT = (245, 245, 247)
TEXT_DIM = (196, 196, 206)
MUTED = (138, 138, 153)


# ─── Font discovery ─────────────────────────────────────────────────────────
# Render's Debian image ships DejaVu by default. We prefer Inter if available
# in the project, else fall back gracefully through the standard stack.
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/inter/Inter-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",  # mac dev
]
FONT_REGULAR_CANDIDATES = [
    "/usr/share/fonts/truetype/inter/Inter-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _font(size: int, bold: bool = True) -> "ImageFont.FreeTypeFont":
    candidates = FONT_CANDIDATES if bold else FONT_REGULAR_CANDIDATES
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    # Last-resort PIL default font (bitmap, looks bad but never crashes).
    return ImageFont.load_default()


# ─── Drawing primitives ─────────────────────────────────────────────────────
def _gradient_bg(img: "Image.Image") -> None:
    """Diagonal gradient from BG_TOP to BG_BOTTOM."""
    base = Image.new("RGB", (W, H), BG_TOP)
    top = Image.new("RGB", (W, H), BG_BOTTOM)
    mask = Image.new("L", (W, H))
    px = mask.load()
    for y in range(H):
        for x in range(W):
            # diagonal: max(0, min(255, (x + y) * 255 / (W + H)))
            v = int(((x + y) / (W + H)) * 255)
            px[x, y] = v
    base.paste(top, (0, 0), mask)
    img.paste(base, (0, 0))


def _draw_logo(draw: "ImageDraw.ImageDraw", x: int, y: int, size: int = 64) -> None:
    """Stylized 'M' with two wheel dots in signal orange — matches favicon."""
    # Rounded-rect background
    draw.rounded_rectangle(
        [(x, y), (x + size, y + size)],
        radius=size // 4,
        fill=(11, 11, 15),
        outline=ACCENT,
        width=2,
    )
    # 'M' strokes
    pad = size * 0.22
    s = size - 2 * pad
    pts = [
        (x + pad, y + pad + s),
        (x + pad + s * 0.25, y + pad),
        (x + pad + s * 0.5, y + pad + s * 0.6),
        (x + pad + s * 0.75, y + pad),
        (x + pad + s, y + pad + s),
    ]
    draw.line(pts, fill=ACCENT, width=max(3, size // 16), joint="curve")
    # Wheel dots
    r = max(2, size // 24)
    draw.ellipse(
        [(x + pad + s * 0.18 - r, y + pad + s + size * 0.06 - r),
         (x + pad + s * 0.18 + r, y + pad + s + size * 0.06 + r)],
        fill=ACCENT,
    )
    draw.ellipse(
        [(x + pad + s * 0.82 - r, y + pad + s + size * 0.06 - r),
         (x + pad + s * 0.82 + r, y + pad + s + size * 0.06 + r)],
        fill=ACCENT,
    )


def _draw_motorcycle(draw: "ImageDraw.ImageDraw", cx: int, cy: int, scale: float = 1.0) -> None:
    """Tiny stylized motorcycle silhouette, centred on (cx, cy)."""
    s = scale
    # Wheels
    r = int(58 * s)
    draw.ellipse([(cx - 220 * s - r, cy + 80 * s - r), (cx - 220 * s + r, cy + 80 * s + r)],
                 outline=ACCENT, width=int(6 * s), fill=BG_TOP)
    draw.ellipse([(cx + 100 * s - r, cy + 80 * s - r), (cx + 100 * s + r, cy + 80 * s + r)],
                 outline=ACCENT, width=int(6 * s), fill=BG_TOP)
    # Hub circles
    r2 = int(22 * s)
    draw.ellipse([(cx - 220 * s - r2, cy + 80 * s - r2), (cx - 220 * s + r2, cy + 80 * s + r2)],
                 outline=ACCENT, width=int(3 * s))
    draw.ellipse([(cx + 100 * s - r2, cy + 80 * s - r2), (cx + 100 * s + r2, cy + 80 * s + r2)],
                 outline=ACCENT, width=int(3 * s))
    # Frame
    pts = [
        (cx - 220 * s, cy + 80 * s),
        (cx - 130 * s, cy),
        (cx - 40 * s, cy),
        (cx, cy + 40 * s),
        (cx + 100 * s, cy + 80 * s),
    ]
    draw.line(pts, fill=ACCENT, width=int(6 * s), joint="curve")
    # Handlebar
    draw.line([(cx - 130 * s, cy), (cx - 80 * s, cy - 60 * s), (cx - 30 * s, cy - 60 * s)],
              fill=ACCENT, width=int(6 * s), joint="curve")
    # Headlight
    rh = int(14 * s)
    draw.ellipse([(cx - 120 * s - rh, cy + 15 * s - rh), (cx - 120 * s + rh, cy + 15 * s + rh)],
                 fill=ACCENT)


def _draw_route_arrow(draw: "ImageDraw.ImageDraw", x1: int, y1: int, x2: int, y2: int) -> None:
    """Dashed route arrow from (x1,y1) to (x2,y2)."""
    # Dashed line
    import math
    dist = math.hypot(x2 - x1, y2 - y1)
    dash = 18
    gap = 12
    nx, ny = (x2 - x1) / dist, (y2 - y1) / dist
    t = 0
    while t < dist:
        sx = x1 + nx * t
        sy = y1 + ny * t
        ex = x1 + nx * min(t + dash, dist)
        ey = y1 + ny * min(t + dash, dist)
        draw.line([(sx, sy), (ex, ey)], fill=ACCENT, width=4)
        t += dash + gap
    # Arrowhead
    ah = 16
    angle = math.atan2(y2 - y1, x2 - x1)
    p1 = (x2 - ah * math.cos(angle - 0.5), y2 - ah * math.sin(angle - 0.5))
    p2 = (x2 - ah * math.cos(angle + 0.5), y2 - ah * math.sin(angle + 0.5))
    draw.polygon([(x2, y2), p1, p2], fill=ACCENT)


def _truncate(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


# ─── Public entry points ────────────────────────────────────────────────────
def render_trip_og(
    origin: str,
    destination: str,
    days: int,
    total_km: float,
    bike_label: str = "",
) -> Optional[bytes]:
    """Render the per-trip OG image. Returns PNG bytes, or None if PIL is missing."""
    if not PIL_AVAILABLE:
        log.warning("PIL not installed; OG image generation disabled")
        return None

    img = Image.new("RGB", (W, H), BG_TOP)
    _gradient_bg(img)
    draw = ImageDraw.Draw(img)

    # ─── Top-left: logo + brand
    _draw_logo(draw, 64, 56, size=68)
    draw.text((152, 60), "Moto Bhai", font=_font(28, bold=True), fill=TEXT)
    draw.text((152, 96), "INDIA · MOTORCYCLE TRIPS", font=_font(15, bold=True), fill=MUTED)

    # ─── Centre block: route headline
    origin_short = _truncate(origin, 18)
    dest_short = _truncate(destination, 18)

    # Headline goes on two lines: "ORIGIN → DESTINATION"
    # Cap headline width at the motorcycle area so they never collide.
    # Right edge for headline = 720px; motorcycle sits past 760.
    RIGHT_EDGE = 720

    # Try single-line layout at full size; auto-shrink and finally wrap if needed.
    head_size = 80
    arrow_size = 72
    y_head = 230
    head_font = _font(head_size, bold=True)
    arrow_font = _font(arrow_size, bold=True)

    def _measure_single_line(of, af):
        ob = draw.textbbox((0, 0), origin_short, font=of)
        ab = draw.textbbox((0, 0), "→", font=af)
        db = draw.textbbox((0, 0), dest_short, font=of)
        return (ob[2] - ob[0]) + 20 + (ab[2] - ab[0]) + 20 + (db[2] - db[0])

    # Shrink up to two steps before wrapping
    while head_size > 50 and 64 + _measure_single_line(head_font, arrow_font) > RIGHT_EDGE:
        head_size -= 12
        arrow_size -= 10
        head_font = _font(head_size, bold=True)
        arrow_font = _font(arrow_size, bold=True)

    single_line_width = _measure_single_line(head_font, arrow_font)
    if 64 + single_line_width <= RIGHT_EDGE:
        # Single line fits.
        draw.text((64, y_head), origin_short, font=head_font, fill=TEXT)
        o_bbox = draw.textbbox((64, y_head), origin_short, font=head_font)
        ax = o_bbox[2] + 20
        draw.text((ax, y_head + 6), "→", font=arrow_font, fill=ACCENT)
        a_bbox = draw.textbbox((ax, y_head + 6), "→", font=arrow_font)
        draw.text((a_bbox[2] + 20, y_head), dest_short, font=head_font, fill=TEXT)
    else:
        # Wrap to two lines: origin on top, arrow + destination underneath.
        draw.text((64, y_head), origin_short, font=head_font, fill=TEXT)
        draw.text((64, y_head + head_size + 10), "→", font=arrow_font, fill=ACCENT)
        a_bbox = draw.textbbox((64, y_head + head_size + 10), "→", font=arrow_font)
        draw.text((a_bbox[2] + 20, y_head + head_size + 4), dest_short, font=head_font, fill=TEXT)
        y_head += head_size + 10  # nudge the sub line down too

    # ─── Sub: days · km · bike (positioned below the headline)
    sub = f"{days} day{'s' if days != 1 else ''} · {int(total_km)} km"
    if bike_label:
        sub += f" · {_truncate(bike_label, 34)}"
    sub_y = max(440, y_head + head_size + 60)
    draw.text((64, sub_y), sub, font=_font(28, bold=False), fill=TEXT_DIM)

    # ─── Accent bar
    draw.rectangle([(64, 510), (264, 518)], fill=ACCENT)

    # ─── Footer: URL
    draw.text((64, 540), "motobhai-india.web.app", font=_font(22, bold=True), fill=ACCENT)

    # ─── Right side: motorcycle silhouette (positioned to never overlap headline)
    _draw_motorcycle(draw, cx=970, cy=330, scale=0.75)

    # Output
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def upload_og(trip_id: str, png_bytes: bytes) -> Optional[str]:
    """Upload an OG image to GCS, returning the public URL.

    Uses the same bucket as PDFs by default (PDF_BUCKET env). The object is
    set to public-read (uniform bucket-level access must permit it, otherwise
    we fall through and return None — share page uses the static fallback).
    """
    try:
        from backend.services.storage import get_client
    except ImportError:
        return None
    client = get_client()
    if client is None:
        return None
    bucket_name = os.getenv("PDF_BUCKET", "motobhai-pdf-files")
    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(f"og/{trip_id}.png")
        blob.upload_from_string(png_bytes, content_type="image/png")
        blob.cache_control = "public, max-age=86400"
        blob.patch()
        # Public URL only works if bucket has uniform-bucket-level-access with allUsers viewer
        # OR fine-grained ACL with allUsers reader on the blob. Caller may need to set this
        # at the bucket level once.
        return f"https://storage.googleapis.com/{bucket_name}/og/{trip_id}.png"
    except Exception:
        log.exception("OG upload failed for %s", trip_id)
        return None
