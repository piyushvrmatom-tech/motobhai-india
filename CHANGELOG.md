# Changelog

## [Unreleased] — feat/v1-og (stacked on feat/v1-refactor)

### Added
- **Per-trip dynamic OG image generator** — `backend/services/og_image.py` renders a unique 1200×630 PNG for every shared trip via Pillow. Origin → Destination headline auto-shrinks then wraps when it would collide with the motorcycle silhouette. Outputs ~45 KB, renders in ~150 ms.
- **`GET /api/og/{short_id}.png`** — returns the cached image from GCS, or renders inline with a 24h cache header if not yet uploaded.
- Plan endpoint now generates + uploads the OG image at trip-creation time (best-effort, never blocks the plan response).
- 8 new tests for the OG generator covering canonical, short trip, long city names, empty bike label, zero km, render time bound, output size bound, and truncate helper.

### Changed
- `backend/requirements.txt`: add `Pillow>=10.4.0`.
- `backend/main.py`: mount `og.router`.

### Migration notes
- For the public OG URL strategy to work, `motobhai-pdf-files` bucket needs uniform-bucket-level-access disabled, or `allUsers` reader on the `og/` prefix. Falls back gracefully to inline-rendered PNGs from `/api/og/{id}.png` if GCS access is restricted.

## [Unreleased] — feat/v1-refactor
…(see PR #1)
