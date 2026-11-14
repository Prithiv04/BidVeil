"""SQLite persistence and SHA-256 integrity checks for completed evaluations."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DB_PATH = Path(__file__).resolve().parent / "instance" / "bidveil.sqlite3"


def database_path() -> Path:
    configured = os.environ.get("BIDVEIL_DB_PATH", "").strip()
    return Path(configured).expanduser().resolve() if configured else _DEFAULT_DB_PATH


def _connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database() -> None:
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS evaluations (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                tender_title TEXT NOT NULL,
                winner TEXT NOT NULL,
                evaluation_mode TEXT NOT NULL,
                average_score REAL NOT NULL,
                record_json TEXT NOT NULL,
                record_hash TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_evaluations_created_at ON evaluations(created_at DESC)"
        )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record_integrity(record_json: str, expected_hash: str) -> bool:
    actual = _sha256_text(record_json)
    return hmac.compare_digest(actual, expected_hash)


def save_evaluation(result: dict[str, Any]) -> dict[str, Any]:
    """Persist a completed result and return it with its durable record identity."""
    if not isinstance(result.get("vendors"), list) or not result["vendors"]:
        raise ValueError("Only completed evaluations with vendor results can be persisted.")

    record_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    persisted_result = json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))
    # Source document text is only needed for inference and is never retained.
    tender = persisted_result.get("tender")
    if isinstance(tender, dict):
        tender.pop("documents", None)
    for vendor in persisted_result.get("vendors", []):
        if isinstance(vendor, dict):
            vendor.pop("documents", None)
            # Proposals are sensitive source material. Keep only derived results.
            vendor.pop("proposalText", None)
            vendor.pop("proposal", None)

    document_hashes = [
        {
            "scope": document.get("scope", "vendor"),
            "vendorIndex": document.get("vendorIndex"),
            "fileName": document.get("fileName"),
            "sha256": document.get("sha256"),
        }
        for document in persisted_result.get("documents", [])
        if isinstance(document, dict) and document.get("sha256")
    ]
    envelope = {
        "id": record_id,
        "createdAt": created_at,
        "documentHashes": document_hashes,
        "evaluation": persisted_result,
    }
    record_json = _canonical_json(envelope)
    record_hash = _sha256_text(record_json)
    tender_title = str((persisted_result.get("tender") or {}).get("title") or "Untitled tender")
    winner = str((persisted_result.get("summary") or {}).get("winner") or "No winner")
    average_score = float((persisted_result.get("summary") or {}).get("averageScore") or 0)
    mode = str(persisted_result.get("evaluationMode") or "ai")

    with _connect() as connection:
        connection.execute(
            """INSERT INTO evaluations
               (id, created_at, tender_title, winner, evaluation_mode, average_score, record_json, record_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (record_id, created_at, tender_title, winner, mode, average_score, record_json, record_hash),
        )

    result["evaluationId"] = record_id
    result["createdAt"] = created_at
    result["recordHash"] = record_hash
    result["integrity"] = {
        "status": "verified",
        "algorithm": "SHA-256",
        "recordHash": record_hash,
        "documentHashes": document_hashes,
    }
    if isinstance(result.get("verification"), dict):
        result["verification"]["recordIntegrity"] = result["integrity"]
    return result


def list_evaluations(limit: int = 100) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 500))
    with _connect() as connection:
        rows = connection.execute(
            """SELECT id, created_at, tender_title, winner, evaluation_mode,
                      average_score, record_hash, record_json
               FROM evaluations ORDER BY created_at DESC, rowid DESC LIMIT ?""",
            (safe_limit,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "createdAt": row["created_at"],
            "tenderTitle": row["tender_title"],
            "winner": row["winner"],
            "evaluationMode": row["evaluation_mode"],
            "averageScore": row["average_score"],
            "recordHash": row["record_hash"],
            "integrityStatus": "verified" if _record_integrity(row["record_json"], row["record_hash"]) else "failed",
        }
        for row in rows
    ]


def get_evaluation(record_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT record_json, record_hash FROM evaluations WHERE id = ?", (record_id,)
        ).fetchone()
    if row is None:
        return None
    valid = _record_integrity(row["record_json"], row["record_hash"])
    envelope = json.loads(row["record_json"])
    result = envelope["evaluation"]
    result.update(
        {
            "evaluationId": envelope["id"],
            "createdAt": envelope["createdAt"],
            "recordHash": row["record_hash"],
            "integrity": {
                "status": "verified" if valid else "failed",
                "algorithm": "SHA-256",
                "recordHash": row["record_hash"],
                "documentHashes": envelope.get("documentHashes", []),
            },
        }
    )
    if isinstance(result.get("verification"), dict):
        result["verification"]["recordIntegrity"] = result["integrity"]
    return result


def verify_evaluation(record_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT record_json, record_hash FROM evaluations WHERE id = ?", (record_id,)
        ).fetchone()
    if row is None:
        return None
    valid = _record_integrity(row["record_json"], row["record_hash"])
    try:
        envelope = json.loads(row["record_json"])
    except (json.JSONDecodeError, TypeError):
        envelope = {}
    return {
        "evaluationId": record_id,
        "verified": valid,
        "status": "verified" if valid else "integrity_mismatch",
        "algorithm": "SHA-256",
        "recordHash": row["record_hash"],
        "documentHashes": envelope.get("documentHashes", []) if isinstance(envelope, dict) else [],
    }


def verify_document_hashes(record_id: str, supplied_documents: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Compare re-uploaded document bytes with hashes protected by the record hash."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT record_json, record_hash FROM evaluations WHERE id = ?", (record_id,)
        ).fetchone()
    if row is None:
        return None
    if not _record_integrity(row["record_json"], row["record_hash"]):
        return {
            "evaluationId": record_id,
            "verified": False,
            "status": "record_integrity_mismatch",
            "algorithm": "SHA-256",
        }
    envelope = json.loads(row["record_json"])
    expected = envelope.get("documentHashes", [])
    if not expected:
        return {
            "evaluationId": record_id,
            "verified": False,
            "status": "no_documents_in_record",
            "algorithm": "SHA-256",
            "checkedCount": 0,
        }

    def identity(document: dict[str, Any]) -> tuple[Any, ...]:
        return (
            document.get("scope", "vendor"),
            document.get("vendorIndex"),
            document.get("fileName"),
            document.get("sha256"),
        )

    if any("scope" not in document for document in supplied_documents):
        # Generic re-upload field: establish byte and filename matches independent
        # of the original vendor grouping, which is not encoded in a file itself.
        matches = Counter((item.get("fileName"), item.get("sha256")) for item in expected) == Counter(
            (item.get("fileName"), item.get("sha256")) for item in supplied_documents
        )
    else:
        matches = Counter(identity(document) for document in expected) == Counter(
            identity(document) for document in supplied_documents
        )
    return {
        "evaluationId": record_id,
        "verified": matches,
        "status": "verified" if matches else "document_mismatch",
        "algorithm": "SHA-256",
        "checkedCount": len(supplied_documents),
        "expectedCount": len(expected),
    }


def check_database_health() -> bool:
    try:
        with _connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return True
    except (OSError, sqlite3.Error):
        return False
