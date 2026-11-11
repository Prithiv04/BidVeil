"""NEAR AI Cloud inference and official TEE verification for BIDVEIL.

Cryptographic checks are performed by the NEAR AI Inference SDK
(nearai-inference-sdk). This module does not implement a substitute verifier.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import httpx
from nearai_inference_sdk import (
    ApiError,
    AttestationClient,
    InferenceClient,
    VerificationError,
)
from nearai_inference_sdk.core.attestation_common import verify_reported_nonce
from nearai_inference_sdk.utils.common import generate_nonce as sdk_generate_nonce

LIVE_API_URL = "https://cloud-api.near.ai/v1"
DEFAULT_MODEL = "z-ai/glm-5.3-flash"
SIGNING_ALGO = "ed25519"
DEFAULT_TIMEOUT_SECONDS = 90.0

STATE_WAITING = "WAITING"
STATE_ATTESTATION_PENDING = "ATTESTATION_PENDING"
STATE_ATTESTATION_VERIFIED = "ATTESTATION_VERIFIED"
STATE_SIGNATURE_VERIFIED = "SIGNATURE_VERIFIED"
STATE_MODEL_TEE_VERIFIED = "MODEL_TEE_VERIFIED"
STATE_GATEWAY_ONLY = "GATEWAY_ONLY"
STATE_VERIFICATION_FAILED = "VERIFICATION_FAILED"
STATE_VERIFICATION_UNAVAILABLE = "VERIFICATION_UNAVAILABLE"


class NearAIError(Exception):
    def __init__(self, message: str, status_code: int = 502, state: str = STATE_VERIFICATION_FAILED):
        super().__init__(message)
        self.status_code = status_code
        self.state = state


class NearAIUnavailableError(NearAIError):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message, status_code, STATE_VERIFICATION_UNAVAILABLE)


class UnsupportedModelError(NearAIError):
    def __init__(self, message: str):
        super().__init__(message, 400, STATE_VERIFICATION_UNAVAILABLE)


def configured_model() -> str:
    return (os.getenv("NEARAI_MODEL") or DEFAULT_MODEL).strip()


def generate_nonce() -> str:
    """Return 32 random bytes as 64 hexadecimal characters (official nonce format)."""
    return sdk_generate_nonce()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "x-no-aliasing": "true",
    }


def require_api_key() -> str:
    api_key = os.getenv("NEARAI_API_KEY")
    if not api_key:
        raise NearAIUnavailableError("NEAR AI Cloud is not configured.")
    return api_key


def parse_signed_payload(signed_text: str, signature_kind: str) -> dict[str, str | None]:
    """Parse official signature text. Kind is never inferred from the payload shape."""
    parts = signed_text.split(":")
    if signature_kind == "provider_tee":
        if len(parts) != 3:
            raise NearAIError("Provider TEE signed payload did not match the official three-part format.")
        return {
            "model_id": parts[0],
            "request_hash": parts[1],
            "response_hash": parts[2],
        }
    if signature_kind == "gateway":
        if len(parts) != 2:
            raise NearAIError("Gateway signed payload did not match the official two-part format.")
        return {
            "model_id": None,
            "request_hash": parts[0],
            "response_hash": parts[1],
        }
    raise NearAIError(f"Unsupported signature kind: {signature_kind}")


def hashes_match_signed_text(
    signed_text: str,
    signature_kind: str,
    request_body: bytes | None,
    response_body: bytes | None,
    expected_model: str | None = None,
) -> dict[str, Any]:
    parsed = parse_signed_payload(signed_text, signature_kind)
    request_match = None
    response_match = None
    model_match = None
    if request_body is not None:
        request_match = parsed["request_hash"] == hashlib.sha256(request_body).hexdigest()
    if response_body is not None:
        response_match = parsed["response_hash"] == hashlib.sha256(response_body).hexdigest()
    if signature_kind == "provider_tee" and expected_model is not None:
        model_match = parsed["model_id"] == expected_model
    valid = True
    if request_match is False or response_match is False or model_match is False:
        valid = False
    return {
        "valid": valid,
        "model_id": parsed["model_id"],
        "request_hash": parsed["request_hash"],
        "response_hash": parsed["response_hash"],
        "request_hash_match": request_match,
        "response_hash_match": response_match,
        "model_id_match": model_match,
    }


def classify_verification_state(
    *,
    failed: bool = False,
    unavailable: bool = False,
    attestation_verified: bool = False,
    signature_verified: bool = False,
    signature_kind: str | None = None,
) -> str:
    if failed:
        return STATE_VERIFICATION_FAILED
    if unavailable:
        return STATE_VERIFICATION_UNAVAILABLE
    if (
        attestation_verified
        and signature_verified
        and signature_kind == "provider_tee"
    ):
        return STATE_MODEL_TEE_VERIFIED
    if signature_verified and signature_kind == "gateway":
        return STATE_GATEWAY_ONLY
    if signature_verified:
        return STATE_SIGNATURE_VERIFIED
    if attestation_verified:
        return STATE_ATTESTATION_VERIFIED
    return STATE_ATTESTATION_PENDING


def empty_verification(
    *,
    state: str = STATE_WAITING,
    model: str | None = None,
    status: str = "Waiting for evaluation.",
    failure_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "mode": "unconfigured" if state == STATE_VERIFICATION_UNAVAILABLE else "live",
        "state": state,
        "status": status,
        "model": model or configured_model(),
        "modelIdentity": None,
        "nonce": None,
        "nonceVerified": False,
        "attestationVerified": False,
        "attestationStatus": "pending",
        "gatewayVerified": False,
        "modelVerified": False,
        "signatureVerified": False,
        "hashVerified": False,
        "responseSignatureKind": "unavailable",
        "signatureType": "unavailable",
        "requestHash": None,
        "responseHash": None,
        "completionId": None,
        "evidenceIds": [],
        "verifiedAt": None,
        "gpuEvidence": "unavailable",
        "failureReason": failure_reason,
        "unavailableChecks": [],
    }


async def list_models(api_key: str | None = None, timeout: float = 30.0) -> list[dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(f"{LIVE_API_URL}/models", headers=headers)
        response.raise_for_status()
        payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise NearAIError("NEAR AI Cloud returned an invalid models list.")
    return [item for item in data if isinstance(item, dict) and item.get("id")]


async def fetch_model_metadata(api_key: str, model: str) -> Any:
    client = AttestationClient(api_key, base_url=LIVE_API_URL)
    return await client.fetch_model_metadata(model)


def model_supports_near_tee(metadata: Any) -> bool:
    return bool(
        getattr(metadata, "attestation_supported", False)
        and getattr(metadata, "provider_type", None) == "vllm"
    )


async def resolve_tee_model(api_key: str, preferred: str | None = None) -> dict[str, Any]:
    """Select a model that actually advertises NEAR model attestation."""
    model_id = (preferred or configured_model()).strip()
    catalog: list[dict[str, Any]] = []
    catalog_error = None
    try:
        catalog = await list_models(api_key)
    except Exception as error:
        catalog_error = error

    listed_ids = {str(item.get("id")) for item in catalog}
    if catalog and model_id not in listed_ids:
        raise UnsupportedModelError(
            f"Model {model_id} is not present in the NEAR AI Cloud models catalog."
        )

    try:
        metadata = await fetch_model_metadata(api_key, model_id)
    except (ApiError, httpx.HTTPError) as error:
        raise UnsupportedModelError(
            f"Model {model_id} could not be resolved for TEE capability."
        ) from error

    if not model_supports_near_tee(metadata):
        raise UnsupportedModelError(
            f"Model {model_id} does not advertise NEAR model attestation "
            f"(provider_type={getattr(metadata, 'provider_type', 'unknown')}, "
            f"attestation_supported={getattr(metadata, 'attestation_supported', False)})."
        )

    return {
        "id": model_id,
        "listed": model_id in listed_ids if catalog else None,
        "catalogCount": len(catalog),
        "catalogError": str(catalog_error) if catalog_error else None,
        "providerType": metadata.provider_type,
        "attestationSupported": metadata.attestation_supported,
    }


async def fetch_attestation_report(
    api_key: str,
    model: str,
    nonce: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """GET /v1/attestation/report using the official query contract."""
    params = {
        "model": model,
        "provider": "near",
        "signing_algo": SIGNING_ALGO,
        "nonce": nonce,
        "include_tls_fingerprint": "false",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{LIVE_API_URL}/attestation/report",
            params=params,
            headers=_auth_headers(api_key),
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise NearAIError("Attestation report was not a JSON object.")
    return payload


def verify_attestation_nonce(report: dict[str, Any], nonce: str) -> dict[str, Any]:
    """Confirm the client nonce is echoed, then bind it with the official SDK helper."""
    gateway = report.get("gateway_attestation") or {}
    model_reports = report.get("model_attestations") or []
    if not isinstance(gateway, dict):
        raise NearAIError("Gateway attestation evidence is missing.")
    if not isinstance(model_reports, list) or not model_reports:
        raise UnsupportedModelError(
            "No NEAR model attestation candidates were returned for this model."
        )

    gateway_nonce = str(gateway.get("request_nonce") or "")
    verify_reported_nonce(gateway_nonce, nonce, "attestationNonce")
    for index, candidate in enumerate(model_reports):
        if not isinstance(candidate, dict):
            raise NearAIError("A model attestation candidate was malformed.")
        reported = str(candidate.get("request_nonce") or "")
        verify_reported_nonce(reported, nonce, "attestationNonce")
        nvidia_payload = candidate.get("nvidia_payload")
        if nvidia_payload:
            payload = nvidia_payload
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError as error:
                    raise NearAIError("NVIDIA GPU payload was not valid JSON.") from error
            if isinstance(payload, dict) and payload.get("nonce"):
                verify_reported_nonce(str(payload["nonce"]), nonce, "nvidiaPayload")

    return {
        "gatewayNonceVerified": True,
        "modelNonceVerified": True,
        "modelCandidateCount": len(model_reports),
        "checkedCandidates": index + 1 if model_reports else 0,
    }


def _signer_identity(value: Any) -> str | None:
    signer = getattr(value, "signer", None)
    if signer is None:
        return None
    return getattr(signer, "signing_address", None)


@dataclass
class VerifiedInference:
    content: str
    verification: dict[str, Any]
    model: str
    completion_id: str | None = None
    unavailable_checks: list[str] = field(default_factory=list)


async def run_verified_inference(
    prompt: str,
    *,
    nonce: str | None = None,
    model: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    on_progress: Callable[[str], None] | None = None,
) -> VerifiedInference:
    """Official order: nonce, attestation report, SDK attestation verify, chat, response verify."""
    api_key = require_api_key()
    session_nonce = nonce or generate_nonce()
    selected = await resolve_tee_model(api_key, model)
    model_id = selected["id"]
    unavailable: list[str] = []

    def progress(stage: str) -> None:
        if on_progress is not None:
            on_progress(stage)

    progress("attestation_pending")
    try:
        report = await fetch_attestation_report(api_key, model_id, session_nonce, timeout=timeout)
        nonce_result = verify_attestation_nonce(report, session_nonce)
    except UnsupportedModelError:
        raise
    except VerificationError as error:
        raise NearAIError(f"Attestation nonce verification failed: {error}") from error
    except httpx.TimeoutException as error:
        raise NearAIUnavailableError("NEAR AI Cloud attestation request timed out.", 504) from error
    except httpx.HTTPError as error:
        raise NearAIError("NEAR AI Cloud attestation request failed.") from error

    model_reports = report.get("model_attestations") or []
    gpu_payloads = [
        candidate.get("nvidia_payload")
        for candidate in model_reports
        if isinstance(candidate, dict) and candidate.get("nvidia_payload")
    ]
    if not gpu_payloads:
        unavailable.append("NVIDIA GPU evidence was not present on the attestation report.")

    evidence_ids = []
    for candidate in model_reports:
        if isinstance(candidate, dict) and candidate.get("signing_address"):
            evidence_ids.append(str(candidate["signing_address"]))
    gateway = report.get("gateway_attestation") or {}
    if isinstance(gateway, dict) and gateway.get("signing_address"):
        evidence_ids.append(f"gateway:{gateway['signing_address']}")

    progress("attestation_verify")
    try:
        async with InferenceClient(
            api_key,
            base_url=LIVE_API_URL,
            e2ee=True,
            signing_algo=SIGNING_ALGO,
            attestation_cache_time_to_live_ms=0,
        ) as client:
            attestation = await client.verify(model_id)
            progress("attestation_verified")
            completion = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a procurement evaluation assistant. Provide valid JSON only.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
            )
            completion_text = completion.choices[0].message.content or ""
            completion_id = completion.id
            progress("signature_verify")
            verified = await client.verify_response(completion_id)
    except NearAIError:
        raise
    except VerificationError as error:
        raise NearAIError(f"NEAR AI cryptographic verification failed: {error}") from error
    except ApiError as error:
        status = 504 if error.retryable else 502
        state = STATE_VERIFICATION_UNAVAILABLE if error.retryable else STATE_VERIFICATION_FAILED
        raise NearAIError(
            "NEAR AI Cloud inference or evidence retrieval failed.",
            status,
            state,
        ) from error
    except httpx.TimeoutException as error:
        raise NearAIUnavailableError("NEAR AI Cloud inference timed out.", 504) from error
    except Exception as error:
        raise NearAIError("NEAR AI Cloud inference failed.") from error

    signature_kind = verified.signature_kind
    signed_text = verified.signature.signed_text
    try:
        hash_result = hashes_match_signed_text(signed_text, signature_kind, None, None, model_id)
    except NearAIError as error:
        raise NearAIError(str(error)) from error

    gpu_statuses = [getattr(item, "gpu_evidence", "unavailable") for item in attestation.models]
    if gpu_statuses and all(status == "not_provided" for status in gpu_statuses):
        if "NVIDIA GPU evidence was not present on the attestation report." not in unavailable:
            unavailable.append("NVIDIA GPU evidence was not provided by the model report.")
    gpu_evidence = gpu_statuses[0] if gpu_statuses else "unavailable"

    model_identity = _signer_identity(verified.attestation)
    attestation_ok = True
    signature_ok = True
    hash_ok = hash_result["valid"]
    model_tee = signature_kind == "provider_tee"
    if not model_tee:
        # Gateway signatures are verified by the SDK but do not prove model TEE execution.
        pass
    if not hash_ok:
        raise NearAIError("Signed response hashes did not match the official payload format.")

    state = classify_verification_state(
        attestation_verified=attestation_ok,
        signature_verified=signature_ok,
        signature_kind=signature_kind,
    )
    if state == STATE_MODEL_TEE_VERIFIED:
        status = "Model TEE signature verified by the official NEAR AI Inference SDK."
    elif state == STATE_GATEWAY_ONLY:
        status = "Gateway signature verified; model TEE execution is not proven."
    else:
        status = "Response signature verified."

    verified_at = datetime.fromtimestamp(attestation.verified_at / 1000, tz=timezone.utc).replace(
        microsecond=0
    ).isoformat()

    verification = {
        "mode": "live",
        "state": state,
        "status": status,
        "model": model_id,
        "modelIdentity": model_identity,
        "nonce": session_nonce,
        "nonceVerified": True,
        "attestationVerified": model_tee,
        "attestationStatus": "verified",
        "gatewayVerified": True,
        "modelVerified": model_tee,
        "signatureVerified": True,
        "hashVerified": hash_ok,
        "responseSignatureKind": signature_kind,
        "signatureType": signature_kind,
        "requestHash": hash_result["request_hash"],
        "responseHash": hash_result["response_hash"],
        "signedModelId": hash_result["model_id"],
        "completionId": completion_id,
        "evidenceIds": evidence_ids,
        "verifiedAt": verified_at,
        "gpuEvidence": gpu_evidence,
        "failureReason": None,
        "unavailableChecks": unavailable,
        "modelCandidateCount": nonce_result["modelCandidateCount"],
        "providerType": selected["providerType"],
        "catalogListed": selected["listed"],
    }
    return VerifiedInference(
        content=completion_text,
        verification=verification,
        model=model_id,
        completion_id=completion_id,
        unavailable_checks=unavailable,
    )


# Imported by app error mapping without exposing secrets.
__all__ = [
    "DEFAULT_MODEL",
    "LIVE_API_URL",
    "NearAIError",
    "NearAIUnavailableError",
    "UnsupportedModelError",
    "VerifiedInference",
    "classify_verification_state",
    "configured_model",
    "empty_verification",
    "fetch_attestation_report",
    "generate_nonce",
    "hashes_match_signed_text",
    "list_models",
    "parse_signed_payload",
    "resolve_tee_model",
    "run_verified_inference",
    "verify_attestation_nonce",
]
