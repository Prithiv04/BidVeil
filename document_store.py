"""Private Supabase Storage adapter for completed evaluation source files."""

from __future__ import annotations

import os
import uuid
from typing import Any

from supabase import create_client


def _settings() -> tuple[str, str, str]:
    return (
        os.environ.get("SUPABASE_URL", "").strip(),
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
        os.environ.get("SUPABASE_DOCUMENT_BUCKET", "bidveil-documents").strip(),
    )


def is_configured() -> bool:
    url, key, bucket = _settings()
    return bool(url and key and bucket)


def upload_document(data: bytes, filename: str, content_type: str) -> str:
    """Save one original document in a private bucket and return its object path."""
    url, key, bucket = _settings()
    if not (url and key and bucket):
        raise RuntimeError("Supabase document storage is not configured.")
    client = create_client(url, key)
    bucket_info = _find_bucket(client, bucket)
    if bucket_info is None or getattr(bucket_info, "public", None) is not False:
        raise RuntimeError("Supabase document bucket must exist and be private.")
    suffix = ".pdf" if filename.lower().endswith(".pdf") else ".txt"
    object_path = f"{uuid.uuid4().hex}{suffix}"
    client.storage.from_(bucket).upload(
        object_path,
        data,
        file_options={"content-type": content_type, "upsert": "false"},
    )
    return object_path


def delete_document(object_path: str) -> None:
    """Remove a source file if its evaluation could not be committed."""
    url, key, bucket = _settings()
    if not (url and key and bucket):
        raise RuntimeError("Supabase document storage is not configured.")
    create_client(url, key).storage.from_(bucket).remove([object_path])


def _find_bucket(client, bucket_name: str):
    return next(
        (item for item in client.storage.list_buckets() if getattr(item, "name", None) == bucket_name),
        None,
    )


def check_health() -> dict[str, Any]:
    url, key, bucket = _settings()
    if not (url and key and bucket):
        return {"configured": False, "available": False, "provider": "supabase-storage"}
    try:
        client = create_client(url, key)
        bucket_info = _find_bucket(client, bucket)
        is_private = bucket_info is not None and getattr(bucket_info, "public", None) is False
        return {
            "configured": True,
            "available": is_private,
            "private": is_private,
            "provider": "supabase-storage",
            "bucket": bucket,
        }
    except Exception:
        return {"configured": True, "available": False, "provider": "supabase-storage", "bucket": bucket}
