# BIDVEIL

BIDVEIL is a tender evaluation application with OpenAI-assisted evidence review, manual scoring, persistent SQLite evaluation records, and SHA-256 integrity checks. Scores and recommendations support human review; they do not make procurement awards.

## What is implemented

- OpenAI Responses API evaluation using `OPENAI_API_KEY` and optional `OPENAI_MODEL` (defaults to `gpt-6-astra`). No mock fallback is used.
- PDF and UTF-8 TXT extraction. Tender configuration and extracted tender / vendor document text are passed as source material. AI evidence quotations must match that vendor's extracted proposal document content before results are accepted.
- AI evaluation requires at least one successfully extracted original proposal document for every vendor. The application does not create, infer, or substitute proposal text from sample data or a manually entered summary.
- Deterministic price normalization and weighted totals; AI supplies rationale and scores for the non-price criteria.
- Manual scoring that does not require an AI credential.
- SQLite persistence in `instance/bidveil.sqlite3` by default, override with `BIDVEIL_DB_PATH`. History and detail views come from the database.
- SHA-256 hashes for uploaded documents and canonical evaluation records. `/api/evaluations/<id>/verify` recomputes and checks the stored record hash; `/api/evaluations/<id>/verify-documents` compares re-uploaded files with their recorded hashes. This detects mismatches, but does not prove that a source document is authentic or that its claims are true. Since the record digest is stored with the record, an administrator who can rewrite both database fields can also recompute it; use protected backups or a separately controlled audit store when resisting privileged tampering is required.
- `/api/evaluations/<id>/verify-documents` accepts the original files as multipart uploads and compares their byte hashes with the document hashes protected by the record hash.
- Health reporting checks SQLite and, when configured, contacts OpenAI to test API reachability. The SAM.gov source is optional and is reported as configured separately.
- Optional U.S. SAM.gov public entity lookup when the submitter provides a UEI and `SAM_GOV_API_KEY`. It only uses the public Entity Management API and does not affect evaluation scores. No external vendor data is invented or supplied as a fallback.

The optional source is the [official SAM.gov Entity Management API](https://open.gsa.gov/api/entity-api/); use requires a SAM.gov public API key and a vendor UEI.

Uploaded document contents and proposal text are removed from the persisted record after evaluation. Extracted evidence quotations, rationales, scores, evaluation metadata, and document hashes are retained. Evaluation prompts are sent to OpenAI when AI mode is used; review the provider's current data terms before uploading sensitive procurement material.

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `OPENAI_API_KEY` in the process environment or private `.env` file to enable AI evaluation. Do not commit `.env`. `OPENAI_MODEL` can select a model available to your account. Manual scoring is available without OpenAI credentials. For optional U.S. entity lookup, set `SAM_GOV_API_KEY`; users must supply a vendor UEI.

Start the app:

```powershell
python app.py
```

Open `http://127.0.0.1:8000/`; the evaluation workspace is at `/workspace`. Check `/api/health` for current service status. The API key is never returned by health responses.

## Document limits

Only PDF and UTF-8 TXT are accepted. Files are limited to 10 MB each, 10 files per vendor or tender, 20 vendors, 1,000 PDF pages, 2 million extracted characters per file, and 10 million per request. Scanned PDFs without an extractable text layer are rejected.

## API routes

- `GET /api/health`
- `POST /api/evaluate` (JSON or multipart form with a `payload` JSON field and `tender_N` / `bid_N` files)
- `POST /api/evaluate/stream` (multipart/server-sent progress)
- `POST /api/evaluate/manual`
- `GET /api/evaluations`
- `GET /api/evaluations/<id>`
- `GET /api/evaluations/<id>/verify`
- `POST /api/evaluations/<id>/verify-documents` (multipart repeated `documents` fields, or grouped `tender_N` / `bid_N` fields; use original filenames)

## Tests

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Tests use controlled fake provider responses only in test code; the application never treats such responses as production evaluations.

## Deployment considerations

The application does not include user authentication or multi-tenant access controls. Put it behind an appropriate identity and access-control layer before using it for real procurement. Use HTTPS, secure secret storage, database backups, and restricted access to the SQLite file. The default SQLite database is suitable for a single application instance; select an appropriately managed database before scaling to multiple workers or hosts.
