# DocFlow API

DocFlow API is a multi-tenant document extraction service built with FastAPI, Celery, PostgreSQL, Redis, and S3-compatible storage.

It accepts uploaded files (PDF/images/DOCX), extracts text, runs schema-driven LLM extraction, and returns structured JSON results through polling and optional webhooks.

## Core Features

- Multi-tenant API-key authentication.
- File upload and asynchronous extraction jobs.
- OCR and document text extraction pipeline.
- LLM map-reduce extraction for large documents.
- Reliability controls:
	- Context-budgeting and bounded merge strategy.
	- Concurrency throttling for LLM calls.
	- AI outage circuit breaker.
	- Retry/backoff behavior in Celery.
- Duplicate detection with Redis Bloom filter.
- Optional webhook callbacks on successful completion.

## Tech Stack

- API: FastAPI
- Async DB layer: SQLAlchemy (async)
- Worker: Celery
- Queue/cache: Redis
- DB: PostgreSQL
- Storage: S3-compatible object store (MinIO/AWS S3)
- LLM client: OpenAI-compatible SDK (`AsyncOpenAI`, supports DeepSeek/OpenAI via `base_url`)
- Validation: Pydantic
- Testing: Pytest

## Project Layout

High-level source structure:

- `main.py`: FastAPI app entrypoint and startup lifecycle.
- `api/src/routers/`: HTTP endpoints (`health`, `jobs`).
- `api/src/tasks/`: Celery app and background tasks.
- `api/src/services/`: Integrations (LLM, storage, extraction, webhook).
- `api/src/jobs/`: Job models, schemas, enums, CRUD, reliability constants.
- `api/src/tenant/`: Tenant models, validation schemas, routes, CRUD.
- `api/src/auth/`: Security, token, and auth dependencies.
- `api/src/database/`: SQLAlchemy and Redis client setup.
- `alembic/`: DB migrations.
- `tests/`: Test suite.

Package-level READMEs are available under `api/src/*/README.md`.

## How It Works

### 1. Job Submission

`POST /api/v1/jobs`

- Tenant authenticates using `X-API-Key`.
- File is validated by MIME type.
- Extraction schema is accepted as JSON or raw string.
- File hash is checked against Redis Bloom filter for duplicate detection.
- File is uploaded to S3-compatible storage.
- Job is created in Postgres with `PENDING` or `QUEUED_AI_OUTAGE` status.
- If the AI breaker is closed, a Celery task is enqueued.

### 2. Background Processing (`process_job_task`)

Worker flow:

1. Load job and mark as `PROCESSING`.
2. Download file from storage.
3. Extract plain text from document.
4. Run LLM extraction (`run_extraction`).
5. Persist result and mark `COMPLETE`.
6. Deliver webhook (if configured).

### 3. LLM Extraction Strategy (`api/src/services/llm.py`)

- Uses strict JSON response mode (`response_format={"type": "json_object"}`).
- Uses output cap (`max_tokens=8192`).
- Applies prompt-budget checks before each call.
- For small docs: single-shot extraction.
- For large docs:
	- Map phase: chunked extraction with semaphore throttling.
	- Reduce phase: batched multi-round merge with semaphore throttling.
	- Recursive merge fallback if any merge group still hits context limits.
- JSON robustness:
	- Primary parse via `json.loads`.
	- Fallback auto-repair via `json-repair` for truncated/malformed JSON.

### 4. Reliability & Failure Semantics

- `BadRequestError` (e.g., hard context/request issues): treated as permanent (`DEAD`).
- `JSONDecodeError`: treated as retryable first, retried with 30s delay, then `DEAD` after max retries.
- Generic exceptions: retried with Celery backoff.
- AI outage detection can trip circuit breaker and queue jobs as `QUEUED_AI_OUTAGE`.
- Sweeper task requeues stale pending jobs when breaker is closed.

## API Endpoints

### Health

- `GET /health`

### Tenant

- `POST /api/v1/tenants` create tenant
- `POST /api/v1/tenants/login` tenant login + API key rotation
- `GET /api/v1/tenants/me` current tenant profile
- `PATCH /api/v1/tenants/me` update tenant fields
- `DELETE /api/v1/tenants/me` deactivate tenant

### Jobs

- `POST /api/v1/jobs` submit extraction job
- `GET /api/v1/jobs/{job_id}` get job status/result
- `GET /api/v1/jobs` list tenant jobs
- `DELETE /api/v1/jobs/{job_id}` cancel queued job

## Configuration

Configuration is loaded from `.env` via `api/src/config_package/settings.py`.

Important variables:

- `database_url`
- `SECRET_KEY`
- `ALGORITHM`
- `openai_api_key`
- `openai_model`
- `openai_base_url`
- `redis_url`
- `celery_task_default_queue`
- `s3_endpoint_url`
- `s3_access_key_id`
- `s3_secret_access_key`
- `s3_region`
- `s3_bucket_name`

## Local Development

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set up environment

Create `.env` with required values.

### 3. Run API

```bash
uvicorn main:app --reload
```

### 4. Run Celery worker

```bash
celery -A api.src.tasks.celery_app:celery_app worker -l info
```

### 5. Run Celery beat (for sweepers)

```bash
celery -A api.src.tasks.celery_app:celery_app beat -l info
```

### 6. Migrations

```bash
alembic upgrade head
```

## Testing

Run tests:

```bash
python -m pytest -q
```

Current verified state: `14 passed`.

## Debugging & Observability

- Rich tracebacks enabled in API and Celery bootstrap (`install(show_locals=True)`).
- Correlation IDs are tracked across submission and worker logs.
- Job status and error logs are persisted in Postgres.

## Security Notes

- Tenant API keys are hashed before persistence.
- Passwords are Argon2-hashed.
- Webhook destinations are validated and private/reserved IPs are blocked.
- Refresh token records include session metadata and revocation/usage fields.

## Operational Notes

- Restart Celery workers after task/service code changes.
- Restart Celery beat after schedule changes.
- Circuit breaker state is Redis-backed and automatically expires.

## License

Internal project. Add your organization license policy here.
