# Architecture — Moto Bhai India v1.0

## TL;DR
A rider in Ghaziabad opens `motobhai-india.web.app`, types Gurugram → Manali → 3 days → Himalayan → Standard, and within 8 seconds has a downloadable PDF, a shareable link, and a route plan they trust enough to actually ride.

## System map

```
[Browser / PWA]                       (Firebase Hosting, CDN-edged)
   │
   ├── GET  /                          ← index.html (5-input form)
   ├── GET  /s/{short_id}              ← share.html (public itinerary view)
   │
   ▼
[Render — motobhai-api]                (FastAPI · Python 3.11 · Singapore region)
   ├── POST /api/plan        ── Routes API ─┐
   │                             Gemini ────┤
   │                             splitter   │
   │                             Firestore ─┘
   ├── POST /api/pdf          ── WeasyPrint → Cloud Storage (signed URL)
   ├── GET  /api/share/{id}   ← Firestore trips/
   ├── POST /api/otp/send     ── MSG91
   ├── POST /api/otp/verify   ── Firestore otp_codes/ + JWT sign
   ├── POST /api/log          ── Apps Script webhook (fire & forget)
   └── GET  /healthz          ── shallow + ?deep=1 probes Gemini & Routes
```

## Module layout (backend)

```
backend/
├── main.py                     entry point — Sentry init, routers wired
├── routes/
│   ├── plan.py                 POST /api/plan
│   ├── share.py                GET  /api/share/{short_id}
│   ├── otp.py                  POST /api/otp/send + /verify
│   ├── log.py                  POST /api/log
│   └── health.py               GET  /healthz
├── services/
│   ├── splitter.py             pure 350km cap logic, 100% tested
│   ├── routes_api.py           Google Routes v2 wrapper
│   ├── gemini.py               versioned-prompt LLM call
│   ├── firestore_client.py     trips/users/otp_codes/share_views
│   ├── otp_service.py          MSG91 + HMAC-SHA256 phone/code hashing
│   ├── jwt_service.py          HS256 sign/verify, 30-day TTL
│   ├── bikes.py                loads data/motorcycles_2026.json
│   └── sheets_logger.py        async fire-and-forget to Apps Script
├── models/                     Pydantic schemas
├── data/motorcycles_2026.json  112-entry DB
├── prompts/itinerary_v3.txt    versioned LLM prompt
└── tests/                      pytest, splitter at 100% coverage
```

## Why this stack
- **Firebase Hosting** — ~30ms TTFB across India, free tier covers v1.
- **Render** — zero-DevOps, auto-deploy on `git push origin main`.
- **Firestore** — serverless, pay-per-read, perfect for trip blobs.
- **No Kubernetes, no Docker registries, no microservices.** Four devs, not forty.

## Data flow (POST /api/plan)
1. Validate `PlanRequest` (Pydantic).
2. `routes_api.compute()` → total km + polyline.
3. `splitter.split()` → list of legs, each ≤ 350 km. **Authoritative.** Reject (422) with `suggested_days` if impossible.
4. `gemini.generate_itinerary()` adds colour: fuel stops, hotels, food, bhai_tip. Receives legs and MUST NOT alter distances.
5. Merge: splitter wins on km/from/to, Gemini wins on everything else.
6. `firestore_client.save_trip()` writes to `trips/{trip_id}` with 30-day TTL.
7. `sheets_logger.log_event_sync("plan_created", …)` fires off to Apps Script.
8. Return `PlanResponse` with `share_url` and `trip_id`.

## SLAs (per CTO §D)
- `/api/plan` — p50 < 6s, p95 < 12s, hard timeout 25s
- Zero 5xx tolerated on `/api/plan` and `/api/share/*` > 5 min — auto-page
- `/healthz` — shallow check < 100 ms, deep check (Gemini+Routes) < 5 s

## Security posture
- Backend issues JWTs after OTP — no client-side Firebase Auth.
- Phone numbers are hashed (HMAC-SHA256 with `OTP_SECRET`) before any storage.
- OTP codes hashed before storage; 3-attempt limit; 5-minute expiry.
- API key restrictions: HTTP referrer for `GMAPS_API_KEY`; IP allowlist for `GOOGLE_ROUTES_API_KEY`.
- Sheets webhook URL acts as a bearer token — never logged, never committed.
- No client-side tracking pixels beyond first-party analytics.
