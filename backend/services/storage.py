"""Google Cloud Storage wrapper for generated PDFs and OG images.

We upload to a single bucket `motobhai-pdf-files` and return signed URLs
with a 7-day TTL. The bucket name is overridable via `PDF_BUCKET` env var.

Lifecycle: configure a 14-day deletion rule in the bucket so we don't
accumulate stale objects. (Set up once in the GCP console.)
"""
from __future__ import annotations

import base64
import json
import logging
import os
from datetime import timedelta
from typing import Optional

log = logging.getLogger(__name__)

try:
    from google.cloud import storage  # type: ignore
    from google.oauth2 import service_account  # type: ignore

    GCS_AVAILABLE = True
except ImportError:  # pragma: no cover
    GCS_AVAILABLE = False


_client: Optional["storage.Client"] = None


def _init_client() -> Optional["storage.Client"]:
    if not GCS_AVAILABLE:
        log.warning("google-cloud-storage not installed; PDF upload disabled")
        return None
    b64 = os.getenv("FIRESTORE_CREDENTIALS_B64", "").strip()
    project = os.getenv("GCP_PROJECT", "motobhai-india")
    try:
        if b64:
            info = json.loads(base64.b64decode(b64).decode("utf-8"))
            creds = service_account.Credentials.from_service_account_info(info)
            return storage.Client(project=info.get("project_id", project), credentials=creds)
        return storage.Client(project=project)
    except Exception as exc:
        log.warning("GCS init failed: %s", exc)
        return None


def get_client() -> Optional["storage.Client"]:
    global _client
    if _client is None:
        _client = _init_client()
    return _client


def is_enabled() -> bool:
    return get_client() is not None


def upload_pdf(trip_id: str, pdf_bytes: bytes, *, ttl_days: int = 7) -> Optional[str]:
    """Upload PDF and return a signed URL valid for `ttl_days`.

    Returns None if GCS is not configured (caller should degrade to a
    streaming PDF response).
    """
    client = get_client()
    if client is None:
        return None
    bucket_name = os.getenv("PDF_BUCKET", "motobhai-pdf-files")
    try:
        bucket = client.bucket(bucket_name)
        blob_name = f"trips/{trip_id}.pdf"
        blob = bucket.blob(blob_name)
        blob.upload_from_string(pdf_bytes, content_type="application/pdf")
        # V4 signed URL with explicit response-content-disposition for nicer downloads.
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(days=ttl_days),
            method="GET",
            response_disposition=f'attachment; filename="motobhai_{trip_id}.pdf"',
        )
    except Exception:
        log.exception("PDF upload to GCS failed")
        return None
