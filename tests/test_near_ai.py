"""Mocked unit tests for the NEAR AI Cloud integration layer.

These tests mock all external calls. They verify BIDVEIL's handling of
NEAR AI responses and errors; they are NOT proof of live TEE verification.
Live verification is covered separately by scripts/tee_smoke_test.py.
"""

import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
import pytest

import near_ai


def make_api_status_error(status_code: int, message: str) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://cloud-api.near.ai/v1/chat/completions")
    response = httpx.Response(
        status_code,
        json={"error": {"message": message, "type": "test_error"}},
        request=request,
    )
    return openai.APIStatusError(message, response=response, body=None)


def test_generate_nonce_is_64_hex_chars():
    nonce = near_ai.generate_nonce()
    assert len(nonce) == 64
    assert all(c in "0123456789abcdef" for c in nonce)
    assert near_ai.generate_nonce() != nonce


def test_parse_signed_payload_provider_tee():
    signed = "model-x:reqhash:reshash"
    parsed = near_ai.parse_signed_payload(signed, "provider_tee")
    assert parsed == {
        "model_id": "model-x",
        "request_hash": "reqhash",
        "response_hash": "reshash",
    }


def test_parse_signed_payload_gateway():
    parsed = near_ai.parse_signed_payload("reqhash:reshash", "gateway")
    assert parsed == {
        "model_id": None,
        "request_hash": "reqhash",
        "response_hash": "reshash",
    }


def test_parse_signed_payload_rejects_bad_format():
    with pytest.raises(near_ai.NearAIError):
        near_ai.parse_signed_payload("only-one-part", "provider_tee")
    with pytest.raises(near_ai.NearAIError):
        near_ai.parse_signed_payload("a:b:c", "gateway")
    with pytest.raises(near_ai.NearAIError):
        near_ai.parse_signed_payload("a:b", "unknown_kind")


def test_hashes_match_signed_text_valid():
    request_body = b'{"model":"m"}'
    response_body = b'{"choices":[]}'
    req_hash = hashlib.sha256(request_body).hexdigest()
    res_hash = hashlib.sha256(response_body).hexdigest()
    signed = f"model-x:{req_hash}:{res_hash}"
    result = near_ai.hashes_match_signed_text(
        signed, "provider_tee", request_body, response_body, "model-x"
    )
    assert result["valid"] is True
    assert result["request_hash_match"] is True
    assert result["response_hash_match"] is True
    assert result["model_id_match"] is True


def test_hashes_match_signed_text_detects_mismatch():
    request_body = b"request"
    response_body = b"response"
    signed = "model-x:wronghash:alsowrong"
    result = near_ai.hashes_match_signed_text(
        signed, "provider_tee", request_body, response_body, "model-x"
    )
    assert result["valid"] is False
    assert result["request_hash_match"] is False
    assert result["response_hash_match"] is False


def test_hashes_match_signed_text_model_mismatch():
    signed = "other-model:aa:bb"
    result = near_ai.hashes_match_signed_text(
        signed, "provider_tee", None, None, "expected-model"
    )
    assert result["valid"] is False
    assert result["model_id_match"] is False


def test_classify_verification_state_matrix():
    assert near_ai.classify_verification_state(failed=True) == near_ai.STATE_VERIFICATION_FAILED
    assert near_ai.classify_verification_state(unavailable=True) == near_ai.STATE_VERIFICATION_UNAVAILABLE
    assert (
        near_ai.classify_verification_state(
            attestation_verified=True, signature_verified=True, signature_kind="provider_tee"
        )
        == near_ai.STATE_MODEL_TEE_VERIFIED
    )
    assert (
        near_ai.classify_verification_state(
            attestation_verified=True, signature_verified=True, signature_kind="gateway"
        )
        == near_ai.STATE_GATEWAY_ONLY
    )
    assert (
        near_ai.classify_verification_state(signature_verified=True, signature_kind="provider_tee")
        == near_ai.STATE_SIGNATURE_VERIFIED
    )
    assert (
        near_ai.classify_verification_state(attestation_verified=True)
        == near_ai.STATE_ATTESTATION_VERIFIED
    )
    assert near_ai.classify_verification_state() == near_ai.STATE_ATTESTATION_PENDING


def test_model_supports_near_tee():
    supported = SimpleNamespace(attestation_supported=True, provider_type="vllm")
    unsupported_provider = SimpleNamespace(attestation_supported=True, provider_type="openai")
    unsupported_flag = SimpleNamespace(attestation_supported=False, provider_type="vllm")
    assert near_ai.model_supports_near_tee(supported) is True
    assert near_ai.model_supports_near_tee(unsupported_provider) is False
    assert near_ai.model_supports_near_tee(unsupported_flag) is False


def _attestation_report(nonce: str, model_nonce: str | None = None) -> dict:
    return {
        "gateway_attestation": {"request_nonce": nonce, "signing_address": "gw-addr"},
        "model_attestations": [
            {
                "request_nonce": model_nonce if model_nonce is not None else nonce,
                "signing_address": "model-addr",
                "nvidia_payload": {"nonce": nonce},
            }
        ],
    }


def test_verify_attestation_nonce_accepts_matching_nonce():
    nonce = near_ai.generate_nonce()
    result = near_ai.verify_attestation_nonce(_attestation_report(nonce), nonce)
    assert result["gatewayNonceVerified"] is True
    assert result["modelNonceVerified"] is True
    assert result["modelCandidateCount"] == 1


def test_verify_attestation_nonce_rejects_mismatch():
    nonce = near_ai.generate_nonce()
    other = near_ai.generate_nonce()
    with pytest.raises(Exception):
        near_ai.verify_attestation_nonce(_attestation_report(nonce, model_nonce=other), nonce)


def test_verify_attestation_nonce_rejects_missing_model_reports():
    nonce = near_ai.generate_nonce()
    report = {"gateway_attestation": {"request_nonce": nonce}, "model_attestations": []}
    with pytest.raises(near_ai.UnsupportedModelError):
        near_ai.verify_attestation_nonce(report, nonce)


def test_verify_attestation_nonce_rejects_missing_gateway():
    nonce = near_ai.generate_nonce()
    report = {"model_attestations": [{"request_nonce": nonce}]}
    with pytest.raises(near_ai.NearAIError):
        near_ai.verify_attestation_nonce(report, nonce)


def test_empty_verification_shape():
    verification = near_ai.empty_verification(
        state=near_ai.STATE_VERIFICATION_UNAVAILABLE,
        status="TEE verification unavailable",
        failure_reason="no key",
    )
    assert verification["state"] == near_ai.STATE_VERIFICATION_UNAVAILABLE
    assert verification["mode"] == "unconfigured"
    assert verification["nonceVerified"] is False
    assert verification["signatureVerified"] is False
    assert verification["failureReason"] == "no key"


def test_run_verified_inference_requires_api_key(monkeypatch):
    monkeypatch.delenv("NEARAI_API_KEY", raising=False)
    with pytest.raises(near_ai.NearAIUnavailableError):
        asyncio.run(near_ai.run_verified_inference("prompt"))


def test_list_models_parses_catalog(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "model-a"}, {"id": "model-b"}, {"no_id": True}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            return FakeResponse()

    monkeypatch.setattr(near_ai.httpx, "AsyncClient", FakeClient)
    models = asyncio.run(near_ai.list_models("key"))
    assert [m["id"] for m in models] == ["model-a", "model-b"]


def test_resolve_tee_model_rejects_unsupported(monkeypatch):
    async def fake_list(api_key, timeout=30.0):
        return [{"id": "bad-model"}]

    async def fake_metadata(api_key, model):
        return SimpleNamespace(attestation_supported=False, provider_type="openai")

    monkeypatch.setattr(near_ai, "list_models", fake_list)
    monkeypatch.setattr(near_ai, "fetch_model_metadata", fake_metadata)
    with pytest.raises(near_ai.UnsupportedModelError):
        asyncio.run(near_ai.resolve_tee_model("key", "bad-model"))


def test_resolve_tee_model_rejects_unlisted_model(monkeypatch):
    async def fake_list(api_key, timeout=30.0):
        return [{"id": "other-model"}]

    monkeypatch.setattr(near_ai, "list_models", fake_list)
    with pytest.raises(near_ai.UnsupportedModelError):
        asyncio.run(near_ai.resolve_tee_model("key", "missing-model"))


def test_run_verified_inference_surfaces_402_as_unavailable(monkeypatch):
    """A provider billing error (402) must surface as VERIFICATION_UNAVAILABLE."""
    monkeypatch.setenv("NEARAI_API_KEY", "test-key")

    async def fake_resolve(api_key, preferred=None):
        return {
            "id": "test-model",
            "listed": True,
            "catalogCount": 1,
            "catalogError": None,
            "providerType": "vllm",
            "attestationSupported": True,
        }

    async def fake_report(api_key, model, nonce, timeout=30.0):
        return _attestation_report(nonce)

    class FakeCompletions:
        async def create(self, **kwargs):
            raise make_api_status_error(402, "No spending limit configured.")

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.chat = FakeChat()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def verify(self, model):
            return SimpleNamespace(models=[], verified_at=0)

        async def verify_response(self, completion_id):
            raise AssertionError("should not reach verify_response")

    monkeypatch.setattr(near_ai, "resolve_tee_model", fake_resolve)
    monkeypatch.setattr(near_ai, "fetch_attestation_report", fake_report)
    monkeypatch.setattr(near_ai, "InferenceClient", FakeClient)

    with pytest.raises(near_ai.NearAIUnavailableError) as excinfo:
        asyncio.run(
            near_ai.run_verified_inference("prompt", nonce=near_ai.generate_nonce())
        )
    assert "spending limit" in str(excinfo.value)
    assert excinfo.value.state == near_ai.STATE_VERIFICATION_UNAVAILABLE


def test_run_verified_inference_rejects_nonce_mismatch(monkeypatch):
    """A mismatched attestation nonce must fail before any inference call."""
    monkeypatch.setenv("NEARAI_API_KEY", "test-key")

    async def fake_resolve(api_key, preferred=None):
        return {
            "id": "test-model",
            "listed": True,
            "catalogCount": 1,
            "catalogError": None,
            "providerType": "vllm",
            "attestationSupported": True,
        }

    async def fake_report(api_key, model, nonce, timeout=30.0):
        return _attestation_report(nonce, model_nonce=near_ai.generate_nonce())

    monkeypatch.setattr(near_ai, "resolve_tee_model", fake_resolve)
    monkeypatch.setattr(near_ai, "fetch_attestation_report", fake_report)

    with pytest.raises(near_ai.NearAIError):
        asyncio.run(
            near_ai.run_verified_inference("prompt", nonce=near_ai.generate_nonce())
        )


def _fake_resolve():
    async def fake_resolve(api_key, preferred=None):
        return {
            "id": "test-model",
            "listed": True,
            "catalogCount": 1,
            "catalogError": None,
            "providerType": "vllm",
            "attestationSupported": True,
        }

    return fake_resolve


def _fake_report(nonce):
    async def fake_report(api_key, model, nonce_arg, timeout=30.0):
        return _attestation_report(nonce_arg)

    return fake_report


def _completion(content: str = '{"vendors": []}', completion_id: str = "cmpl-test"):
    return SimpleNamespace(
        id=completion_id,
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
    )


def _attestation_obj(signer_address: str = "model-signer"):
    return SimpleNamespace(
        models=[SimpleNamespace(gpu_evidence="verified")],
        verified_at=1_700_000_000_000,
        signer=SimpleNamespace(signing_address=signer_address),
    )


def _verified_result(signature_kind: str, signed_text: str):
    return SimpleNamespace(
        signature_kind=signature_kind,
        signature=SimpleNamespace(signed_text=signed_text),
        attestation=_attestation_obj(),
    )


def _install_success_client(monkeypatch, verified_result):
    class FakeCompletions:
        async def create(self, **kwargs):
            return _completion()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.chat = FakeChat()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def verify(self, model):
            return _attestation_obj()

        async def verify_response(self, completion_id):
            if isinstance(verified_result, Exception):
                raise verified_result
            return verified_result

    monkeypatch.setattr(near_ai, "InferenceClient", FakeClient)


def _run_inference(monkeypatch, verified_result):
    monkeypatch.setenv("NEARAI_API_KEY", "test-key")
    monkeypatch.setattr(near_ai, "resolve_tee_model", _fake_resolve())
    monkeypatch.setattr(near_ai, "fetch_attestation_report", _fake_report(None))
    _install_success_client(monkeypatch, verified_result)
    return asyncio.run(
        near_ai.run_verified_inference("prompt", nonce=near_ai.generate_nonce())
    )


def test_gateway_signature_never_yields_model_tee(monkeypatch):
    """A verified gateway signature must classify as GATEWAY_ONLY."""
    result = _run_inference(
        monkeypatch,
        _verified_result("gateway", "reqhash:reshash"),
    )
    verification = result.verification
    assert verification["state"] == near_ai.STATE_GATEWAY_ONLY
    assert verification["signatureType"] == "gateway"
    assert verification["modelVerified"] is False
    assert verification["attestationVerified"] is False
    assert verification["signatureVerified"] is True


def test_provider_tee_signature_yields_model_tee(monkeypatch):
    """A verified provider_tee signature with matching model id yields MODEL_TEE_VERIFIED."""
    result = _run_inference(
        monkeypatch,
        _verified_result("provider_tee", "test-model:reqhash:reshash"),
    )
    verification = result.verification
    assert verification["state"] == near_ai.STATE_MODEL_TEE_VERIFIED
    assert verification["signatureType"] == "provider_tee"
    assert verification["modelVerified"] is True
    assert verification["attestationVerified"] is True
    assert verification["signedModelId"] == "test-model"
    assert verification["modelIdentity"] == "model-signer"
    assert verification["verifiedAt"] is not None


def test_tampered_signed_model_id_is_rejected(monkeypatch):
    """A provider_tee signature naming a different model must fail."""
    with pytest.raises(near_ai.NearAIError):
        _run_inference(
            monkeypatch,
            _verified_result("provider_tee", "other-model:reqhash:reshash"),
        )


def test_malformed_signed_payload_is_rejected(monkeypatch):
    """A signed payload that does not match the official format must fail."""
    with pytest.raises(near_ai.NearAIError):
        _run_inference(
            monkeypatch,
            _verified_result("provider_tee", "only-one-part"),
        )
    with pytest.raises(near_ai.NearAIError):
        _run_inference(
            monkeypatch,
            _verified_result("gateway", "a:b:c"),
        )


def test_sdk_verification_failure_propagates(monkeypatch):
    """A VerificationError from the official SDK must fail the evaluation."""
    from nearai_inference_sdk.utils.errors import verification_failure

    with pytest.raises(near_ai.NearAIError):
        _run_inference(
            monkeypatch,
            verification_failure("signature.invalid"),
        )


def test_unknown_signature_kind_is_rejected(monkeypatch):
    """An unrecognized signature kind must not be treated as verified."""
    with pytest.raises(near_ai.NearAIError):
        _run_inference(
            monkeypatch,
            _verified_result("mystery", "a:b"),
        )


def test_verify_attestation_nonce_rejects_nvidia_payload_mismatch():
    """A NVIDIA payload echoing a different nonce must fail binding."""
    nonce = near_ai.generate_nonce()
    report = _attestation_report(nonce)
    report["model_attestations"][0]["nvidia_payload"] = {"nonce": near_ai.generate_nonce()}
    with pytest.raises(Exception):
        near_ai.verify_attestation_nonce(report, nonce)


def test_verify_attestation_nonce_rejects_malformed_candidate():
    nonce = near_ai.generate_nonce()
    report = _attestation_report(nonce)
    report["model_attestations"] = ["not-a-dict"]
    with pytest.raises(near_ai.NearAIError):
        near_ai.verify_attestation_nonce(report, nonce)


def test_verify_attestation_nonce_rejects_invalid_json_nvidia_payload():
    nonce = near_ai.generate_nonce()
    report = _attestation_report(nonce)
    report["model_attestations"][0]["nvidia_payload"] = "{not json"
    with pytest.raises(near_ai.NearAIError):
        near_ai.verify_attestation_nonce(report, nonce)


def test_replayed_attestation_report_is_rejected():
    """A report generated for an earlier nonce must not satisfy a fresh session."""
    old_nonce = near_ai.generate_nonce()
    fresh_nonce = near_ai.generate_nonce()
    report = _attestation_report(old_nonce)
    with pytest.raises(Exception):
        near_ai.verify_attestation_nonce(report, fresh_nonce)
