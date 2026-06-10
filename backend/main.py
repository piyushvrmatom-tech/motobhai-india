"""Moto Bhai India — FastAPI entry point. v1.1.0 (run4: pdf+share+otp hardened).

This module is intentionally thin: it boots the app, configures middleware,
optionally initialises Sentry, and mounts the routers from `routes/`. All
business logic lives in `services/` and `routes/`.
"""
from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# ─── Sentry (must be initialised before the FastAPI app is created) ─────────
SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            environment=os.getenv("ENV", "production"),
            release=os.getenv("RENDER_GIT_COMMIT", "unknown")[:7],
            traces_sample_rate=float(os.getenv("SENTRY_TRACES", "0.1")),
            send_default_pii=False,
            integrations=[StarletteIntegration(), FastApiIntegration()],
        )
        log.info("Sentry initialised")
    except Exception as exc:
        log.warning("Sentry init failed: %s", exc)

# ─── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(title="Moto Bhai India", version="1.1.0")

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "https://motobhai.app")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN, "http://localhost:5173", "http://localhost:8000"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    allow_credentials=False,
)

# ─── Routers ────────────────────────────────────────────────────────────────
from backend.routes import health, log as log_route, otp, pdf, plan, share  # noqa: E402

app.include_router(health.router, tags=["ops"])
app.include_router(plan.router, tags=["plan"])
app.include_router(share.router, tags=["share"])
app.include_router(pdf.router, tags=["pdf"])
app.include_router(otp.router, tags=["auth"])
app.include_router(log_route.router, tags=["ops"])


@app.get("/")
def root():
    return {
        "service": "Moto Bhai India",
        "version": "1.0.0",
        "docs": "/docs",
        "healthz": "/healthz",
    }
