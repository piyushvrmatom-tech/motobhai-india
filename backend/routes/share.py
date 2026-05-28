"""GET /api/share/{short_id} — public, read-only trip view."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.services import firestore_client

router = APIRouter()


@router.get("/api/share/{short_id}")
def get_share(short_id: str):
    """Public read of a trip. No auth. Used by /s/{short_id} frontend."""
    trip_id = short_id if short_id.startswith("mb_") else f"mb_{short_id}"
    doc = firestore_client.load_trip(trip_id)
    if not doc:
        raise HTTPException(status_code=404, detail="trip not found")
    firestore_client.increment_share_view(trip_id)
    # Sanitize Firestore timestamps → ISO strings so FastAPI can JSON-serialize
    return _sanitize(doc)


def _sanitize(obj):
    """Recursively convert datetime/Timestamp objects to ISO strings."""
    from datetime import datetime
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(i) for i in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    # Google Firestore Timestamp
    try:
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        if hasattr(obj, 'seconds'):  # protobuf Timestamp
            return datetime.fromtimestamp(obj.seconds, tz=__import__('datetime').timezone.utc).isoformat()
    except Exception:
        pass
    return obj
