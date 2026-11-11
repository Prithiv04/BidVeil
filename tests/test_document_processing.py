import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from pypdf import PdfWriter
from werkzeug.datastructures import FileStorage

import app as bidveil
import near_ai


def make_text_pdf(text: str = "Readable bid proposal text") -> bytes:
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n"
        + content
        + b"\nendstream",
    ]
    document = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{index} 0 obj\n".encode("ascii"))
        document.extend(obj)
        document.extend(b"\nendobj\n")

    xref_offset = len(document)
    document.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    document.extend(
        (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(document)


def file_upload(data: bytes, filename: str, content_type: str) -> FileStorage:
    return FileStorage(
        stream=BytesIO(data),
        filename=filename,
        content_type=content_type,
    )


def bid_payload(name: str = "Vendor A") -> dict:
    return {
        "tender": {"title": "Test tender", "maximumBudget": 100000},
        "bids": [
            {
                "vendorName": name,
                "quotedPrice": 85000,
                "proposalText": "Brief text summary",
            }
        ],
    }


def sample_ai_output_for_test(name: str = "Vendor A") -> dict:
    vendor = {
        "vendorName": name,
        "quotedPrice": 85000,
        "technicalCapabilities": "Secure implementation",
        "deliveryTimeline": "Six months",
        "relevantExperience": "Relevant projects",
        "eligibilityCompliance": "Requirements met",
        "strengths": ["Clear plan"],
        "weaknesses": [],
        "missingInformation": [],
        "riskIndicators": [],
        "technicalComplianceScore": 80,
        "priceCompetitivenessScore": 80,
        "relevantExperienceScore": 80,
        "deliveryTimelineScore": 80,
        "eligibilityDocumentationScore": 80,
        "evidenceSummary": "Based on submitted information.",
    }
    return {
        "response": {"content": json.dumps({"vendors": [vendor]})},
        "verification": {
            "mode": "test",
            "model": bidveil.MODEL_NAME,
            "nonce": "test-nonce",
            "attestationVerified": False,
            "gatewayVerified": False,
            "modelVerified": False,
            "responseSignatureKind": "unavailable",
            "completionId": None,
            "status": "No external attestation was performed by the test stub.",
        },
    }


def test_extracts_txt(tmp_path):
    text, status = bidveil.extract_uploaded_document(
        file_upload(b"\xef\xbb\xbfBid data in UTF-8", "bid.txt", "text/plain"),
        tmp_path,
        0,
        0,
    )

    assert text == "Bid data in UTF-8"
    assert status["status"] == "extracted"
    assert status["characters"] > 0


def test_extracts_pdf_text(tmp_path):
    text, status = bidveil.extract_uploaded_document(
        file_upload(make_text_pdf(), "bid.pdf", "application/pdf"),
        tmp_path,
        0,
        0,
    )

    assert "Readable bid proposal text" in text
    assert status["status"] == "extracted"


@pytest.mark.parametrize(
    ("data", "filename", "content_type", "message"),
    [
        (b"data", "bid.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "Only PDF"),
        (b"data", "bid.pdf", "text/plain", "does not match"),
        (b"", "bid.txt", "text/plain", "empty"),
        (b"\xff\xfe", "bid.txt", "text/plain", "UTF-8"),
        (b"%PDF-not-a-pdf", "bid.pdf", "application/pdf", "corrupted"),
    ],
)
def test_rejects_invalid_documents(tmp_path, data, filename, content_type, message):
    with pytest.raises(ValueError, match=message):
        bidveil.extract_uploaded_document(
            file_upload(data, filename, content_type),
            tmp_path,
            0,
            0,
        )


def test_rejects_encrypted_pdf(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("secret")
    encrypted = BytesIO()
    writer.write(encrypted)

    with pytest.raises(ValueError, match="Encrypted"):
        bidveil.extract_uploaded_document(
            file_upload(encrypted.getvalue(), "locked.pdf", "application/pdf"),
            tmp_path,
            0,
            0,
        )


def test_rejects_text_empty_pdf(tmp_path):
    with pytest.raises(ValueError, match="No readable text"):
        bidveil.extract_uploaded_document(
            file_upload(make_text_pdf(""), "empty.pdf", "application/pdf"),
            tmp_path,
            0,
            0,
        )


def test_rejects_document_over_size_limit(tmp_path):
    oversized = b"x" * (bidveil.MAX_DOCUMENT_BYTES + 1)

    with pytest.raises(ValueError, match="10 MB"):
        bidveil.extract_uploaded_document(
            file_upload(oversized, "large.txt", "text/plain"),
            tmp_path,
            0,
            0,
        )


def test_successful_evaluation_uses_extracted_text_and_cleans_temp_files(
    tmp_path, monkeypatch
):
    prompts = []

    async def fake_near_ai(prompt, nonce, on_verifying=None):
        prompts.append(prompt)
        if on_verifying:
            on_verifying()
        return sample_ai_output_for_test()

    monkeypatch.setattr(bidveil, "call_near_ai", fake_near_ai)
    payload = bid_payload()
    upload = file_upload(
        make_text_pdf("Confidential quote 123"),
        "quote.pdf",
        "application/pdf",
    )
    uploads = {
        0: [upload]
    }

    result, status = bidveil.process_evaluation(payload, uploads, str(tmp_path))

    assert status == 200
    assert "Confidential quote 123" in prompts[0]
    assert result["documents"][0]["status"] == "extracted"
    assert result["processing"][-1]["state"] == "cleanup_completed"
    assert list(tmp_path.iterdir()) == []
    assert "documents" not in payload["bids"][0]
    assert uploads == {}
    assert upload.stream.closed


def test_failed_inference_cleans_temp_files(tmp_path, monkeypatch):
    async def failing_near_ai(_prompt, _nonce, _on_verifying=None):
        raise RuntimeError("upstream request failed")

    monkeypatch.setattr(bidveil, "call_near_ai", failing_near_ai)
    result, status = bidveil.process_evaluation(
        bid_payload(),
        {0: [file_upload(b"bid contents", "bid.txt", "text/plain")]},
        str(tmp_path),
    )

    assert status == 502
    assert result["processing"][-1]["state"] == "cleanup_completed"
    assert result["verification"]["attestationVerified"] is False
    assert list(tmp_path.iterdir()) == []


def test_extraction_failure_cleans_temp_files(tmp_path):
    result, status = bidveil.process_evaluation(
        bid_payload(),
        {0: [file_upload(b"not pdf", "bid.pdf", "application/pdf")]},
        str(tmp_path),
    )

    assert status == 422
    assert result["documents"][0]["status"] == "failed"
    assert result["processing"][-1]["state"] == "cleanup_completed"
    assert list(tmp_path.iterdir()) == []


def test_concurrent_evaluations_use_isolated_temporary_directories(tmp_path, monkeypatch):
    async def fake_near_ai(_prompt, _nonce, on_verifying=None):
        if on_verifying:
            on_verifying()
        return sample_ai_output_for_test()

    monkeypatch.setattr(bidveil, "call_near_ai", fake_near_ai)

    def run_one(index):
        return bidveil.process_evaluation(
            bid_payload(f"Vendor {index}"),
            {
                0: [
                    file_upload(
                        f"Private content {index}".encode("utf-8"),
                        f"bid-{index}.txt",
                        "text/plain",
                    )
                ]
            },
            str(tmp_path),
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(run_one, range(4)))

    assert all(status == 200 for _result, status in results)
    assert all(
        result["processing"][-1]["state"] == "cleanup_completed"
        for result, _status in results
    )
    assert list(tmp_path.iterdir()) == []


def test_multipart_evaluation_route_extracts_and_returns_status(monkeypatch):
    async def fake_near_ai(_prompt, _nonce, on_verifying=None):
        if on_verifying:
            on_verifying()
        return sample_ai_output_for_test()

    monkeypatch.setattr(bidveil, "call_near_ai", fake_near_ai)
    client = bidveil.app.test_client()
    response = client.post(
        "/api/evaluate",
        data={
            "payload": json.dumps(bid_payload()),
            "bid_0": (BytesIO(b"Plain text bid"), "bid.txt", "text/plain"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["documents"][0]["status"] == "extracted"
    assert body["processing"][-1]["state"] == "cleanup_completed"


def test_stream_endpoint_reports_processing_stages_in_order(monkeypatch):
    async def fake_near_ai(_prompt, _nonce, on_verifying=None):
        if on_verifying:
            on_verifying()
        return sample_ai_output_for_test()

    monkeypatch.setattr(bidveil, "call_near_ai", fake_near_ai)
    response = bidveil.app.test_client().post(
        "/api/evaluate/stream",
        data={
            "payload": json.dumps(bid_payload()),
            "bid_0": (BytesIO(b"Plain text bid"), "bid.txt", "text/plain"),
        },
        content_type="multipart/form-data",
        buffered=True,
    )

    assert response.status_code == 200
    events = [
        json.loads(line[6:])
        for line in response.get_data(as_text=True).splitlines()
        if line.startswith("data: ")
    ]
    states = [event["status"] for event in events if event["type"] == "state"]

    assert states == [
        "Extracting document",
        "Extracted document: bid.txt",
        "Preparing confidential analysis",
        "Verifying attestation",
        "Evaluation completed",
        "Cleanup completed",
    ]
    assert events[-1]["type"] == "result"
    assert events[-1]["result"]["vendors"]


def test_unconfigured_near_service_never_returns_fabricated_scores(monkeypatch):
    monkeypatch.delenv("NEARAI_API_KEY", raising=False)
    response = bidveil.app.test_client().post(
        "/api/evaluate",
        json=bid_payload(),
    )

    assert response.status_code == 503
    body = response.get_json()
    assert "vendors" not in body
    assert body["verification"]["attestationVerified"] is False
    assert body["processing"][-1]["state"] == "cleanup_completed"


def test_health_endpoint_reports_service_configuration(monkeypatch):
    monkeypatch.delenv("NEARAI_API_KEY", raising=False)
    response = bidveil.app.test_client().get("/api/health")

    assert response.status_code == 200
    body = response.get_json()
    assert body["teeMode"] == "unconfigured"
    assert body["apiConfigured"] is False
    assert body["status"] == "ok"
    assert isinstance(body["model"], str) and body["model"]
    assert isinstance(body["verificationStates"], list)
    assert near_ai.STATE_MODEL_TEE_VERIFIED in body["verificationStates"]
    assert near_ai.STATE_VERIFICATION_UNAVAILABLE in body["verificationStates"]


def test_health_endpoint_reports_configured_key(monkeypatch):
    monkeypatch.setenv("NEARAI_API_KEY", "test-key")
    response = bidveil.app.test_client().get("/api/health")

    assert response.status_code == 200
    body = response.get_json()
    assert body["apiConfigured"] is True
    assert body["teeMode"] == "live"
