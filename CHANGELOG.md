# Changelog

All notable changes to Moto Bhai India. Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased] — feat/v1-pdf (stacked on feat/v1-refactor)

### Added
- **`POST /api/pdf`** — accepts `{ trip_id }`, returns a 7-day signed Cloud Storage URL to a WeasyPrint A4-landscape PDF.
- **`services/pdf_renderer.py`** — Jinja2 template + WeasyPrint, lazy import (no startup cost if PDFs aren't used).
- **`services/storage.py`** — GCS wrapper, V4 signed URLs with `attachment` content-disposition for clean downloads, falls back to streaming PDF if GCS isn't configured.
- **`templates/itinerary.html`** — magazine-grade A4 landscape PDF: cover with stat grid + advisories + share URL, day-by-day with fuel/food/hotel/bhai_tip/warnings panels, appendix with pre-ride checklist + emergency numbers.
- **8 new template tests** covering canonical Gurugram→Manali, HTML escape safety, A4 landscape declaration, page-break behaviour.
- `PDF_BUCKET` env var (defaults to `motobhai-pdf-files`).
- `google-cloud-storage` dependency.

### Changed
- `plan.py` now stashes `_bike_id`, `_bike_custom`, `_bike_label`, `_vibe`, `_budget_tier` on the persisted trip doc so the PDF endpoint can recover context.

### Migration notes
- Bucket `motobhai-pdf-files` must exist in `motobhai-india` GCP project before deploy (or set `PDF_BUCKET` to an existing bucket).
- Set bucket lifecycle: delete objects after 14 days (matches our 7-day signed URL TTL + headroom).
- `motobhai-firestore` service account needs `roles/storage.objectAdmin` on this bucket. (Optional — without it, the endpoint streams PDFs directly instead of uploading; rider still gets the file.)

## [Unreleased] — feat/v1-refactor

### Added
- **Modular backend layout**: `routes/`, `services/`, `models/`, `data/`, `prompts/`, `tests/` per CTO spec §3.
- `services/splitter.py` — pure 350 km/day cap logic, 31 tests, ~96% coverage, deterministic redistribution + waypoint snapping.
- `services/routes_api.py` — Google **Routes API v2** wrapper (not legacy Directions).
- `services/gemini.py` — versioned prompt (`prompts/itinerary_v3.txt`), JSON-mode, single retry, 18 s timeout.
- `services/firestore_client.py` — trip persistence to `trips/{trip_id}` with 30-day TTL, share-view counters.
- `services/otp_service.py` — MSG91 transactional SMS with DLT template, HMAC-SHA256 phone/code hashing, 3-attempt + 5-min expiry.
- `services/jwt_service.py` — hand-rolled HS256 sign/verify, 30-day TTL.
- `services/bikes.py` + `data/motorcycles_2026.json` — **112-model** 2026 India motorcycle DB (15 brands, all segments, BS6 Phase 2 OBD-2A/2B).
- `services/sheets_logger.py` — async fire-and-forget logger to Apps Script webhook.
- `routes/plan.py` — new `POST /api/plan` contract per CTO §4.1.
- `routes/share.py` — public `GET /api/share/{short_id}`.
- `routes/otp.py` — `POST /api/otp/send` + `/verify` returning signed JWT.
- `routes/log.py` — `POST /api/log` fire-and-forget.
- `routes/health.py` — `GET /healthz` with optional `?deep=1` Gemini+Routes probes.
- Sentry initialisation in `main.py` (FastAPI + Starlette integrations).
- GitHub Actions `ci.yml` (ruff lint + pytest, fail under 90% coverage on splitter).
- GitHub Actions `deploy-frontend.yml` (Firebase Hosting on push to `main`).
- `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/ONCALL.md`.
- `.env.example` listing every required env var.
- `render.yaml` — explicit Python 3.11.9, `/healthz` health check, all CTO-spec env vars declared.

### Changed
- `backend/main.py` reduced from 677-line monolith to 71-line entry that wires routers.
- Endpoint names migrated to CTO contract: `/api/plan` (was `/api/generate-itinerary`), `/api/pdf` (was `/api/itinerary/pdf`).
- `requirements.txt` adds `sentry-sdk[fastapi]`, `weasyprint`, `jinja2`, `google-auth`; removes `reportlab`.

### Removed
- Hardcoded 15-bike Python dict (replaced by 112-entry JSON DB).
- In-memory `_OTP_STORE` dict + fake `'mb_' + timestamp` tokens (replaced by Firestore + signed JWT).
- Tacked-on `_mb_router` v2 block at the bottom of `main.py`.

### Migration notes
- Frontend payload fields rename: `origin` → `from`, `destination` → `to`, `motorcycle` → `bike_id` + `bike_custom`, new `vibe` field. The legacy `/api/generate-itinerary` endpoint is gone — frontend must update before deploy.
- 5 Render env vars MUST be set before deploy: `GOOGLE_ROUTES_API_KEY`, `SHEETS_WEBHOOK_URL`, `OTP_SECRET`, `JWT_SECRET` (NEW), `MSG91_AUTH_KEY`, `MSG91_TEMPLATE_ID` (NEW), `FIRESTORE_CREDENTIALS_B64`.

## [2.0.0] — 2026-05-21
- Firestore location intelligence, weather API, weekly data integration.

## [0.3.0] — earlier
- Replaced rule-based itinerary with Gemini 2.5 Flash.
