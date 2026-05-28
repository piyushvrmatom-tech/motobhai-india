# API Reference — Moto Bhai India v1.0

Base URL: `https://motobhai-api.onrender.com`

All endpoints return JSON. Errors use standard HTTP status codes and a `{"detail": ...}` body.

## POST `/api/plan`

Create a new trip plan.

### Request
```json
{
  "from": "Gurugram",
  "to": "Manali",
  "days": 3,
  "bike_id": "re_himalayan_450",
  "vibe": "standard",
  "budget_tier": "standard",
  "loop": false,
  "user_phone_hash": null
}
```

| Field | Type | Notes |
|---|---|---|
| `from` | string | 2-120 chars |
| `to` | string | 2-120 chars |
| `days` | int | 1-21 |
| `bike_id` | string\|null | one of `motorcycles_2026.json` ids |
| `bike_custom` | string\|null | required if `bike_id` is null |
| `vibe` | enum | `chill` \| `standard` \| `hardcore` |
| `budget_tier` | enum | `economy` \| `standard` \| `premium` \| `luxury` |
| `loop` | bool | round trip if true |
| `user_phone_hash` | string\|null | from OTP login (sha256) |

### Response 200
```json
{
  "trip_id": "mb_a3f9k2",
  "created_at": "2026-05-28T02:30:00Z",
  "summary": {
    "from": "Gurugram",
    "to": "Manali",
    "total_km": 538,
    "total_days": 3,
    "est_fuel_cost_inr": 2400,
    "est_hotel_cost_inr": 7500,
    "max_day_km": 248
  },
  "days_plan": [ /* see below */ ],
  "warnings": ["Rohtang Pass closed before 9 AM"],
  "share_url": "https://motobhai-india.web.app/s/a3f9k2",
  "pdf_url": null
}
```

### Errors
- `422 trip_too_long_for_days` — body carries `suggested_days`.
- `502 routes_api` / `502 gemini` — upstream failure, retry the call.
- `503` — server misconfigured.

### Day-plan object
```json
{
  "day": 1,
  "from": "Gurugram",
  "to": "Chandigarh",
  "km": 248,
  "eta_hours": 5.5,
  "elevation_gain_m": 120,
  "route_polyline": "encoded_string",
  "fuel_stops": [{ "name": "Murthal IOC", "km_from_start": 65, "type": "petrol" }],
  "hotel_suggestion": { "name": "Hotel Mountview", "area": "Sector 10, Chandigarh", "price_range_inr": "2500-4000" },
  "food_stops": ["Amrik Sukhdev Dhaba, Murthal"],
  "bhai_tip": "Leave by 6 AM. NH-44 truck traffic builds up by 10.",
  "warnings": []
}
```

## GET `/api/share/{short_id}`
Public, no auth. Returns the full trip document. Increments `share_views/{trip_id}.view_count`.

## POST `/api/otp/send`
Request: `{ "phone": "+919xxxxxxxxx" }` → `{ "ok": true }`.
Errors: `503` if MSG91/Firestore down, `502` on SMS provider error.

## POST `/api/otp/verify`
Request: `{ "phone": "+919xxxxxxxxx", "code": "123456" }` → `{ "ok": true, "token": "<jwt>" }`.
Errors: `401 invalid_or_expired`.

## POST `/api/log`
Fire-and-forget. Body is forwarded to the Apps Script webhook as-is. Always returns `{"ok": true}`.

## GET `/healthz`
Shallow:
```json
{ "ok": true, "version": "1.0.0", "env": "production",
  "config": { "gemini_key": true, "routes_key": true, ... },
  "firestore": true }
```
Deep (`?deep=1`):
```json
{ ..., "gemini": "up", "routes": "up" }
```
Non-ok status returns HTTP 503 so Render's health check fails fast.

## GET `/api/motorcycles`
Returns the full 112-bike database for the frontend carousel.
