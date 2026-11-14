import asyncio
import hashlib
import json
import math
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
import criteria
import storage
import sam_gov

load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="static")

# Security configuration
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY") or os.urandom(32)
app.config["DATABASE_PATH"] = os.environ.get("BIDVEIL_DB_PATH") or str(
    Path(app.instance_path) / "bidveil.sqlite3"
)

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

storage.initialize_database()


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
        quoted_price = bid.get("quotedPrice") or bid.get("price") or 0
        if isinstance(quoted_price, str):
            try:
                quoted_price = float(quoted_price.replace(",", ""))
            except ValueError as error:
                raise EvaluationServiceError(
                    f"Vendor '{vendor_name}' has an invalid quoted price.", 400
                ) from error
        if isinstance(quoted_price, bool):
            raise EvaluationServiceError(
                f"Vendor '{vendor_name}' has an invalid quoted price.", 400
            )
        try:
            quoted_price = float(quoted_price or 0)
        except (TypeError, ValueError) as error:
            raise EvaluationServiceError(
                f"Vendor '{vendor_name}' has an invalid quoted price.", 400
            ) from error
        if not math.isfinite(quoted_price) or quoted_price < 0:
            raise EvaluationServiceError(
                f"Vendor '{vendor_name}' quoted price must be a finite, non-negative number.", 400
            )
        cleaned_bid = {
            "vendorName": vendor_name,
            "quotedPrice": quoted_price,
            "documents": bid.get("documents") or [],
            "ueiSAM": str(bid.get("ueiSAM") or "").strip(),
        }
        # Preserve manual scores if present
        if "scores" in bid:
            cleaned_bid["scores"] = bid["scores"]
        # Preserve evidence fields if present
        if "evidence" in bid:
            cleaned_bid["evidence"] = bid["evidence"]
        if "strengths" in bid:
            cleaned_bid["strengths"] = bid["strengths"]
        if "weaknesses" in bid:
            cleaned_bid["weaknesses"] = bid["weaknesses"]
        if "missingInformation" in bid:
            cleaned_bid["missingInformation"] = bid["missingInformation"]
        if "riskIndicators" in bid:
            cleaned_bid["riskIndicators"] = bid["riskIndicators"]
        cleaned.append(cleaned_bid)
    return cleaned


def build_bid_context(tender: dict[str, Any], bids: list[dict[str, Any]]) -> str:
    tender_data = {key: value for key, value in tender.items() if key != "documents"}
    return json.dumps(
        {
            "tender": tender_data,
            "tenderDocuments": [
                {"fileName": doc.get("fileName", "tender document"), "text": doc.get("text", "")}
                for doc in (tender.get("documents") or [])
                if isinstance(doc, dict)
            ],
            "bids": [
                {
                    "vendorName": bid["vendorName"],
                    "quotedPrice": bid["quotedPrice"],
                    "documents": [
                        {"fileName": doc.get("fileName", "bid document"), "text": doc.get("text", "")}
                        for doc in (bid.get("documents") or [])
                        if isinstance(doc, dict)
                    ],
                }
                for bid in bids
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def build_evaluation_prompt(tender: dict[str, Any], bids: list[dict[str, Any]], nonce: str) -> str:
    context = build_bid_context(tender, bids)
    criteria_config = tender.get("criteria") or criteria.DEFAULT_CRITERIA
    return json.dumps(
        {
            "evaluationNonce": nonce,
            "task": "Evaluate each supplied bid against the tender and configured criteria. Quote evidence only from that vendor's uploaded proposal documents. Do not invent missing bid content.",
            "criteria": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "description": item["description"],
                    "weight": item["weight"],
                }
                for item in criteria_config
            ],
            "sourceMaterial": json.loads(context),
        },
        ensure_ascii=False,
        indent=2,
    )


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
        raw_scores = vendor.get("scores") or {
            "technical_compliance": vendor.get("technicalComplianceScore", 0),
            "price_competitiveness": vendor.get("priceCompetitivenessScore", 0),
            "relevant_experience": vendor.get("relevantExperienceScore", 0),
            "delivery_timeline": vendor.get("deliveryTimelineScore", 0),
            "eligibility_and_documentation": vendor.get("eligibilityDocumentationScore", 0),
        }
        scores = {key: float(raw_scores.get(key, 0) or 0) for key in weights}
        total = 0.0
        for key, value in scores.items():
            total += value * float(weights.get(key, 0.0))
        vendor["scores"] = scores
        vendor["criterionScores"] = scores
        vendor["weightedScore"] = round(total, 2)
        ranked.append(vendor)
    return sorted(ranked, key=lambda item: item["weightedScore"], reverse=True)


def derive_final_scores(vendors: list[dict[str, Any]], tender: dict[str, Any]) -> list[dict[str, Any]]:
    criteria_config = tender.get("criteria") or criteria.DEFAULT_CRITERIA
    valid, error = criteria.validate_criteria_config(criteria_config)
    if not valid:
        raise EvaluationServiceError(f"Invalid criteria configuration: {error}", 400)
    weights = criteria.get_criteria_weights(criteria_config)
    for vendor in vendors:
        quoted_price = float(vendor.get("quotedPrice", 0) or 0)
        max_budget = float(tender.get("maximumBudget", 0) or 0)
        scores = dict(vendor.get("scores") or {})
        for criterion in criteria_config:
            criterion_id = criterion["id"]
            if criterion.get("auto_calculated") and criterion_id == "price_competitiveness":
                scores[criterion_id] = criteria.normalize_price_score(quoted_price, max_budget)
            elif criterion_id not in scores:
                scores[criterion_id] = 0
        vendor["scores"] = scores
        vendor["technicalComplianceScore"] = scores.get("technical_compliance", 0)
        vendor["priceCompetitivenessScore"] = scores.get("price_competitiveness", 0)
        vendor["relevantExperienceScore"] = scores.get("relevant_experience", 0)
        vendor["deliveryTimelineScore"] = scores.get("delivery_timeline", 0)
        vendor["eligibilityDocumentationScore"] = scores.get("eligibility_and_documentation", 0)
    return compute_weighted_scores(vendors, weights)


async def evaluate_bids(
    payload: dict[str, Any],
    on_verifying: Callable[[], None] | None = None,
) -> dict[str, Any]:
    tender = payload.get("tender") or {}
    bids = normalize_bids(payload.get("bids") or [])
    if not bids:
        raise EvaluationServiceError("Add at least one vendor bid before evaluation.", 400)

    tender_text = " ".join(
        [
            str(tender.get("description") or ""),
            str(tender.get("technicalRequirements") or ""),
            str(tender.get("eligibilityRequirements") or ""),
            str(tender.get("evaluationCriteria") or ""),
            *[str(doc.get("text") or "") for doc in tender.get("documents", []) if isinstance(doc, dict)],
        ]
    ).strip()
    if not tender_text:
        raise EvaluationServiceError(
            "Provide tender requirements or upload a tender document before AI evaluation.", 400
        )
    criteria_config = tender.get("criteria") or criteria.DEFAULT_CRITERIA
    valid_criteria, criteria_error = criteria.validate_criteria_config(criteria_config)
    if not valid_criteria:
        raise EvaluationServiceError(f"Invalid criteria configuration: {criteria_error}", 400)
    names = [bid["vendorName"].casefold() for bid in bids]
    if len(names) != len(set(names)):
        raise EvaluationServiceError("Vendor names must be unique for evaluation records.", 400)
    for bid in bids:
        has_documents = any(str(doc.get("text") or "").strip() for doc in bid.get("documents", []) if isinstance(doc, dict))
        if not has_documents:
            raise EvaluationServiceError(
                f"Vendor '{bid['vendorName']}' needs at least one readable uploaded proposal document.", 400
            )

    nonce = generate_nonce()
    prompt = build_evaluation_prompt(tender, bids, nonce)
    ai_response = await call_inference(prompt, nonce, on_verifying)
    content = ai_response.get("response", {}).get("content") or "{}"
    parsed = parse_json_blob(content)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("vendors"), list):
        raise EvaluationServiceError("Inference provider returned an invalid evaluation response.")

    model_vendors = parsed.get("vendors") or []
    if len(model_vendors) != len(bids):
        raise EvaluationServiceError("OpenAI returned an incomplete or extra vendor evaluation.")
    by_name = {bid["vendorName"]: bid for bid in bids}
    normalized = []
    required_assessments = {
        criterion["id"]
        for criterion in criteria_config
        if not criterion.get("auto_calculated")
    }
    for model_vendor in model_vendors:
        if not isinstance(model_vendor, dict) or model_vendor.get("vendorName") not in by_name:
            raise EvaluationServiceError("OpenAI returned a vendor that was not submitted.")
        bid = by_name[model_vendor["vendorName"]]
        assessments = model_vendor.get("criteriaAssessments")
        if not isinstance(assessments, list):
            raise EvaluationServiceError(f"OpenAI omitted criterion assessments for {bid['vendorName']}.")
        assessment_map = {}
        source_text = " ".join(
            str(doc.get("text") or "")
            for doc in bid.get("documents", [])
            if isinstance(doc, dict)
        )
        normalized_source = " ".join(source_text.split()).casefold()
        for assessment in assessments:
            if not isinstance(assessment, dict):
                raise EvaluationServiceError("OpenAI returned a malformed criterion assessment.")
            criterion_id = assessment.get("criterionId")
            score = assessment.get("score")
            if criterion_id not in required_assessments or criterion_id in assessment_map:
                raise EvaluationServiceError("OpenAI returned duplicate or unknown evaluation criteria.")
            if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
                raise EvaluationServiceError("OpenAI returned a criterion score outside the 0–100 range.")
            quotes = assessment.get("evidenceQuotes")
            if not isinstance(quotes, list):
                raise EvaluationServiceError("OpenAI returned malformed evidence quotations.")
            for quote in quotes:
                normalized_quote = " ".join(str(quote).split()).casefold()
                if not normalized_quote or normalized_quote not in normalized_source:
                    raise EvaluationServiceError(
                        f"OpenAI returned evidence for {bid['vendorName']} that could not be matched to the submitted proposal."
                    )
            assessment_map[criterion_id] = {
                "score": score,
                "rationale": str(assessment.get("rationale") or ""),
                "evidenceQuotes": [str(quote) for quote in quotes],
            }
        if set(assessment_map) != required_assessments:
            raise EvaluationServiceError(f"OpenAI omitted one or more criteria for {bid['vendorName']}.")
        model_vendor["quotedPrice"] = bid["quotedPrice"]
        model_vendor["scores"] = {key: item["score"] for key, item in assessment_map.items()}
        model_vendor["evidence"] = assessment_map
        model_vendor["externalData"] = bid.get("externalData")
        normalized.append(model_vendor)

    ranked_vendors = derive_final_scores(normalized, tender)
    for vendor in ranked_vendors:
        for criterion in criteria_config:
            if criterion.get("auto_calculated"):
                vendor.setdefault("evidence", {})[criterion["id"]] = {
                    "score": vendor["scores"].get(criterion["id"], 0),
                    "rationale": "Automatically calculated by BIDVEIL from the submitted quoted price and tender budget using the configured price normalization rule.",
                    "evidenceQuotes": [],
                }
    for index, vendor in enumerate(ranked_vendors, start=1):
        vendor["rank"] = index

    verification = ai_response.get("verification") or {}

    return {
        "tender": tender,
        "vendors": ranked_vendors,
        "overallRecommendation": str(parsed.get("overallRecommendation") or ""),
        "verification": verification,
        "weights": criteria.get_criteria_weights(tender.get("criteria") or criteria.DEFAULT_CRITERIA),
        "evaluationMode": "ai",
        "privacy": {
            "serverSideRetention": "Source documents, extracted proposal text, prompts, and raw provider responses are not persisted. Derived scores, rationales, evidence quotations, recommendations, and document hashes are stored in the evaluation record.",
            "temporaryStorage": "Uploads are held in a unique request-scoped temporary directory and removed at request completion.",
            "memoryErasure": "Process memory is released by normal runtime lifecycle; cryptographic memory erasure is not guaranteed.",
            "externalProcessing": "Bid text is sent to an inference provider when configured. The provider's retention and processing policies are outside BIDVEIL's control.",
        },
        "summary": {
            "winner": ranked_vendors[0]["vendorName"] if ranked_vendors else "No vendor available",
            "averageScore": round(sum(v["weightedScore"] for v in ranked_vendors) / len(ranked_vendors), 2) if ranked_vendors else 0,
        },
    }


def evaluate_manual_scores(payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate bids using manually entered scores (no AI required).

    This function:
    1. Validates criteria configuration
    2. Normalizes and validates vendor scores
    3. Auto-calculates price scores if not provided
    4. Applies weighted scoring using the existing scoring engine
    5. Returns ranked results

    Args:
        payload: Evaluation payload with tender, bids, and manual scores

    Returns:
        Evaluation result with ranked vendors and metadata

    Raises:
        EvaluationServiceError: If validation fails
    """
    tender = payload.get("tender") or {}
    bids = normalize_bids(payload.get("bids") or [])

    if not bids:
        raise EvaluationServiceError("Add at least one vendor bid before evaluation.", 400)

    # Get criteria configuration (use default if not provided)
    criteria_config = tender.get("criteria") or criteria.DEFAULT_CRITERIA

    # Validate criteria configuration
    valid, error = criteria.validate_criteria_config(criteria_config)
    if not valid:
        raise EvaluationServiceError(f"Invalid criteria configuration: {error}", 400)

    # Extract weights from criteria
    weights = criteria.get_criteria_weights(criteria_config)

    # Validate and normalize each vendor's scores
    for bid in bids:
        try:
            criteria.normalize_vendor_scores(bid, criteria_config, tender)
        except ValueError as e:
            vendor_name = bid.get("vendorName", "Unnamed vendor")
            raise EvaluationServiceError(f"Vendor '{vendor_name}': {str(e)}", 400) from e

    # Map scores to the format expected by derive_final_scores
    for bid in bids:
        scores = bid.get("scores", {})
        bid["technicalComplianceScore"] = scores.get("technical_compliance", 0)
        bid["priceCompetitivenessScore"] = scores.get("price_competitiveness", 0)
        bid["relevantExperienceScore"] = scores.get("relevant_experience", 0)
        bid["deliveryTimelineScore"] = scores.get("delivery_timeline", 0)
        bid["eligibilityDocumentationScore"] = scores.get("eligibility_and_documentation", 0)

    # Use the existing scoring engine
    ranked_vendors = derive_final_scores(bids, tender)
    for index, vendor in enumerate(ranked_vendors, start=1):
        vendor["rank"] = index

    # Preserve evidence and justification fields
    for bid in bids:
        vendor_name = bid.get("vendorName")
        for ranked_vendor in ranked_vendors:
            if ranked_vendor.get("vendorName") == vendor_name:
                ranked_vendor["evidence"] = bid.get("evidence", {})
                ranked_vendor["strengths"] = bid.get("strengths", [])
                ranked_vendor["weaknesses"] = bid.get("weaknesses", [])
                ranked_vendor["missingInformation"] = bid.get("missingInformation", [])
                ranked_vendor["riskIndicators"] = bid.get("riskIndicators", [])
                break

    return {
        "tender": tender,
        "vendors": ranked_vendors,
        "verification": {
            "mode": "manual",
            "state": "MANUAL_COMPLETED",
            "status": "Manual evaluation completed; no AI inference was used.",
            "model": "none",
        },
        "weights": weights,
        "evaluationMode": "manual",
        "privacy": {
            "serverSideRetention": "Source documents and extracted text are not persisted. Manual scores, reviewer-entered rationale, evaluation metadata, and document hashes are stored in the evaluation record.",
            "temporaryStorage": "Uploads are held in a unique request-scoped temporary directory and removed at request completion.",
            "memoryErasure": "Process memory is released by normal runtime lifecycle; cryptographic memory erasure is not guaranteed.",
            "externalProcessing": "Manual evaluation does not send data to external inference providers.",
        },
        "summary": {
            "winner": ranked_vendors[0]["vendorName"] if ranked_vendors else "No vendor available",
            "averageScore": round(sum(v["weightedScore"] for v in ranked_vendors) / len(ranked_vendors), 2) if ranked_vendors else 0,
        },
    }


def extract_uploaded_document(
    upload: FileStorage,
    destination: Path,
    vendor_index: int | None,
    document_index: int,
    scope: str = "vendor",
) -> tuple[str, dict[str, Any]]:
    filename = upload.filename or ""
    extension = Path(filename).suffix.lower()
    display = {"scope": scope, "fileName": filename or "unnamed file"}
    if vendor_index is not None:
        display["vendorIndex"] = vendor_index
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

    prefix = "tender" if scope == "tender" else f"vendor-{vendor_index}"
    saved_path = destination / f"{prefix}-document-{document_index}{extension}"
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
    return text, {
        **display,
        "status": "extracted",
        "characters": len(text),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


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
            tender = payload.setdefault("tender", {})
            if not isinstance(tender, dict):
                raise DocumentInputError("Tender configuration must be an object.", document_statuses)
            for vendor_index, uploads in uploads_by_vendor.items():
                if vendor_index == -1:
                    if len(uploads) > MAX_DOCUMENTS_PER_BID:
                        raise DocumentInputError(
                            "A maximum of 10 tender documents is supported.", document_statuses
                        )
                    continue
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
                    is_tender_document = vendor_index == -1
                    try:
                        text, status = extract_uploaded_document(
                            upload,
                            Path(request_dir),
                            None if is_tender_document else vendor_index,
                            document_index,
                            scope="tender" if is_tender_document else "vendor",
                        )
                    except ValueError as error:
                        document_statuses.append(
                            {
                                "scope": "tender" if is_tender_document else "vendor",
                                **({} if is_tender_document else {"vendorIndex": vendor_index}),
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
                                "scope": "tender" if is_tender_document else "vendor",
                                **({} if is_tender_document else {"vendorIndex": vendor_index}),
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
                    if is_tender_document:
                        tender.setdefault("documents", []).append(
                            {"fileName": status["fileName"], "text": text}
                        )
                    else:
                        bids[vendor_index].setdefault("documents", []).append(
                            {"fileName": status["fileName"], "text": text}
                        )

            close_uploads()
            uploads_by_vendor.clear()
            emit("preparing", "Preparing evaluation")

            external_data_by_vendor: dict[str, dict[str, Any]] = {}
            for bid in bids:
                # Ignore client-asserted registry data; only attach server-fetched results.
                bid.pop("externalData", None)
                uei = str(bid.get("ueiSAM") or "").strip()
                if uei:
                    vendor_name = str(bid.get("vendorName") or bid.get("name") or "Unnamed vendor").strip()
                    external_data_by_vendor[vendor_name] = sam_gov.lookup_entity(uei)

            # Determine evaluation mode
            evaluation_mode = payload.get("evaluationMode", "auto")

            if evaluation_mode == "manual":
                # Manual evaluation - no AI required
                emit("scoring", "Calculating weighted scores")
                result = evaluate_manual_scores(payload)
                verification = result.get("verification") or {}
                emit("evaluation_completed", "Evaluation completed")
            else:
                # AI-assisted evaluation (default)
                def mark_verifying() -> None:
                    emit("verifying", "Running inference")

                result = asyncio.run(evaluate_bids(payload, mark_verifying))
                verification = result.get("verification") or {}
                emit("evaluation_completed", "Evaluation completed")
            for vendor in result.get("vendors", []):
                external = external_data_by_vendor.get(vendor.get("vendorName"))
                if external is not None:
                    vendor["externalData"] = external
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
        payload_tender = payload.get("tender")
        if isinstance(payload_tender, dict):
            payload_tender.pop("documents", None)
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
    result["verification"]["validationVerified"] = True
    result["verification"]["extractionVerified"] = True if document_statuses else None
    result["verification"]["cleanupVerified"] = cleanup_completed
    result["privacy"]["temporaryStorage"] = (
        "The request-scoped temporary directory was removed before this response."
    )
    try:
        storage.save_evaluation(result)
    except Exception:
        return {
            "error": "Evaluation completed but could not be saved to the records database.",
            "documents": document_statuses,
            "processing": processing,
            "verification": inference.empty_verification(
                state=inference.STATE_INFERENCE_FAILED,
                status="Evaluation record could not be persisted",
                failure_reason="Database persistence failed.",
            ),
        }, 500
    return result, 200


@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/workspace")
def workspace():
    return render_template("index.html")


@app.route("/api/health", methods=["GET"])
def healthcheck():
    database_available = storage.check_database_health()
    ai_status = inference.check_provider_health()
    response = {
        "status": "ok" if database_available and ai_status.get("available") else "degraded",
        "backend": {"available": True},
        "database": {"available": database_available},
        "inferenceProvider": ai_status,
        "externalSources": {
            "samGov": {
                "configured": bool(os.environ.get("SAM_GOV_API_KEY", "").strip()),
                "provider": "sam.gov",
            }
        },
    }
    return jsonify(response), (200 if database_available else 503)


@app.route("/api/evaluations", methods=["GET"])
def evaluations_list_route():
    try:
        limit = request.args.get("limit", default=100, type=int)
        return jsonify({"evaluations": storage.list_evaluations(limit)})
    except Exception:
        return jsonify({"error": "Evaluation records are unavailable."}), 503


@app.route("/api/evaluations/<record_id>", methods=["GET"])
def evaluation_detail_route(record_id: str):
    try:
        result = storage.get_evaluation(record_id)
    except Exception:
        return jsonify({"error": "Evaluation record could not be read."}), 503
    if result is None:
        return jsonify({"error": "Evaluation record not found."}), 404
    return jsonify(result)


@app.route("/api/evaluations/<record_id>/verify", methods=["GET"])
def evaluation_verify_route(record_id: str):
    try:
        result = storage.verify_evaluation(record_id)
    except Exception:
        return jsonify({"error": "Evaluation integrity could not be checked."}), 503
    if result is None:
        return jsonify({"error": "Evaluation record not found."}), 404
    return jsonify(result), (200 if result["verified"] else 409)


@app.route("/api/evaluations/<record_id>/verify-documents", methods=["POST"])
def evaluation_documents_verify_route(record_id: str):
    if request.mimetype != "multipart/form-data":
        return jsonify({"error": "Re-upload documents as multipart files using tender_N and bid_N fields."}), 400

    supplied: list[dict[str, Any]] = []
    counts: dict[int, int] = {}
    tender_count = 0
    generic_field = "documents" in request.files
    if generic_field and len(request.files) > 1:
        return jsonify({"error": "Use either documents or grouped tender_N / bid_N fields, not both."}), 400
    try:
        for field_name in request.files:
            bid_match = re.fullmatch(r"bid_(\d+)", field_name)
            tender_match = re.fullmatch(r"tender_(\d+)", field_name)
            if field_name == "documents" and generic_field:
                is_tender = False
                vendor_index = None
            elif not bid_match and not tender_match:
                return jsonify({"error": "Unexpected uploaded file field."}), 400
            else:
                is_tender = bool(tender_match)
                vendor_index = None if is_tender else int(bid_match.group(1))
            uploads = request.files.getlist(field_name)
            if field_name == "documents":
                if len(supplied) + len(uploads) > MAX_DOCUMENTS_PER_BID * (MAX_VENDORS + 1):
                    return jsonify({"error": "Too many documents to verify."}), 413
            elif is_tender:
                tender_count += len(uploads)
                if tender_count > MAX_DOCUMENTS_PER_BID:
                    return jsonify({"error": "Too many tender documents to verify."}), 413
            else:
                counts[vendor_index] = counts.get(vendor_index, 0) + len(uploads)
                if counts[vendor_index] > MAX_DOCUMENTS_PER_BID:
                    return jsonify({"error": "Too many vendor documents to verify."}), 413
            for upload in uploads:
                data = upload.stream.read(MAX_DOCUMENT_BYTES + 1)
                if len(data) > MAX_DOCUMENT_BYTES:
                    return jsonify({"error": "A document exceeds the 10 MB verification limit."}), 413
                if not data:
                    return jsonify({"error": "Empty files cannot be verified."}), 400
                supplied.append({
                    "fileName": upload.filename or "unnamed file",
                    "sha256": hashlib.sha256(data).hexdigest(),
                    **({} if field_name == "documents" else {
                        "scope": "tender" if is_tender else "vendor",
                        "vendorIndex": vendor_index,
                    }),
                })
    finally:
        for _field_name, upload in request.files.items(multi=True):
            upload.close()

    if not supplied:
        return jsonify({"error": "Upload at least one original document to verify."}), 400
    try:
        result = storage.verify_document_hashes(record_id, supplied)
    except Exception:
        return jsonify({"error": "Document integrity could not be checked."}), 503
    if result is None:
        return jsonify({"error": "Evaluation record not found."}), 404
    return jsonify(result), (200 if result["verified"] else 409)


def evaluation_request():
    if request.mimetype == "multipart/form-data":
        try:
            payload = json.loads(request.form.get("payload", "{}"))
        except json.JSONDecodeError:
            return None, None, (jsonify({"error": "Evaluation payload must be valid JSON."}), 400)
        uploads_by_vendor: dict[int, list[FileStorage]] = {}
        for key in request.files:
            bid_match = re.fullmatch(r"bid_(\d+)", key)
            tender_match = re.fullmatch(r"tender_(\d+)", key)
            if bid_match:
                uploads_by_vendor.setdefault(int(bid_match.group(1)), []).extend(request.files.getlist(key))
            elif tender_match:
                uploads_by_vendor.setdefault(-1, []).extend(request.files.getlist(key))
            else:
                return None, None, (jsonify({"error": "Unexpected uploaded file field."}), 400)
    else:
        payload = request.get_json(silent=True) or {}
        uploads_by_vendor = {}
        if isinstance(payload, dict):
            payload_bids = payload.get("bids", [])
            payload_tender = payload.get("tender", {})
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
            if isinstance(payload_tender, dict) and payload_tender.get("documents"):
                return None, None, (
                    jsonify({"error": "Upload tender documents as multipart files, not embedded text."}),
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


@app.route("/api/evaluate/manual", methods=["POST"])
def evaluate_manual_route():
    """Manual evaluation endpoint - works without AI inference."""
    payload, uploads_by_vendor, error_response = evaluation_request()
    if error_response:
        return error_response
    payload["evaluationMode"] = "manual"
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
