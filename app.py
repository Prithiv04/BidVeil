import asyncio
import json
import os
import re
import tempfile
import queue
import threading
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from pypdf import PdfReader
from werkzeug.datastructures import FileStorage

import inference

load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

DEFAULT_WEIGHTS = {
    "technical_compliance": 0.30,
    "price_competitiveness": 0.25,
    "relevant_experience": 0.20,
    "delivery_timeline": 0.15,
    "eligibility_and_documentation": 0.10,
}

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_CHARACTERS_PER_DOCUMENT = 2_000_000
MAX_TOTAL_EXTRACTED_CHARACTERS = 10_000_000
MAX_PDF_PAGES = 1_000
MAX_DOCUMENTS_PER_BID = 10
MAX_VENDORS = 20


class DocumentInputError(Exception):
    def __init__(self, message: str, documents: list[dict[str, Any]]):
        super().__init__(message)
        self.documents = documents


class EvaluationServiceError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def generate_nonce() -> str:
    return inference.generate_nonce()


def parse_json_blob(content: str) -> Any:
    if not content:
        return None
    cleaned = content.strip()
    cleaned = cleaned.strip("`")
    if cleaned.startswith("json"):
        cleaned = cleaned[4:].strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()
    if cleaned.startswith("json"):
        cleaned = cleaned[4:].strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def normalize_bids(raw_bids: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    for bid in raw_bids or []:
        if not isinstance(bid, dict):
            continue
        vendor_name = str(bid.get("vendorName") or bid.get("name") or "Unnamed vendor").strip()
        proposal = bid.get("proposalText") or bid.get("proposal") or ""
        quoted_price = bid.get("quotedPrice") or bid.get("price") or 0
        if isinstance(quoted_price, str):
            try:
                quoted_price = float(quoted_price.replace(",", ""))
            except ValueError:
                quoted_price = 0.0
        cleaned.append(
            {
                "vendorName": vendor_name,
                "quotedPrice": float(quoted_price or 0),
                "proposalText": str(proposal),
                "documents": bid.get("documents") or [],
            }
        )
    return cleaned


def build_bid_context(tender: dict[str, Any], bids: list[dict[str, Any]]) -> str:
    source_docs = []
    for bid in bids:
        docs = bid.get("documents") or []
        if not docs:
            source_docs.append(f"Vendor {bid['vendorName']}: {bid.get('proposalText', '')}")
            continue
        text = "\n\n".join(str(doc.get("text") or "") for doc in docs if isinstance(doc, dict))
        if not text:
            text = bid.get("proposalText", "")
        source_docs.append(f"Vendor {bid['vendorName']}\n{text}")

    return json.dumps(
        {
            "tender": tender,
            "bids": source_docs,
        },
        ensure_ascii=False,
        indent=2,
    )


def build_evaluation_prompt(tender: dict[str, Any], bids: list[dict[str, Any]], nonce: str) -> str:
    context = build_bid_context(tender, bids)
    return f"""
You are an AI evaluator for confidential procurement assistance.

Task: analyze the tender and each vendor bid, then return structured evidence that can be turned into a deterministic procurement score.

IMPORTANT:
- Return valid JSON only.
- No markdown formatting, no commentary, no code fences.
- Use the exact schema below.
- The response must remain within one JSON object.
- Do not invent a legal decision; this is an AI-assisted decision support output.

Tender context:
{context}

Required JSON schema:
{{
  "vendors": [
    {{
      "vendorName": "string",
      "quotedPrice": 12345.67,
      "technicalCapabilities": "string",
      "deliveryTimeline": "string",
      "relevantExperience": "string",
      "eligibilityCompliance": "string",
      "strengths": ["string"],
      "weaknesses": ["string"],
      "missingInformation": ["string"],
      "riskIndicators": ["string"],
      "technicalComplianceScore": 0,
      "priceCompetitivenessScore": 0,
      "relevantExperienceScore": 0,
      "deliveryTimelineScore": 0,
      "eligibilityDocumentationScore": 0,
      "evidenceSummary": "string"
    }}
  ]
}}

Scoring instructions:
- Scores must be integers 0-100.
- Use the exact same values for the five final score fields as the compliant evidence summary.
- Keep bid data factual and grounded in the provided proposal text.
- Include a nonce value in the evidence summary for traceability: {nonce}
- If a field is missing or unclear, explicitly note it in missingInformation and lower the associated score.
"""


async def call_inference(
    prompt: str,
    nonce: str,
    on_verifying: Callable[[], None] | None = None,
) -> dict[str, Any]:
    def on_progress(stage: str) -> None:
        if on_verifying is not None and stage == "inference":
            on_verifying()

    try:
        result = await inference.run_inference(
            prompt,
            model=None,
            on_progress=on_progress,
        )
    except inference.InferenceUnavailableError as error:
        raise EvaluationServiceError(str(error), error.status_code) from error
    except inference.InferenceError as error:
        raise EvaluationServiceError(str(error), error.status_code) from error

    return {
        "response": {"content": result.content},
        "verification": result.verification,
    }


def compute_weighted_scores(vendors: list[dict[str, Any]], weights: dict[str, float]) -> list[dict[str, Any]]:
    ranked = []
    for vendor in vendors:
        scores = {
            "technical_compliance": float(vendor.get("technicalComplianceScore", 0) or 0),
            "price_competitiveness": float(vendor.get("priceCompetitivenessScore", 0) or 0),
            "relevant_experience": float(vendor.get("relevantExperienceScore", 0) or 0),
            "delivery_timeline": float(vendor.get("deliveryTimelineScore", 0) or 0),
            "eligibility_and_documentation": float(vendor.get("eligibilityDocumentationScore", 0) or 0),
        }
        total = 0.0
        for key, value in scores.items():
            total += value * float(weights.get(key, 0.0))
        vendor["criterionScores"] = scores
        vendor["weightedScore"] = round(total, 2)
        ranked.append(vendor)
    return sorted(ranked, key=lambda item: item["weightedScore"], reverse=True)


def derive_final_scores(vendors: list[dict[str, Any]], tender: dict[str, Any]) -> list[dict[str, Any]]:
    weights = tender.get("weights") or DEFAULT_WEIGHTS
    for vendor in vendors:
        quoted_price = float(vendor.get("quotedPrice", 0) or 0)
        max_budget = float(tender.get("maximumBudget", 0) or 0)
        normalized_price = 100.0
        if max_budget > 0 and quoted_price > 0:
            normalized_price = max(0.0, min(100.0, 100.0 - ((quoted_price / max_budget) * 100.0 - 100.0)))
        vendor["priceCompetitivenessScore"] = int(round(float(vendor.get("priceCompetitivenessScore", 0) or normalized_price)))
        vendor["technicalComplianceScore"] = int(float(vendor.get("technicalComplianceScore", 0) or 0))
        vendor["relevantExperienceScore"] = int(float(vendor.get("relevantExperienceScore", 0) or 0))
        vendor["deliveryTimelineScore"] = int(float(vendor.get("deliveryTimelineScore", 0) or 0))
        vendor["eligibilityDocumentationScore"] = int(float(vendor.get("eligibilityDocumentationScore", 0) or 0))
    return compute_weighted_scores(vendors, weights)


async def evaluate_bids(
    payload: dict[str, Any],
    on_verifying: Callable[[], None] | None = None,
) -> dict[str, Any]:
    tender = payload.get("tender") or {}
    bids = normalize_bids(payload.get("bids") or [])
    if not bids:
        raise EvaluationServiceError("Add at least one vendor bid before evaluation.", 400)

    nonce = generate_nonce()
    prompt = build_evaluation_prompt(tender, bids, nonce)
    ai_response = await call_inference(prompt, nonce, on_verifying)
    content = ai_response.get("response", {}).get("content") or "{}"
    parsed = parse_json_blob(content)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("vendors"), list):
        raise EvaluationServiceError("Inference provider returned an invalid evaluation response.")

    normalized = []
    for vendor in parsed.get("vendors") or []:
        if not isinstance(vendor, dict):
            continue
        vendor["quotedPrice"] = vendor.get("quotedPrice") or next((bid["quotedPrice"] for bid in bids if bid["vendorName"] == vendor.get("vendorName")), 0)
        if not vendor.get("vendorName"):
            vendor["vendorName"] = "Unnamed vendor"
        normalized.append(vendor)

    if not normalized:
        raise EvaluationServiceError("Inference provider returned no vendor evaluations.")

    ranked_vendors = derive_final_scores(normalized, tender)
    for index, vendor in enumerate(ranked_vendors, start=1):
        vendor["rank"] = index

    verification = ai_response.get("verification") or {}

    return {
        "tender": tender,
        "vendors": ranked_vendors,
        "verification": verification,
        "weights": tender.get("weights") or DEFAULT_WEIGHTS,
        "privacy": {
            "serverSideRetention": "BIDVEIL does not intentionally persist uploaded bid content, prompts, or inference responses.",
            "temporaryStorage": "Uploads are held in a unique request-scoped temporary directory and removed at request completion.",
            "memoryErasure": "Process memory is released by normal runtime lifecycle; cryptographic memory erasure is not guaranteed.",
            "externalProcessing": "Bid text is sent to an inference provider when configured. The provider's retention and processing policies are outside BIDVEIL's control.",
        },
        "summary": {
            "winner": ranked_vendors[0]["vendorName"] if ranked_vendors else "No vendor available",
            "averageScore": round(sum(v["weightedScore"] for v in ranked_vendors) / len(ranked_vendors), 2) if ranked_vendors else 0,
        },
    }


def extract_uploaded_document(
    upload: FileStorage,
    destination: Path,
    vendor_index: int,
    document_index: int,
) -> tuple[str, dict[str, Any]]:
    filename = upload.filename or ""
    extension = Path(filename).suffix.lower()
    display = {"vendorIndex": vendor_index, "fileName": filename or "unnamed file"}
    allowed_mimes = {
        ".pdf": {"application/pdf", "application/octet-stream"},
        ".txt": {"text/plain", "application/octet-stream"},
    }

    if extension not in allowed_mimes:
        raise ValueError("Only PDF and TXT documents are supported.")
    if (upload.mimetype or "").lower() not in allowed_mimes[extension]:
        raise ValueError("The file type does not match its extension.")

    data = upload.stream.read(MAX_DOCUMENT_BYTES + 1)
    if not data:
        raise ValueError("The document is empty.")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("The document exceeds the 10 MB per-file limit.")

    saved_path = destination / f"vendor-{vendor_index}-document-{document_index}{extension}"
    saved_path.write_bytes(data)

    if extension == ".txt":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("TXT documents must use UTF-8 encoding.") from error
    else:
        if not data.startswith(b"%PDF-"):
            raise ValueError("The file does not have a valid PDF header.")
        try:
            reader = PdfReader(str(saved_path), strict=True)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDFs are not supported.")
            if len(reader.pages) > MAX_PDF_PAGES:
                raise ValueError("PDFs with more than 1,000 pages are not supported.")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("The PDF is corrupted or could not be read.") from error

    if not text.strip():
        raise ValueError("No readable text was found in the document.")
    if len(text) > MAX_EXTRACTED_CHARACTERS_PER_DOCUMENT:
        raise ValueError("Extracted text exceeds the 2 million character per-file limit.")
    return text, {**display, "status": "extracted", "characters": len(text)}


def process_evaluation(
    payload: dict[str, Any],
    uploads_by_vendor: dict[int, list[FileStorage]],
    temp_root: str | None = None,
    progress_callback: Callable[[dict[str, str]], None] | None = None,
) -> tuple[dict[str, Any], int]:
    document_statuses: list[dict[str, Any]] = []
    has_uploads = any(uploads_by_vendor.values())
    processing: list[dict[str, str]] = []

    def emit(state: str, status: str) -> None:
        event = {"state": state, "status": status}
        processing.append(event)
        if progress_callback is not None:
            progress_callback(event)

    def close_uploads() -> None:
        for uploads in uploads_by_vendor.values():
            for upload in uploads:
                upload.close()

    if has_uploads:
        emit("extracting", "Extracting document")
    result: dict[str, Any] | None = None
    response_status = 200
    failure: str | None = None
    temp_directory_path: Path | None = None
    upload_cleanup_completed = True

    try:
        with tempfile.TemporaryDirectory(prefix="bidveil-", dir=temp_root) as request_dir:
            temp_directory_path = Path(request_dir)
            total_extracted_characters = 0
            bids = payload.get("bids") or []
            if not isinstance(bids, list) or len(bids) > MAX_VENDORS:
                raise DocumentInputError(
                    "A maximum of 20 vendor bids is supported.", document_statuses
                )
            if any(not isinstance(bid, dict) for bid in bids):
                raise DocumentInputError(
                    "Each vendor bid must be an object.", document_statuses
                )
            for vendor_index, uploads in uploads_by_vendor.items():
                if vendor_index < 0 or vendor_index >= len(bids):
                    raise DocumentInputError(
                        "A document was submitted for an unknown vendor.", document_statuses
                    )
                if len(uploads) > MAX_DOCUMENTS_PER_BID:
                    raise DocumentInputError(
                        "A maximum of 10 documents per vendor is supported.", document_statuses
                    )

            for vendor_index, uploads in uploads_by_vendor.items():
                for document_index, upload in enumerate(uploads):
                    try:
                        text, status = extract_uploaded_document(
                            upload,
                            Path(request_dir),
                            vendor_index,
                            document_index,
                        )
                    except ValueError as error:
                        document_statuses.append(
                            {
                                "vendorIndex": vendor_index,
                                "fileName": upload.filename or "unnamed file",
                                "status": "failed",
                                "message": str(error),
                            }
                        )
                        raise DocumentInputError(
                            "One or more documents could not be extracted.",
                            document_statuses,
                        ) from error
                    total_extracted_characters += len(text)
                    if total_extracted_characters > MAX_TOTAL_EXTRACTED_CHARACTERS:
                        document_statuses.append(
                            {
                                "vendorIndex": vendor_index,
                                "fileName": upload.filename or "unnamed file",
                                "status": "failed",
                                "message": "Combined extracted text exceeds the 10 million character request limit.",
                            }
                        )
                        raise DocumentInputError(
                            "Combined extracted text exceeds the request limit.",
                            document_statuses,
                        )
                    document_statuses.append(status)
                    emit("extracting", f"Extracted document: {status['fileName']}")
                    bids[vendor_index].setdefault("documents", []).append(
                        {"text": text}
                    )

            close_uploads()
            uploads_by_vendor.clear()
            emit("preparing", "Preparing confidential analysis")

            def mark_verifying() -> None:
                emit("verifying", "Running inference")

            result = asyncio.run(evaluate_bids(payload, mark_verifying))
            verification = result.get("verification") or {}
            emit("evaluation_completed", "Evaluation completed")
    except DocumentInputError as error:
        failure = str(error)
        document_statuses = error.documents
        response_status = 422
        emit("failed", "Failed / verification unavailable")
    except EvaluationServiceError as error:
        failure = str(error)
        response_status = error.status_code
        emit("verification_unavailable", "Failed / verification unavailable")
    except Exception:
        failure = "Evaluation failed; verification is unavailable."
        response_status = 502
        emit("verification_unavailable", "Failed / verification unavailable")
    finally:
        payload_bids = payload.get("bids")
        if isinstance(payload_bids, list):
            for bid in payload_bids:
                if isinstance(bid, dict):
                    bid.pop("documents", None)
        try:
            close_uploads()
        except Exception:
            upload_cleanup_completed = False
            failure = "Temporary upload cleanup could not be confirmed."
            response_status = 500
        uploads_by_vendor.clear()

    temp_cleanup_completed = (
        temp_directory_path is None or not temp_directory_path.exists()
    )
    cleanup_completed = upload_cleanup_completed and temp_cleanup_completed
    if cleanup_completed:
        emit("cleanup_completed", "Cleanup completed")
    else:
        emit("cleanup_failed", "Cleanup could not be confirmed")
        failure = failure or "Temporary processing cleanup could not be confirmed."
        response_status = 500
    if failure:
        return {
            "error": failure,
            "documents": document_statuses,
            "processing": processing,
            "verification": inference.empty_verification(
                state=inference.STATE_INFERENCE_UNAVAILABLE
                if response_status in {503, 504}
                else inference.STATE_INFERENCE_FAILED,
                status="Inference unavailable",
                failure_reason=failure,
            ),
        }, response_status

    assert result is not None
    result["documents"] = document_statuses
    result["processing"] = processing
    result["privacy"]["temporaryStorage"] = (
        "The request-scoped temporary directory was removed before this response."
    )
    return result, 200


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health", methods=["GET"])
def healthcheck():
    return jsonify({
        "status": "ok",
        "inferenceProvider": "none",
    })


def evaluation_request():
    if request.mimetype == "multipart/form-data":
        try:
            payload = json.loads(request.form.get("payload", "{}"))
        except json.JSONDecodeError:
            return None, None, (jsonify({"error": "Evaluation payload must be valid JSON."}), 400)
        uploads_by_vendor: dict[int, list[FileStorage]] = {}
        for key in request.files:
            match = re.fullmatch(r"bid_(\d+)", key)
            if not match:
                return None, None, (jsonify({"error": "Unexpected uploaded file field."}), 400)
            uploads_by_vendor[int(match.group(1))] = request.files.getlist(key)
    else:
        payload = request.get_json(silent=True) or {}
        uploads_by_vendor = {}
        if isinstance(payload, dict):
            payload_bids = payload.get("bids", [])
            if isinstance(payload_bids, list) and any(
                isinstance(bid, dict) and bid.get("documents")
                for bid in payload_bids
            ):
                return None, None, (
                    jsonify(
                        {"error": "Upload PDF and TXT documents as multipart files, not embedded text."}
                    ),
                    400,
                )

    if not isinstance(payload, dict):
        return None, None, (jsonify({"error": "Evaluation payload must be an object."}), 400)
    return payload, uploads_by_vendor, None


@app.route("/api/evaluate", methods=["POST"])
def evaluate_route():
    payload, uploads_by_vendor, error_response = evaluation_request()
    if error_response:
        return error_response
    result, status_code = process_evaluation(payload, uploads_by_vendor)
    return jsonify(result), status_code


@app.route("/api/evaluate/stream", methods=["POST"])
def evaluate_stream_route():
    payload, uploads_by_vendor, error_response = evaluation_request()
    if error_response:
        return error_response

    events: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def run_evaluation() -> None:
        try:
            result, status_code = process_evaluation(
                payload,
                uploads_by_vendor,
                progress_callback=events.put,
            )
        except Exception:
            result = {
                "error": "Evaluation failed; inference is unavailable.",
                "verification": inference.empty_verification(
                    state=inference.STATE_INFERENCE_UNAVAILABLE,
                    status="Inference unavailable",
                    failure_reason="Evaluation failed; inference is unavailable.",
                ),
                "processing": [
                    {"state": "failed", "status": "Failed / inference unavailable"},
                    {"state": "cleanup_completed", "status": "Cleanup completed"},
                ],
            }
            status_code = 502
        events.put(
            {"type": "result", "statusCode": status_code, "result": result}
        )
        events.put(None)

    threading.Thread(target=run_evaluation, daemon=True).start()

    @stream_with_context
    def stream_events():
        while True:
            event = events.get()
            if event is None:
                break
            event_type = event.get("type", "state")
            yield f"data: {json.dumps({**event, 'type': event_type})}\n\n"

    response = Response(stream_events(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({
        "error": "The upload exceeds the 50 MB request limit.",
        "processing": [
            {"state": "failed", "status": "Failed / inference unavailable"},
            {"state": "cleanup_completed", "status": "Cleanup completed"},
        ],
        "verification": inference.empty_verification(
            state=inference.STATE_INFERENCE_UNAVAILABLE,
            status="Request rejected before evaluation.",
            failure_reason="The upload exceeds the 50 MB request limit.",
        ),
    }), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
