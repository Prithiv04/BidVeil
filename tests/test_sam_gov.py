import json
from contextlib import contextmanager

import sam_gov


def test_lookup_skips_network_when_not_configured(monkeypatch):
    monkeypatch.delenv("SAM_GOV_API_KEY", raising=False)
    assert sam_gov.lookup_entity("123456789012")["status"] == "not_configured"


def test_lookup_returns_only_exact_public_entity_match(monkeypatch):
    monkeypatch.setenv("SAM_GOV_API_KEY", "test-key")
    payload = {
        "entityData": [{"entityRegistration": {
            "ueiSAM": "123456789012",
            "legalBusinessName": "Registered Example LLC",
            "registrationStatus": "Active",
            "samRegistered": True,
        }}]
    }
    requests = []

    @contextmanager
    def fake_urlopen(request, timeout):
        requests.append(request.full_url)
        yield type("Response", (), {"read": lambda self, size: json.dumps(payload).encode()})()

    monkeypatch.setattr(sam_gov, "urlopen", fake_urlopen)
    result = sam_gov.lookup_entity("123456789012")

    assert result["status"] == "found"
    assert result["legalBusinessName"] == "Registered Example LLC"
    assert result["source"] == sam_gov.SAM_API_URL
    assert "ueiSAM=123456789012" in requests[0]
    assert "test-key" not in json.dumps(result)


def test_lookup_rejects_a_different_uei(monkeypatch):
    monkeypatch.setenv("SAM_GOV_API_KEY", "test-key")
    payload = {"entityData": [{"entityRegistration": {"ueiSAM": "000000000000"}}]}

    @contextmanager
    def fake_urlopen(_request, timeout):
        yield type("Response", (), {"read": lambda self, size: json.dumps(payload).encode()})()

    monkeypatch.setattr(sam_gov, "urlopen", fake_urlopen)
    assert sam_gov.lookup_entity("123456789012")["status"] == "no_exact_match"
