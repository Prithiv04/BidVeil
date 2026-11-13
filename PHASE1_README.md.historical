# BIDVEIL Phase 1 — NEAR AI Cloud TEE Smoke Test

The repository's main dashboard and privacy/document-upload architecture are documented in [README.md](./README.md).

To run the standalone cloud smoke test:

1. Install dependencies with `python -m pip install -r requirements.txt`.
2. Configure `NEARAI_API_KEY` in `.env`.
3. Run `python scripts/tee_smoke_test.py`.

The smoke test uses the NEAR AI Inference SDK in E2EE mode and attempts response-signature verification. A `provider_tee` signature proves model TEE execution; a `gateway` signature alone does not. No mock verification mode is provided.
