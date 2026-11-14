import sqlite3
import hashlib
from io import BytesIO

import app as bidveil
import storage


def sample_record():
    return {
        "tender": {"title": "Tender A"},
        "vendors": [{"vendorName": "Vendor A", "proposalText": "private proposal", "weightedScore": 81}],
        "summary": {"winner": "Vendor A", "averageScore": 81},
        "evaluationMode": "manual",
        "documents": [{"scope": "vendor", "fileName": "proposal.txt", "sha256": "a" * 64}],
        "verification": {},
    }


def test_persists_record_and_omits_source_text():
    storage.initialize_database()
    submitted = sample_record()
    saved = storage.save_evaluation(submitted)

    assert saved["evaluationId"]
    assert len(saved["recordHash"]) == 64
    assert storage.list_evaluations()[0]["id"] == saved["evaluationId"]
    loaded = storage.get_evaluation(saved["evaluationId"])
    assert loaded["vendors"][0].get("proposalText") is None
    assert loaded["integrity"]["status"] == "verified"
    assert storage.verify_evaluation(saved["evaluationId"])["verified"] is True


def test_detects_modified_persisted_record():
    saved = storage.save_evaluation(sample_record())
    with sqlite3.connect(storage.database_path()) as connection:
        connection.execute(
            "UPDATE evaluations SET record_json = ? WHERE id = ?",
            ('{"tampered":true}', saved["evaluationId"]),
        )

    verified = storage.verify_evaluation(saved["evaluationId"])
    assert verified["verified"] is False
    assert verified["status"] == "integrity_mismatch"


def test_document_verification_checks_reuploaded_bytes():
    content = b"original proposal"
    record = sample_record()
    record["documents"][0]["vendorIndex"] = 0
    record["documents"][0]["sha256"] = hashlib.sha256(content).hexdigest()
    saved = storage.save_evaluation(record)
    client = bidveil.app.test_client()

    verified = client.post(
        f"/api/evaluations/{saved['evaluationId']}/verify-documents",
        data={"documents": (BytesIO(content), "proposal.txt", "text/plain")},
        content_type="multipart/form-data",
    )
    mismatch = client.post(
        f"/api/evaluations/{saved['evaluationId']}/verify-documents",
        data={"documents": (BytesIO(b"changed proposal"), "proposal.txt", "text/plain")},
        content_type="multipart/form-data",
    )

    assert verified.status_code == 200
    assert verified.get_json()["verified"] is True
    assert mismatch.status_code == 409
    assert mismatch.get_json()["status"] == "document_mismatch"
