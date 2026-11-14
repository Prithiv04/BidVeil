import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

import inference


def test_inference_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(inference.InferenceUnavailableError, match="OPENAI_API_KEY"):
        asyncio.run(inference.run_inference("{}"))


def test_inference_uses_responses_api_and_strict_schema(monkeypatch):
    captured = {}

    class Responses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text='{"overallRecommendation":"Review","vendors":[]}', id="resp-test")

    class OpenAI:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.responses = Responses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setenv("OPENAI_MODEL", "account-model")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=OpenAI))

    result = asyncio.run(inference.run_inference('{"sourceMaterial":{}}'))

    assert result.model == "account-model"
    assert result.completion_id == "resp-test"
    assert captured["store"] is False
    assert captured["text"]["format"]["strict"] is True
    assert json.loads(result.content)["overallRecommendation"] == "Review"
    assert captured["client"]["api_key"] == "test-secret"


def test_provider_health_reports_missing_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert inference.check_provider_health() == {
        "provider": "openai",
        "configured": False,
        "available": False,
        "model": "gpt-6-astra",
        "status": "missing_api_key",
    }
