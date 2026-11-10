# BIDVEIL

BIDVEIL is an AI-assisted tender evaluation dashboard using NEAR AI Cloud and its Inference SDK's E2EE and response-verification flow. It ranks submissions using the existing weighted scoring engine. Results are decision support, not an automatic or legally binding procurement decision.

## Features

- Tender setup and multiple vendor bid submissions
- PDF and UTF-8 TXT upload with server-side extraction
- Weighted scoring, ranking, criterion breakdown, and evaluation evidence
- NEAR AI Cloud inference using `z-ai/glm-5.3-flash`
- Response signature distinction between `provider_tee` and `gateway`
- Request-specific processing status, extraction result, and cleanup confirmation
- No database or application-level history for bids or evaluation content

## Document processing

The browser sends PDF/TXT files as multipart uploads. BIDVEIL validates extensions, MIME types, file size, PDF structure/encryption, UTF-8 encoding, and the presence of extractable text. Unsupported or unreadable files fail the evaluation with a per-file status; BIDVEIL does not silently omit them or claim successful extraction.

For each evaluation, the server writes uploads using generated names inside a unique `TemporaryDirectory`, extracts text using `pypdf` or UTF-8 decoding, closes the framework upload streams before inference, and uses the extracted text to construct the NEAR AI Cloud analysis request. The temporary directory is closed on success and on extraction, inference, verification, or evaluation failures. Multiple requests receive independent temporary directories. Werkzeug may also use its request-managed temporary spool for multipart parsing; BIDVEIL closes those file streams after extraction (or on failure), and Werkzeug closes them when the request context ends.

Limits: 10 MB per document, 2 million extracted characters per document, 10 million extracted characters per request, 1,000 PDF pages per document, 10 documents per vendor, 20 vendors, and 50 MB per HTTP request. Only PDF and UTF-8 TXT are supported; scanned/image-only PDFs without an OCR text layer are rejected as text-empty.

## Privacy boundaries

- BIDVEIL does not intentionally persist uploaded documents, extracted bid text, prompts, or model responses in a database, application files, or logs.
- Temporary upload files are removed when the request-scoped temporary directory closes. This is file cleanup, not a guarantee of physical storage overwrite.
- Multipart parser spool files, if used by Werkzeug, are request-managed temporary files and are closed after document extraction or request completion.
- Python process memory may retain copies until normal runtime memory reuse/release; secure memory erasure is not claimed.
- Bid text is sent to NEAR AI Cloud for analysis. BIDVEIL cannot control or promise the provider's retention, operational logging, or other processing practices; check the provider's current terms and configuration before using real procurement data.
- The evaluation response is returned to the browser and may exist in browser/runtime memory. BIDVEIL does not implement a history feature.

## Verification behavior

Live inference requires `NEARAI_API_KEY`. BIDVEIL uses the NEAR AI Inference SDK with `e2ee=True` and calls `verify_response(completion.id)`. An SDK verification exception fails the evaluation. The dashboard marks model execution verified only when the SDK returns a verified `provider_tee` signature. A successfully verified `gateway` signature is explicitly not treated as proof of model TEE execution. No mock AI or mock attestation mode is provided.

The SDK performs its gateway/model attestation checks as part of the E2EE request flow. BIDVEIL reports gateway verification only after the SDK's response verification call succeeds; it does not claim that a gateway signature proves model execution.

## Run locally (Windows PowerShell)

1. Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

2. If `.env` does not already exist, copy the example and add a real key:

```powershell
Copy-Item .env.example .env
```

```env
NEARAI_API_KEY=sk-your-key-here
```

3. Start BIDVEIL:

```powershell
python app.py
```

4. Open `http://127.0.0.1:8000/`. Check `http://127.0.0.1:8000/api/health` for service readiness. Without a configured key, health reports `unconfigured` and evaluation returns an explicit service error.

## Tests

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## Existing TEE smoke test

With a configured key, `python scripts/tee_smoke_test.py` runs the separate NEAR AI Cloud smoke test. It is not a local mock mode.

## References

- NEAR AI Cloud verification docs: https://docs.near.ai/cloud/verification
- NEAR AI Cloud API: https://cloud-api.near.ai/v1
- NEAR model examples: https://github.com/near-examples/nearai-cloud-verification-example
