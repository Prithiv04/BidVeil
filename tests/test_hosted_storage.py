import hashlib
import sqlite3

import pytest

import document_store
import storage
from scripts import migrate_sqlite_to_postgres as migration


class FakeCursor:
    def __init__(self, rowcount=0, row=None):
        self.rowcount = rowcount
        self._row = row

    def fetchone(self):
        return self._row


class FakePostgres:
    def __init__(self):
        self.queries = []
        self.rows = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=()):
        self.queries.append((query, params))
        if query.startswith("INSERT INTO evaluations"):
            record_id = params[0]
            if record_id in self.rows:
                return FakeCursor(0)
            self.rows[record_id] = {
                "id": record_id,
                "record_json": params[6],
                "record_hash": params[7],
            }
            return FakeCursor(1)
        if query.startswith("SELECT record_json, record_hash"):
            row = self.rows.get(params[0])
            return FakeCursor(row=(row["record_json"], row["record_hash"]) if row else None)
        return FakeCursor()


def test_postgres_initialization_adds_sort_order_for_existing_tables(monkeypatch):
    connection = FakePostgres()
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/db")
    monkeypatch.setattr(storage.psycopg, "connect", lambda *_args, **_kwargs: connection)

    storage.initialize_database()

    sql = "\n".join(query for query, _params in connection.queries)
    assert "CREATE TABLE IF NOT EXISTS evaluations" in sql
    assert "ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS sort_order BIGSERIAL" in sql
    assert "idx_evaluations_sort_order" in sql


def test_postgres_query_adapter_uses_psycopg_parameter_markers(monkeypatch):
    connection = FakePostgres()
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/db")

    storage._execute(connection, "SELECT * FROM evaluations WHERE id = ?", ("record-id",))

    assert connection.queries[-1] == (
        "SELECT * FROM evaluations WHERE id = %s",
        ("record-id",),
    )


def test_migration_is_idempotent_and_validates_source_and_target(tmp_path, monkeypatch, capsys):
    database_file = tmp_path / "source.sqlite3"
    record_json = '{"id":"record-1","evaluation":{}}'
    record_hash = hashlib.sha256(record_json.encode("utf-8")).hexdigest()
    with sqlite3.connect(database_file) as source:
        source.execute(
            """CREATE TABLE evaluations (
                id TEXT, created_at TEXT, tender_title TEXT, winner TEXT,
                evaluation_mode TEXT, average_score REAL, record_json TEXT, record_hash TEXT
            )"""
        )
        source.execute(
            "INSERT INTO evaluations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("record-1", "2026-01-01T00:00:00+00:00", "Tender", "Vendor", "ai", 80.0, record_json, record_hash),
        )

    postgres = FakePostgres()
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/db")
    monkeypatch.setenv("BIDVEIL_DB_PATH", str(database_file))
    monkeypatch.setattr(migration.psycopg, "connect", lambda *_args, **_kwargs: postgres)

    assert migration.main() == 0
    assert "1 rows copied; 0 already existed" in capsys.readouterr().out
    assert migration.main() == 0
    assert "0 rows copied; 1 already existed" in capsys.readouterr().out
    assert len(postgres.rows) == 1

    with sqlite3.connect(database_file) as source:
        source.execute("UPDATE evaluations SET record_hash = ? WHERE id = ?", ("0" * 64, "record-1"))
    with pytest.raises(ValueError, match="failed its SHA-256 integrity check"):
        migration.main()


def test_supabase_upload_requires_private_bucket(monkeypatch):
    class Bucket:
        def __init__(self, public):
            self.name = "bidveil-documents"
            self.public = public

    class Storage:
        def __init__(self, public):
            self.bucket = Bucket(public)
            self.uploaded = None

        def list_buckets(self):
            return [self.bucket]

        def from_(self, _bucket_name):
            return self

        def upload(self, path, data, file_options):
            self.uploaded = (path, data, file_options)

    class Client:
        def __init__(self, public):
            self.storage = Storage(public)

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-only-key")
    monkeypatch.setenv("SUPABASE_DOCUMENT_BUCKET", "bidveil-documents")

    private_client = Client(False)
    monkeypatch.setattr(document_store, "create_client", lambda *_args: private_client)
    object_path = document_store.upload_document(b"pdf bytes", "proposal.pdf", "application/pdf")
    assert object_path.endswith(".pdf")
    assert private_client.storage.uploaded[1] == b"pdf bytes"
    assert private_client.storage.uploaded[2]["content-type"] == "application/pdf"

    public_client = Client(True)
    monkeypatch.setattr(document_store, "create_client", lambda *_args: public_client)
    assert document_store.check_health()["available"] is False
    with pytest.raises(RuntimeError, match="must exist and be private"):
        document_store.upload_document(b"pdf bytes", "proposal.pdf", "application/pdf")
