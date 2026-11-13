"""Provider-agnostic inference interface for BIDVEIL.

This module defines the interface for AI inference providers.
No provider is implemented by default — evaluations will fail with
INFERENCE_UNAVAILABLE until a provider is configured.

The scoring engine (in app.py) is deterministic and independent of any
specific provider — it processes score values returned by the inference
interface. Without a provider, evaluation cannot produce rankings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

# Simplified verification states (no TEE-specific states)
STATE_WAITING = "WAITING"
STATE_INFERENCE_PENDING = "INFERENCE_PENDING"
STATE_INFERENCE_COMPLETED = "INFERENCE_COMPLETED"
STATE_INFERENCE_FAILED = "INFERENCE_FAILED"
STATE_INFERENCE_UNAVAILABLE = "INFERENCE_UNAVAILABLE"


class InferenceError(Exception):
    """Base exception for inference failures."""
    def __init__(self, message: str, status_code: int = 502, state: str = STATE_INFERENCE_FAILED):
        super().__init__(message)
        self.status_code = status_code
        self.state = state


class InferenceUnavailableError(InferenceError):
    """Inference provider unavailable or misconfigured."""
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message, status_code, STATE_INFERENCE_UNAVAILABLE)


@dataclass
class InferenceResult:
    """Result from an inference provider."""
    content: str
    verification: dict[str, Any] = field(default_factory=dict)
    model: str = "unconfigured"
    completion_id: str | None = None


def generate_nonce() -> str:
    """Return 32 random bytes as 64 hexadecimal characters."""
    import secrets
    return secrets.token_hex(32)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def empty_verification(
    *,
    state: str = STATE_INFERENCE_UNAVAILABLE,
    model: str = "unconfigured",
    status: str = "Inference unavailable",
    failure_reason: str | None = None,
) -> dict[str, Any]:
    """Return a minimal verification object for unavailable/failed states."""
    return {
        "mode": "none",
        "state": state,
        "status": status,
        "model": model,
        "failureReason": failure_reason,
    }


async def run_inference(
    prompt: str,
    *,
    model: str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> InferenceResult:
    """
    Provider-agnostic inference entry point.

    This stub raises InferenceUnavailableError because no provider is
    configured. To integrate a provider, replace this implementation
    with a concrete one (OpenAI, Anthropic, local model, etc.).

    Tests can mock this function to provide sample data for testing
    document processing and scoring logic.
    """
    raise InferenceUnavailableError(
        "No inference provider is configured. "
        "Evaluations require an AI provider to extract evidence and score vendors. "
        "Configure a provider by implementing run_inference() in inference.py."
    )
