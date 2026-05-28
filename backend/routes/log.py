"""POST /api/log — fire-and-forget event logger, forwards to Apps Script webhook."""
from __future__ import annotations

from fastapi import APIRouter, Request

from backend.services import sheets_logger

router = APIRouter()


@router.post("/api/log")
async def log_event(request: Request):
    body = await request.json()
    event_name = body.pop("event", "unknown")
    await sheets_logger.log_event(event_name, **body)
    return {"ok": True}
