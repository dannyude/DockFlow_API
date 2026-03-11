"""Job API routes for submission, status lookup, listing, and cancellation."""

import hashlib
import json
import time
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.src.database.postgres_client import get_session
from api.src.database.redis_client import redis_db
from api.src.dependencies import get_current_tenant
from api.src.jobs.crud import create_job, get_job_for_tenant, list_jobs_for_tenant
from api.src.jobs.enums import JobStatus
from api.src.jobs.models import Job
from api.src.jobs.reliability import AI_BREAKER_OPEN_UNTIL_KEY
from api.src.jobs.schemas import JobCreate, JobResponse, JobStatusResponse
from api.src.rate_limit import limiter
from api.src.services.storage import upload_to_s3
from api.src.services.webhook import validate_webhook_url
from api.src.tasks.celery_app import celery_app
from api.src.tenant.models import Tenant

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/tiff",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=JobResponse)
@limiter.limit("20/minute")
async def submit_job(
    request: Request,
    file: UploadFile = File(...),
    extraction_schema: str = Form(...),
    webhook_url: str | None = Form(None),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_session),
) -> JobResponse:
    """Validate upload and schema, create a job, and enqueue worker processing."""
    _ = request
    correlation_id = str(uuid4())

    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(400, f"Unsupported file type: {file.content_type}")

    # Try to parse as JSON; if it fails, accept the raw string for AI to interpret
    try:
        parsed_schema = json.loads(extraction_schema)
    except json.JSONDecodeError:
        parsed_schema = extraction_schema

    try:
        schema = JobCreate(
            extraction_schema=parsed_schema, webhook_url=webhook_url
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    file_bytes = await file.read()
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    is_probably_a_duplicate = await redis_db.execute_command(
        "BF.EXISTS", "docflow_pdf_bloom", file_hash
    )

    if is_probably_a_duplicate:
        smt = select(Job).where(Job.file_hash == file_hash, Job.tenant_id == tenant.id)
        existing_job = (await db.execute(smt)).scalars().first()

        if existing_job:
            raise HTTPException(
                status_code=409,
                detail=f"A job with the same file has already been submitted (Job ID: {existing_job.id})",
            )

    await redis_db.execute_command("BF.ADD", "docflow_pdf_bloom", file_hash)

    s3_key = await upload_to_s3(
        file_bytes,
        file.filename or "upload.bin",
        str(tenant.id),
        correlation_id=correlation_id,
    )

    breaker_open_until_raw = await redis_db.get(AI_BREAKER_OPEN_UNTIL_KEY)
    now_ts = int(time.time())
    ai_circuit_open = bool(
        breaker_open_until_raw and int(breaker_open_until_raw) > now_ts
    )

    initial_status = JobStatus.QUEUED_AI_OUTAGE if ai_circuit_open else JobStatus.PENDING
    effective_webhook_url = webhook_url or tenant.webhook_url

    if effective_webhook_url:
        try:
            effective_webhook_url = validate_webhook_url(effective_webhook_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    job = await create_job(
        db,
        tenant_id=tenant.id,
        file_name=file.filename or "upload.bin",
        file_s3_key=s3_key,
        file_mime_type=file.content_type,
        file_hash=file_hash,
        correlation_id=correlation_id,
        extraction_schema=schema.extraction_schema if isinstance(schema.extraction_schema, dict) else {"raw": schema.extraction_schema},
        webhook_url=effective_webhook_url,
        status=initial_status,
        mark_enqueued=not ai_circuit_open,
    )

    if not ai_circuit_open:
        cast(Any, celery_app).send_task(
            "api.src.tasks.process_job.process_job_task",
            args=[str(job.id), correlation_id],
        )

    return JobResponse(
        job_id=str(job.id),
        correlation_id=correlation_id,
        status=job.status.value,
    )


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(
    job_id: UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_session),
) -> JobStatusResponse:
    """Return a tenant-scoped status payload for a single job."""
    job = await get_job_for_tenant(db, job_id=job_id, tenant_id=tenant.id)
    if not job:
        raise HTTPException(404, "Job not found")

    return JobStatusResponse(
        job_id=str(job.id),
        correlation_id=job.correlation_id,
        status=job.status.value,
        progress_message=job.progress_message,
        result=job.result,
        error=job.error_log,
        created_at=job.created_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


@router.get("", response_model=list[JobStatusResponse])
async def list_jobs(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_session),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[JobStatusResponse]:
    """List paginated jobs for the current tenant."""
    jobs = await list_jobs_for_tenant(db, tenant_id=tenant.id, limit=limit, offset=offset)

    return [
        JobStatusResponse(
            job_id=str(job.id),
            correlation_id=job.correlation_id,
            status=job.status.value,
            progress_message=job.progress_message,
            result=job.result,
            error=job.error_log,
            created_at=job.created_at.isoformat(),
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
        )
        for job in jobs
    ]


@router.delete("/{job_id}")
async def cancel_job(
    job_id: UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Cancel a job that has not started worker execution yet."""
    job = await get_job_for_tenant(db, job_id=job_id, tenant_id=tenant.id)
    if not job:
        raise HTTPException(404, "Job not found")

    if job.status not in (JobStatus.PENDING, JobStatus.QUEUED_AI_OUTAGE):
        raise HTTPException(409, "Only queued jobs can be cancelled")

    job.status = JobStatus.DEAD
    job.error_log = "Cancelled by tenant before processing"
    await db.commit()

    return {"job_id": str(job.id), "status": job.status.value}
