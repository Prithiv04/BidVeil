# BIDVEIL

BIDVEIL is a tender evaluation dashboard with provider-agnostic inference and manual scoring modes. It ranks submissions using a deterministic weighted scoring engine. Results are decision support, not an automatic or legally binding procurement decision.

## Features

- Tender setup and multiple vendor bid submissions
- PDF and UTF-8 TXT upload with server-side extraction
- **Manual scoring mode**: Enter bidder scores directly without AI (works without any provider)
- **AI-assisted evaluation**: Configure any AI provider in `inference.py` for automated analysis
- Weighted scoring, ranking, criterion breakdown, and evaluation evidence
- Configurable evaluation criteria with customizable weights
- Price normalization with explicit over-budget handling
- Request-specific processing status, extraction result, and cleanup confirmation
- No database or application-level history for bids or evaluation content

## Document processing

The browser sends PDF/TXT files as multipart uploads. BIDVEIL validates extensions, MIME types, file size, PDF structure/encryption, UTF-8 encoding, and the presence of extractable text. Unsupported or unreadable files fail the evaluation with a per-file status; BIDVEIL does not silently omit them or claim successful extraction.

For each evaluation, the server writes uploads using generated names inside a unique `TemporaryDirectory`, extracts text using `pypdf` or UTF-8 decoding, closes the framework upload streams before inference, and uses the extracted text to construct the inference request. The temporary directory is closed on success and on extraction, inference, or evaluation failures. Multiple requests receive independent temporary directories. Werkzeug may also use its request-managed temporary spool for multipart parsing; BIDVEIL closes those file streams after extraction (or on failure), and Werkzeug closes them when the request context ends.

Limits: 10 MB per document, 2 million extracted characters per document, 10 million extracted characters per request, 1,000 PDF pages per document, 10 documents per vendor, 20 vendors, and 50 MB per HTTP request. Only PDF and UTF-8 TXT are supported; scanned/image-only PDFs without an OCR text layer are rejected as text-empty.

## Architecture

```text
Browser (Flask template + vanilla JS)
   |  multipart POST /api/evaluate/stream  (SSE progress events)
   v
app.py  process_evaluation()
   |-- validate uploads (extension, MIME, size, PDF structure, UTF-8)
   |-- write to unique request-scoped TemporaryDirectory (bidveil-*)
   |-- extract text (pypdf / UTF-8 decode) -> in-memory only
   |-- generate fresh 32-byte nonce (hex)
   |-- build evaluation prompt (tender + extracted bid text + nonce)
   v
inference.py  run_inference()   [provider-agnostic]
   |-- When configured: calls AI provider for analysis
   |-- When not configured: raises INFERENCE_UNAVAILABLE
   v
Verification object -> app.py -> deterministic weighted scoring -> SSE result
   |
   +-- TemporaryDirectory removed on success AND every failure path
   +-- upload streams closed; extracted text never persisted
```

Evaluation states: `WAITING`, `INFERENCE_PENDING`, `INFERENCE_COMPLETED`, `INFERENCE_FAILED`, `INFERENCE_UNAVAILABLE`. Without a configured provider, evaluations fail with `INFERENCE_UNAVAILABLE`.

## Judge demo workflow (fictional vendors)

### Manual Scoring Mode (no AI required)

1. `python app.py` then open `http://127.0.0.1:8000/`.
2. Configure your tender in the **Evaluate** tab:
   - Enter tender title, description, budget, and requirements
   - Add bidders with their quoted prices and proposal summaries
   - Select **Manual scoring** as the evaluation mode
3. Navigate to the **Manual Scoring** tab:
   - Enter scores (0-100) for each bidder on the required criteria:
     - Technical Compliance
     - Relevant Experience
     - Delivery Timeline
     - Eligibility & Documentation
   - Price scores are auto-calculated based on budget
   - Add evidence, strengths, and weaknesses for each bidder
4. Click **Submit & Rank** to calculate weighted scores and rankings
5. View results in the **Results** tab with score breakdowns and rankings

### AI-Assisted Evaluation (requires provider configuration)

1. Configure an AI provider in `inference.py` (e.g., OpenAI, Anthropic, local models)
2. `python app.py` then open `http://127.0.0.1:8000/`.
3. Click **Load demo** — three fictional vendors (Northstar Systems: lower price/moderate compliance; Meridian Consulting: higher price/excellent compliance; Helio DataWorks: competitive price/incomplete documentation).
4. Optionally attach the sample TXT files referenced in the demo proposals.
5. Select **AI-Assisted** as the evaluation mode.
6. Click **Evaluate bids** — watch Processing status stream extraction -> preparation -> inference -> completion -> cleanup.
7. Inspect the **Evaluation Integrity** section: it shows document validation, extraction status, scoring completion, and cleanup status.
8. Rankings and per-vendor evidence come from the deterministic weighted scoring engine; the AI only extracts structured evidence, never final scores.

## Privacy boundaries

- BIDVEIL does not intentionally persist uploaded documents, extracted bid text, prompts, or model responses in a database, application files, or logs.
- Temporary upload files are removed when the request-scoped temporary directory closes. This is file cleanup, not a guarantee of physical storage overwrite.
- Multipart parser spool files, if used by Werkzeug, are request-managed temporary files and are closed after document extraction or request completion.
- Python process memory may retain copies until normal runtime memory reuse/release; secure memory erasure is not claimed.
- Bid text is sent to an inference provider when configured. BIDVEIL cannot control or promise the provider's retention, operational logging, or other processing practices; check the provider's current terms and configuration before using real procurement data.
- The evaluation response is returned to the browser and may exist in browser/runtime memory. BIDVEIL does not implement a history feature.

## Provider configuration

The `inference.py` module provides a provider-agnostic interface. By default, no provider is configured and evaluations fail with `INFERENCE_UNAVAILABLE`. To enable evaluation, implement `run_inference()` in `inference.py` with your chosen AI provider (OpenAI, Anthropic, local models, etc.).

## Run locally (Windows PowerShell)

1. Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

2. Start BIDVEIL:

```powershell
python app.py
```

3. Open `http://127.0.0.1:8000/`. Check `http://127.0.0.1:8000/api/health` for service readiness. Without a configured provider, health reports `none` and evaluation returns `INFERENCE_UNAVAILABLE`.

## Tests

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```
