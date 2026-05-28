# On-Call Runbook — Moto Bhai India

## P0: planner is down

1. Hit `https://motobhai-api.onrender.com/healthz?deep=1`.
2. If `gemini: down` → check Google AI Studio quota and outages page. Failover: serve last cached plan from Firestore.
3. If `routes: down` → check GCP project `motobhai-india` quotas. Failover: temporarily reject new plans with HTTP 503 + "Routes API recovering".
4. If `firestore: false` → check service account expiry. If `FIRESTORE_CREDENTIALS_B64` was rotated, re-paste base64-encoded JSON into Render.
5. If shallow `/healthz` returns 503 → an env var was unset. Diff Render dashboard against `.env.example`.

## Rotating secrets

### `OTP_SECRET` and `JWT_SECRET`
- These are HMAC keys. Rotating invalidates all live JWTs and all in-flight OTP codes.
- Generate locally: `python3 -c "import secrets, string; a = string.ascii_letters + string.digits + '_-'; print(''.join(secrets.choice(a) for _ in range(48)))"`
- Paste into Render. Render restarts the service automatically. Announce in `#moto-bhai-eng` because all logged-in sessions will be kicked.

### `GOOGLE_ROUTES_API_KEY`
- GCP Console → APIs & Services → Credentials → motobhai-routes-key → Regenerate.
- Restrict to IP allowlist (Render egress IPs — see Render dashboard → Network).

### `MSG91_AUTH_KEY`
- MSG91 dashboard → API → Auth Keys → Generate new.
- Update Render. Verify with `/api/otp/send` to a test number.

### `FIRESTORE_CREDENTIALS_B64`
- GCP Console → IAM → Service Accounts → motobhai-firestore → Keys → Add key → JSON.
- Encode: `base64 -i key.json | tr -d '\n'`. Paste the result into Render.
- Revoke the old key immediately.

## Sentry triage rules
- **P0** (page within 5 min): any `5xx` on `/api/plan` or `/api/share/*` for > 5 min.
- **P1** (1 h): Gemini parse-error rate > 5% in a 10-min window.
- **P2** (daily digest): WeasyPrint render errors, Sheets webhook failures, OTP send failures < 1%.

## Common diagnostic commands

```bash
# Smoke test
curl https://motobhai-api.onrender.com/healthz | jq

# Plan smoke (uses production keys — be sparing)
curl -X POST https://motobhai-api.onrender.com/api/plan \
  -H "Content-Type: application/json" \
  -d '{"from":"Gurugram","to":"Manali","days":3,"bike_id":"re_himalayan_450","vibe":"standard"}'

# Tail logs
# Render dashboard → motobhai-api → Logs (live tail)
```
