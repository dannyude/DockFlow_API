<div align="center">

<br/>

<h1>
  <img src="https://img.shields.io/badge/DocFlow-API-4F46E5?style=for-the-badge&logoColor=white" alt="DocFlow API" height="42"/>
</h1>

<p><em>Multi-tenant document extraction service powered by LLM map-reduce — built for scale, reliability, and real-time observability.</em></p>

<br/>

<!-- Tech Badges -->
<img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white"/>
<img src="https://img.shields.io/badge/Celery-37814A?style=flat-square&logo=celery&logoColor=white"/>
<img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white"/>
<img src="https://img.shields.io/badge/Redis-DC382D?style=flat-square&logo=redis&logoColor=white"/>
<img src="https://img.shields.io/badge/S3-FF9900?style=flat-square&logo=amazon-s3&logoColor=white"/>
<img src="https://img.shields.io/badge/OpenAI%20SDK-412991?style=flat-square&logo=openai&logoColor=white"/>
<img src="https://img.shields.io/badge/Alembic-6B6B6B?style=flat-square&logoColor=white"/>
<img src="https://img.shields.io/badge/Pydantic-E92063?style=flat-square&logo=pydantic&logoColor=white"/>

<br/><br/>

<!-- Status Badges -->
<img src="https://img.shields.io/badge/tests-24%20passed-22C55E?style=flat-square"/>
<img src="https://img.shields.io/badge/license-MIT-3B82F6?style=flat-square"/>
<img src="https://img.shields.io/badge/python-3.10%2B-F59E0B?style=flat-square&logo=python&logoColor=white"/>

<br/><br/>

---

</div>

## Overview

DocFlow API accepts uploaded files **(PDF / images / DOCX)**, extracts plain text, runs **schema-driven LLM extraction**, and returns structured JSON results via async polling and optional webhooks.

It is designed as a **multi-tenant SaaS backend** — every tenant is fully isolated, API keys are hashed, and the LLM pipeline is built with multiple layers of reliability so a single model outage never permanently blocks a job.

<br/>

---

## ✦ Core Features

<table>
<tr>
<td width="50%" valign="top">

**Platform**
- Multi-tenant API-key authentication
- File upload & async extraction jobs
- Duplicate detection via Redis Bloom filter
- Optional webhook callbacks on completion
- Real-time job progress messages persisted to DB

</td>
<td width="50%" valign="top">

**Reliability**
- LLM map-reduce for arbitrarily large documents
- Context-budgeting & bounded merge strategy
- Concurrency throttling (semaphore-gated)
- AI outage circuit breaker
- Retry / exponential backoff via Celery
- `json-repair` fallback for malformed LLM output

</td>
</tr>
</table>

<br/>

---

## ⚙ Tech Stack

<table>
<thead>
<tr>
<th>Layer</th>
<th>Technology</th>
<th>Role</th>
</tr>
</thead>
<tbody>
<tr><td>API</td><td><b>FastAPI</b></td><td>HTTP framework, routing, dependency injection</td></tr>
<tr><td>Async DB</td><td><b>SQLAlchemy (async)</b></td><td>ORM for API routes</td></tr>
<tr><td>Worker</td><td><b>Celery</b></td><td>Background extraction tasks</td></tr>
<tr><td>Queue / Cache</td><td><b>Redis</b></td><td>Task broker, Bloom filter, circuit breaker state</td></tr>
<tr><td>Database</td><td><b>PostgreSQL</b></td><td>Primary data store, job records, tenants, tokens</td></tr>
<tr><td>Storage</td><td><b>S3-compatible</b></td><td>MinIO (local) / AWS S3 (production)</td></tr>
<tr><td>LLM Client</td><td><b>AsyncOpenAI SDK</b></td><td>OpenAI or DeepSeek via configurable <code>base_url</code></td></tr>
<tr><td>Validation</td><td><b>Pydantic v2</b></td><td>Request / response schema validation</td></tr>
<tr><td>Migrations</td><td><b>Alembic</b></td><td>DB schema versioning</td></tr>
<tr><td>Testing</td><td><b>Pytest</b></td><td>Unit & integration test suite</td></tr>
</tbody>
</table>

<br/>

---

## Project Layout

```
DocFlow API/
├── main.py                        # FastAPI app entrypoint & lifecycle
├── api/src/
│   ├── routers/                   # HTTP route handlers (health, jobs)
│   ├── tasks/                     # Celery app + background tasks
│   ├── services/                  # LLM, storage, extraction, webhook
│   │   ├── llm.py                 # Map-reduce orchestration
│   │   ├── llm_prompts.py         # Prompt builders
│   │   └── llm_limits.py          # Token budgeting & chunking
│   ├── jobs/                      # Job models, schemas, enums, CRUD
│   ├── tenant/                    # Tenant models, routes, CRUD
│   ├── auth/                      # Security, tokens, auth dependencies
│   └── database/                  # SQLAlchemy & Redis client setup
├── alembic/                       # DB migration versions
└── tests/                         # Pytest test suite
```

<br/>

---

## How It Works

<details>
<summary><b>1 — Job Submission &nbsp;·&nbsp; <code>POST /api/v1/jobs</code></b></summary>
<br/>

| Step | Detail |
|------|--------|
| Auth | Tenant authenticates via `X-API-Key` header |
| Validation | File MIME type checked; extraction schema accepted as JSON or raw string |
| Dedup | File SHA-256 hash verified against Redis Bloom filter |
| Storage | File uploaded to S3-compatible store |
| Dispatch | Job created in Postgres (`PENDING` or `QUEUED_AI_OUTAGE`); Celery task enqueued if breaker is closed |

</details>

<details>
<summary><b>2 — Background Processing &nbsp;·&nbsp; <code>process_job_task</code></b></summary>
<br/>

```
Load job → PROCESSING
  ↓
Download file from S3
  ↓
Extract plain text (OCR / DOCX / PDF)
  ↓
Run LLM extraction (run_extraction)
  ↓
Persist result → COMPLETE
  ↓
Deliver webhook (if configured)
```

Real-time `progress_message` is written to the job record at each phase so clients can display live progress via polling.

</details>

<details>
<summary><b>3 — LLM Extraction Strategy &nbsp;·&nbsp; <code>api/src/services/llm.py</code></b></summary>
<br/>

| Mode | When | How |
|------|------|-----|
| **Single-shot** | Small documents | One LLM call with full document in context |
| **Map phase** | Large documents | Document chunked → parallel LLM calls (semaphore-gated, max 5 concurrent) |
| **Reduce phase** | After map | Partial results batched → multi-round merge (semaphore-gated); recursive fallback if any merge group still hits context limits |

**JSON robustness:**
1. Primary parse via `json.loads`
2. Fallback auto-repair via `json-repair` for truncated / malformed responses
3. `max_tokens=8192` output cap prevents silent truncation

</details>

<details>
<summary><b>4 — Reliability & Failure Semantics</b></summary>
<br/>

| Error Type | Behaviour |
|-----------|-----------|
| `BadRequestError` (hard context / request error) | Immediately marked `DEAD` |
| `JSONDecodeError` | Retried with 30 s delay; `DEAD` after max retries |
| Generic exception | Retried with Celery exponential backoff |
| AI provider outage | Circuit breaker trips; jobs queued as `QUEUED_AI_OUTAGE`; sweeper requeues when breaker closes |

</details>

<br/>

---

## API Reference

<details open>
<summary><b>Endpoints</b></summary>
<br/>

**Health**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Service health check |

**Tenant**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/tenants` | Create tenant |
| `POST` | `/api/v1/tenants/login` | Login + API key rotation |
| `GET` | `/api/v1/tenants/me` | Current tenant profile |
| `PATCH` | `/api/v1/tenants/me` | Update tenant fields |
| `DELETE` | `/api/v1/tenants/me` | Deactivate tenant |

**Jobs**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/jobs` | Submit extraction job |
| `GET` | `/api/v1/jobs/{job_id}` | Get job status / result / progress |
| `GET` | `/api/v1/jobs` | List all tenant jobs |
| `DELETE` | `/api/v1/jobs/{job_id}` | Cancel queued job |

</details>

<br/>

---

## Configuration

Configuration is loaded from `.env` via `api/src/config_package/settings.py`. Copy [`.env.example`](.env.example) to get started.

<details>
<summary><b>Environment Variables</b></summary>
<br/>

| Variable | Description |
|----------|-------------|
| `database_url` | PostgreSQL connection string |
| `SECRET_KEY` | JWT signing secret |
| `ALGORITHM` | JWT algorithm (e.g. `HS256`) |
| `openai_api_key` | LLM provider API key |
| `openai_model` | Model name (e.g. `deepseek-chat`) |
| `openai_base_url` | Override for DeepSeek / alternative providers |
| `redis_url` | Redis connection string |
| `celery_task_default_queue` | Default Celery queue name |
| `s3_endpoint_url` | S3 / MinIO endpoint |
| `s3_access_key_id` | S3 access key |
| `s3_secret_access_key` | S3 secret key |
| `s3_region` | S3 region |
| `s3_bucket_name` | Target bucket name |

</details>

<br/>

---

## Local Development

**Prerequisites**
- Python 3.10+
- Docker (for Postgres, Redis and MinIO)
- [Tesseract OCR](https://tesseract-ocr.github.io/tessdoc/Installation.html), only needed to process image uploads (`apt install tesseract-ocr` / `brew install tesseract`)

**1. Create a virtual environment and install dependencies**
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```
*Using [uv](https://docs.astral.sh/uv/)? `uv sync` installs from `uv.lock` instead.*

**2. Set up environment**
```bash
cp .env.example .env   # add your LLM API key; other defaults match docker-compose.yml
```

**3. Start Postgres, Redis and MinIO**
```bash
docker compose up -d
```
Redis runs as `redis-stack`, which includes the Bloom filter module used for duplicate detection. The S3 bucket is created automatically when the API starts.

**4. Apply migrations**
```bash
alembic upgrade head
```
Run this before starting the API for the first time. If you have a database that the API created on startup, before migrations existed, mark it as current with `alembic stamp head` instead.

**5. Start the API**
```bash
uvicorn main:app --reload
```
Interactive docs are at http://localhost:8000/docs.

**6. Start the Celery worker**
```bash
celery -A api.src.tasks.celery_app:celery_app worker -l info
```

**7. Start Celery beat** *(sweepers)*
```bash
celery -A api.src.tasks.celery_app:celery_app beat -l info
```

<br/>

---

## Testing

The test suite mocks Postgres, Redis, S3 and the LLM, so it needs no running services. It does need a `.env`, and the defaults from `.env.example` are enough:

```bash
cp .env.example .env   # skip if you already did this above
python -m pytest -q
```

> **Current verified state: 24 passed**

Tests cover: health, reliability semantics, tenant login, extractor pipeline, and LLM helper modules (`llm_limits`, `llm_prompts`).

<br/>

---

## Observability

- **Rich tracebacks** enabled in both API and Celery worker (`install(show_locals=True)`)
- **Correlation IDs** tracked across job submission and worker logs
- **Live progress messages** written to `jobs.progress_message` at each extraction phase
- **Error logs** persisted per-job in Postgres for post-mortem analysis

<br/>

---

## Security

| Concern | Implementation |
|---------|---------------|
| API key storage | Hashed before DB persistence (never stored in plain text) |
| Passwords | Argon2-hashed |
| Webhooks | Destination URLs validated; private / reserved IPs blocked (SSRF protection) |
| Refresh tokens | Session metadata, revocation + usage tracking |
| Rate limiting | SlowAPI per-tenant limits on all job endpoints |

<br/>

---

## Operational Notes

> **After any code change:**
> - Restart Celery **workers** after modifying task or service code.
> - Restart Celery **beat** after changing scheduled task intervals.
> - Run `alembic upgrade head` after pulling new migrations.

<br/>

---

## License

```
MIT License

Copyright (c) 2026 DocFlow

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

<div align="center">
<br/>
<sub>Built with FastAPI · Celery · PostgreSQL · Redis · OpenAI SDK</sub>
</div>
