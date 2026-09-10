import asyncio
import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.src.jobs.enums import JobStatus
from api.src.routers import jobs as jobs_router


def _fake_request() -> Any:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/jobs",
        "headers": [],
        "query_string": b"",
    }
    return Request(scope)
from api.src.tasks import process_job as process_job_module
from api.src.tasks import sweep_pending_jobs as sweeper_module


class DummyDbSession:
    def __init__(self, job=None, jobs=None):
        self._job = job
        self._jobs = jobs or []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, _model, _job_id):
        return self._job

    def commit(self):
        self.commits += 1

    def execute(self, _statement):
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: self._jobs)
        )


def test_process_job_idempotent_when_already_complete(monkeypatch):
    job = SimpleNamespace(
        id=uuid4(),
        status=JobStatus.COMPLETE,
        webhook_url=None,
    )
    db = DummyDbSession(job=job)

    monkeypatch.setattr(process_job_module, "SyncSessionLocal", lambda: db)
    monkeypatch.setattr(
        process_job_module,
        "download_from_s3",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not download")),
    )

    cast(Any, process_job_module.process_job_task).run(str(job.id), "corr-id-1")

    assert job.status == JobStatus.COMPLETE
    assert db.commits == 0


def test_process_job_marks_queued_when_circuit_open(monkeypatch):
    job = SimpleNamespace(
        id=uuid4(),
        status=JobStatus.PENDING,
        error_log=None,
        webhook_url=None,
    )
    db = DummyDbSession(job=job)

    monkeypatch.setattr(process_job_module, "SyncSessionLocal", lambda: db)
    monkeypatch.setattr(process_job_module, "_is_ai_outage_open", lambda: True)

    cast(Any, process_job_module.process_job_task).run(str(job.id), "corr-id-2")

    assert job.status == JobStatus.QUEUED_AI_OUTAGE
    assert "circuit breaker" in (job.error_log or "")
    assert db.commits == 1


def test_sweeper_requeues_stuck_jobs(monkeypatch):
    now = datetime.now(timezone.utc)
    old_job = SimpleNamespace(
        id=uuid4(),
        correlation_id="corr-sweep-1",
        status=JobStatus.PENDING,
        enqueue_attempts=0,
        last_enqueued_at=None,
        error_log=None,
        created_at=now - timedelta(minutes=30),
    )
    db = DummyDbSession(jobs=[old_job])

    sent = []

    monkeypatch.setattr(sweeper_module, "SyncSessionLocal", lambda: db)
    monkeypatch.setattr(sweeper_module, "pending_cutoff", lambda: now - timedelta(minutes=10))
    monkeypatch.setattr(sweeper_module.redis_sync, "get", lambda _k: None)
    monkeypatch.setattr(
        sweeper_module.celery_app,
        "send_task",
        lambda task_name, args: sent.append((task_name, args)),
    )

    cast(Any, sweeper_module.sweep_stuck_jobs_task).run()

    assert old_job.enqueue_attempts == 1
    assert old_job.last_enqueued_at is not None
    assert sent == [
        ("api.src.tasks.process_job.process_job_task", [str(old_job.id), "corr-sweep-1"])
    ]
    assert db.commits == 1


def test_sweeper_abandons_poison_job_after_max_attempts(monkeypatch):
    from api.src.jobs.reliability import MAX_ENQUEUE_ATTEMPTS

    now = datetime.now(timezone.utc)
    poison_job = SimpleNamespace(
        id=uuid4(),
        correlation_id="corr-poison-1",
        status=JobStatus.PENDING,
        enqueue_attempts=MAX_ENQUEUE_ATTEMPTS,
        last_enqueued_at=now - timedelta(minutes=5),
        error_log=None,
        created_at=now - timedelta(minutes=60),
    )
    db = DummyDbSession(jobs=[poison_job])

    sent = []

    monkeypatch.setattr(sweeper_module, "SyncSessionLocal", lambda: db)
    monkeypatch.setattr(sweeper_module, "pending_cutoff", lambda: now - timedelta(minutes=10))
    monkeypatch.setattr(sweeper_module.redis_sync, "get", lambda _k: None)
    monkeypatch.setattr(
        sweeper_module.celery_app,
        "send_task",
        lambda task_name, args: sent.append((task_name, args)),
    )

    cast(Any, sweeper_module.sweep_stuck_jobs_task).run()

    assert poison_job.status == JobStatus.DEAD
    assert sent == []
    assert db.commits == 1


def test_submit_job_propagates_correlation_id(monkeypatch):
    tenant_id = uuid4()
    captured = {}

    async def fake_execute_command(command, _key, _value):
        if command == "BF.EXISTS":
            return 0
        if command == "BF.ADD":
            return 1
        raise AssertionError(f"unexpected redis command: {command}")

    async def fake_get(_key):
        return None

    async def fake_upload(_file_bytes, _filename, tenant_id_str, *, correlation_id):
        captured["upload_correlation"] = correlation_id
        captured["tenant_id"] = tenant_id_str
        return f"{tenant_id_str}/{correlation_id}/obj.pdf"

    async def fake_create_job(
        _db,
        *,
        tenant_id,
        file_name,
        file_s3_key,
        file_mime_type,
        file_hash,
        correlation_id,
        extraction_schema,
        webhook_url,
        status,
        mark_enqueued,
    ):
        captured["create_correlation"] = correlation_id
        captured["status"] = status
        captured["mark_enqueued"] = mark_enqueued
        return SimpleNamespace(id=uuid4(), status=status, correlation_id=correlation_id)

    sent = []

    monkeypatch.setattr(jobs_router.redis_db, "execute_command", fake_execute_command)
    monkeypatch.setattr(jobs_router.redis_db, "get", fake_get)
    monkeypatch.setattr(jobs_router, "upload_to_s3", fake_upload)
    monkeypatch.setattr(jobs_router, "create_job", fake_create_job)
    monkeypatch.setattr(jobs_router, "validate_webhook_url", lambda url: url)
    monkeypatch.setattr(
        jobs_router.celery_app,
        "send_task",
        lambda task_name, args: sent.append((task_name, args)),
    )

    async def _read_sample() -> bytes:
        return io.BytesIO(b"%PDF-1.4 fake").read()

    upload = SimpleNamespace(
        filename="sample.pdf",
        content_type="application/pdf",
        read=_read_sample,
    )

    tenant = cast(Any, SimpleNamespace(id=tenant_id, webhook_url="https://example.test/webhook"))
    db = cast(Any, object())

    result = asyncio.run(
        jobs_router.submit_job(
            request=_fake_request(),
            file=cast(Any, upload),
            extraction_schema='{"fields": [{"name": "invoice_number", "type": "string", "description": "invoice id"}]}',
            webhook_url=None,
            tenant=tenant,
            db=db,
        )
    )

    assert result.correlation_id == captured["upload_correlation"] == captured["create_correlation"]
    assert captured["tenant_id"] == str(tenant_id)
    assert sent[0][0] == "api.src.tasks.process_job.process_job_task"
    assert sent[0][1][1] == result.correlation_id
    assert result.status == JobStatus.PENDING.value


def test_submit_job_queues_when_breaker_open(monkeypatch):
    tenant_id = uuid4()

    async def fake_execute_command(command, _key, _value):
        if command == "BF.EXISTS":
            return 0
        if command == "BF.ADD":
            return 1
        raise AssertionError(f"unexpected redis command: {command}")

    now_ts = int(datetime.now(timezone.utc).timestamp())

    async def fake_get(_key):
        return str(now_ts + 600)

    async def fake_upload(_file_bytes, _filename, tenant_id_str, *, correlation_id):
        return f"{tenant_id_str}/{correlation_id}/obj.pdf"

    async def fake_create_job(
        _db,
        *,
        tenant_id,
        file_name,
        file_s3_key,
        file_mime_type,
        file_hash,
        correlation_id,
        extraction_schema,
        webhook_url,
        status,
        mark_enqueued,
    ):
        return SimpleNamespace(id=uuid4(), status=status, correlation_id=correlation_id)

    sent = []

    monkeypatch.setattr(jobs_router.redis_db, "execute_command", fake_execute_command)
    monkeypatch.setattr(jobs_router.redis_db, "get", fake_get)
    monkeypatch.setattr(jobs_router, "upload_to_s3", fake_upload)
    monkeypatch.setattr(jobs_router, "create_job", fake_create_job)
    monkeypatch.setattr(
        jobs_router.celery_app,
        "send_task",
        lambda task_name, args: sent.append((task_name, args)),
    )

    async def _read_sample() -> bytes:
        return io.BytesIO(b"%PDF-1.4 fake").read()

    upload = SimpleNamespace(
        filename="sample.pdf",
        content_type="application/pdf",
        read=_read_sample,
    )

    tenant = cast(Any, SimpleNamespace(id=tenant_id, webhook_url=None))
    db = cast(Any, object())

    result = asyncio.run(
        jobs_router.submit_job(
            request=_fake_request(),
            file=cast(Any, upload),
            extraction_schema='{"fields": [{"name": "total", "type": "float", "description": "amount"}]}',
            webhook_url=None,
            tenant=tenant,
            db=db,
        )
    )

    assert result.status == JobStatus.QUEUED_AI_OUTAGE.value
    assert sent == []


def test_submit_job_rejects_invalid_tenant_webhook_url(monkeypatch):
    tenant_id = uuid4()

    async def fake_execute_command(command, _key, _value):
        if command == "BF.EXISTS":
            return 0
        if command == "BF.ADD":
            return 1
        raise AssertionError(f"unexpected redis command: {command}")

    async def fake_get(_key):
        return None

    async def fake_upload(_file_bytes, _filename, tenant_id_str, *, correlation_id):
        return f"{tenant_id_str}/{correlation_id}/obj.pdf"

    async def should_not_create_job(_db, **_kwargs):
        raise AssertionError("create_job should not be called for invalid webhook URL")

    monkeypatch.setattr(jobs_router.redis_db, "execute_command", fake_execute_command)
    monkeypatch.setattr(jobs_router.redis_db, "get", fake_get)
    monkeypatch.setattr(jobs_router, "upload_to_s3", fake_upload)
    monkeypatch.setattr(jobs_router, "create_job", should_not_create_job)
    monkeypatch.setattr(
        jobs_router.celery_app,
        "send_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not enqueue")),
    )

    async def _read_sample() -> bytes:
        return io.BytesIO(b"%PDF-1.4 fake").read()

    upload = SimpleNamespace(
        filename="sample.pdf",
        content_type="application/pdf",
        read=_read_sample,
    )

    tenant = cast(Any, SimpleNamespace(id=tenant_id, webhook_url="example.test/webhook"))
    db = cast(Any, object())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            jobs_router.submit_job(
                request=_fake_request(),
                file=cast(Any, upload),
                extraction_schema='{"fields": [{"name": "total", "type": "float", "description": "amount"}]}',
                webhook_url=None,
                tenant=tenant,
                db=db,
            )
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == "Webhook URL must include http:// or https://"
