"""Copy BIDVEIL evaluation rows to DATABASE_URL without changing record hashes.

Run once before deploying: python scripts/migrate_sqlite_to_postgres.py
The source SQLite file is read-only; existing rows are left untouched.
"""

from __future__ import annotations

import os
import hashlib
import sqlite3
import sys
from pathlib import Path

import psycopg


def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("DATABASE_URL is required; set it in your private environment.", file=sys.stderr)
        return 2

    source = Path(os.environ.get("BIDVEIL_DB_PATH", "instance/bidveil.sqlite3")).resolve()
    if not source.is_file():
        print(f"SQLite database not found: {source}", file=sys.stderr)
        return 2

    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as sqlite_db:
        sqlite_db.row_factory = sqlite3.Row
        rows = sqlite_db.execute(
            "SELECT id, created_at, tender_title, winner, evaluation_mode, average_score, record_json, record_hash "
            "FROM evaluations ORDER BY created_at, rowid"
        ).fetchall()

    with psycopg.connect(database_url, connect_timeout=10) as postgres_db:
        postgres_db.execute(
            """CREATE TABLE IF NOT EXISTS evaluations (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                tender_title TEXT NOT NULL,
                winner TEXT NOT NULL,
                evaluation_mode TEXT NOT NULL,
                average_score DOUBLE PRECISION NOT NULL,
                record_json TEXT NOT NULL,
                record_hash TEXT NOT NULL,
                sort_order BIGSERIAL UNIQUE NOT NULL
            )"""
        )
        postgres_db.execute(
            "ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS sort_order BIGSERIAL"
        )
        postgres_db.execute(
            "ALTER TABLE evaluations ALTER COLUMN sort_order SET NOT NULL"
        )
        postgres_db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_evaluations_sort_order ON evaluations(sort_order)"
        )
        postgres_db.execute(
            "CREATE INDEX IF NOT EXISTS idx_evaluations_created_at ON evaluations(created_at DESC)"
        )
        inserted = 0
        for row in rows:
            if hashlib.sha256(row["record_json"].encode("utf-8")).hexdigest() != row["record_hash"]:
                raise ValueError(f"Source SQLite record {row['id']} failed its SHA-256 integrity check.")
            cursor = postgres_db.execute(
                """INSERT INTO evaluations
                   (id, created_at, tender_title, winner, evaluation_mode, average_score, record_json, record_hash)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
                tuple(row),
            )
            existing = postgres_db.execute(
                "SELECT record_json, record_hash FROM evaluations WHERE id = %s", (row["id"],)
            ).fetchone()
            if existing is None or existing[1] != row["record_hash"] or existing[0] != row["record_json"]:
                raise ValueError(f"PostgreSQL record {row['id']} does not match the SQLite source.")
            inserted += cursor.rowcount

    print(f"Migration complete: {inserted} rows copied; {len(rows) - inserted} already existed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
