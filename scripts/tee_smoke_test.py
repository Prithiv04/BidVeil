"""Live NEAR AI Cloud TEE smoke test using the official verification order.

This script calls the real NEAR AI Cloud API. It is not a mocked unit test
and must not be counted as passing TEE proof unless every required check
succeeds. API credentials are never printed.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import near_ai


FICTIONAL_PROMPT = """
Return valid JSON only for this harmless fictional procurement scenario.

Tender: Fictional municipal records archive for the town of Rivermark.
Vendor A: quoted 82000, moderate technical compliance, 9-month delivery.
Do not use real organizations or personal data.

Schema: {"vendors":[{"vendorName":"Vendor A","quotedPrice":82000,"technicalComplianceScore":70}]}
""".strip()


def _mark(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _unavailable(label: str, reason: str) -> None:
    print(f"UNAVAILABLE  {label}: {reason}")


async def main() -> int:
    load_dotenv()
    print("=" * 64)
    print("BIDVEIL live NEAR AI Cloud TEE smoke test")
    print("=" * 64)
    print(f"Python: {sys.version.split()[0]}")
    print(f"Endpoint: {near_ai.LIVE_API_URL}")
    print(f"API key configured: {'yes' if os.getenv('NEARAI_API_KEY') else 'no'}")
    print()

    required_failed = False
    try:
        api_key = near_ai.require_api_key()
    except near_ai.NearAIUnavailableError as error:
        print(f"ERROR: {error}")
        return 1

    print("1. Model discovery (GET /v1/models)")
    try:
        models = await near_ai.list_models(api_key)
        print(f"   Catalog entries: {len(models)}")
    except Exception as error:
        print(f"   {_mark(False)} models endpoint: {type(error).__name__}")
        return 1

    print("2. Select a TEE-capable model (metadata is not assumed)")
    try:
        selected = await near_ai.resolve_tee_model(api_key)
    except near_ai.UnsupportedModelError as error:
        print(f"   {_mark(False)} {error}")
        return 1
    print(f"   Selected model: {selected['id']}")
    print(f"   provider_type: {selected['providerType']}")
    print(f"   attestation_supported: {selected['attestationSupported']}")
    print()

    nonce = near_ai.generate_nonce()
    print("3. Fresh nonce")
    print(f"   Nonce length (hex chars): {len(nonce)}")
    print()

    print("4. Attestation report (official /v1/attestation/report order)")
    try:
        report = await near_ai.fetch_attestation_report(api_key, selected["id"], nonce)
        nonce_check = near_ai.verify_attestation_nonce(report, nonce)
        print(f"   {_mark(True)} attestation HTTP retrieval")
        print(f"   {_mark(True)} gateway nonce binding")
        print(f"   {_mark(True)} model nonce binding ({nonce_check['modelCandidateCount']} candidate(s))")
    except Exception as error:
        print(f"   {_mark(False)} attestation verification: {type(error).__name__}: {error}")
        return 1

    model_reports = report.get("model_attestations") or []
    gpu_present = any(
        isinstance(item, dict) and item.get("nvidia_payload") for item in model_reports
    )
    if gpu_present:
        print("   NVIDIA GPU payload: present (verified later by official SDK)")
    else:
        _unavailable("NVIDIA GPU evidence", "model report did not include nvidia_payload")
    print()

    print("5. Official SDK attestation + fictional inference + response signature")
    try:
        result = await near_ai.run_verified_inference(
            FICTIONAL_PROMPT,
            nonce=nonce,
            model=selected["id"],
        )
    except Exception as error:
        print(f"   {_mark(False)} inference/verification: {type(error).__name__}: {error}")
        print("   Inference success: FAIL")
        return 1

    verification = result.verification
    kind = verification["responseSignatureKind"]
    model_tee = verification["state"] == near_ai.STATE_MODEL_TEE_VERIFIED
    gateway_only = verification["state"] == near_ai.STATE_GATEWAY_ONLY
    print(f"   Inference success: PASS")
    print(f"   Selected model identifier: {result.model}")
    print(f"   Signature type: {kind}")
    print(f"   Attestation verification: {_mark(True)}")
    print(f"   Response-signature verification: {_mark(verification['signatureVerified'])}")
    print(f"   Request hash: {verification['requestHash']}")
    print(f"   Response hash: {verification['responseHash']}")
    print(f"   Hash payload parse: {_mark(verification['hashVerified'])}")
    print(f"   GPU evidence (SDK): {verification['gpuEvidence']}")
    for check in verification.get("unavailableChecks") or []:
        _unavailable("optional check", check)
    print()
    print("=" * 64)
    print("VERIFICATION SUMMARY")
    print("=" * 64)
    print(f"State: {verification['state']}")
    print(f"Model TEE proven: {str(model_tee).lower()}")
    print(f"Gateway-only: {str(gateway_only).lower()}")
    print(f"Completion ID: {result.completion_id}")
    print()
    if model_tee:
        print("MEANING: The official SDK verified a provider_tee signature.")
        print("         Model TEE execution is proven for this response.")
        return 0
    if gateway_only:
        print("MEANING: The official SDK verified a gateway signature.")
        print("         Model TEE execution is NOT proven.")
        required_failed = True
    else:
        print("MEANING: Required model TEE verification did not succeed.")
        required_failed = True
    return 1 if required_failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
