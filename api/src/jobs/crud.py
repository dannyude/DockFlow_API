"""Data-access helpers for job creation, retrieval, and listing."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.src.jobs.enums import JobStatus
from api.src.jobs.models import Job



async def create_job(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    file_name: str,
    file_s3_key: str,
    file_mime_type: str,
    file_hash: str,
    correlation_id: str,
    extraction_schema: dict,
    webhook_url: str | None,
    status: JobStatus = JobStatus.PENDING,
    mark_enqueued: bool = True,
) -> Job:
    """Create and persist a new extraction job for a tenant."""
    job = Job(
        tenant_id=tenant_id,
        status=status,
        file_name=file_name,
        file_s3_key=file_s3_key,
        file_mime_type=file_mime_type,
        file_hash=file_hash,
        correlation_id=correlation_id,
        extraction_schema=extraction_schema,
        webhook_url=webhook_url,
        enqueue_attempts=1 if mark_enqueued else 0,
        last_enqueued_at=datetime.now(timezone.utc) if mark_enqueued else None,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def get_job_for_tenant(
    db: AsyncSession, *, job_id: UUID, tenant_id: UUID
) -> Job | None:
    """Fetch a single job only if it belongs to the requesting tenant."""
    res = await db.execute(
        select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id)
    )
    return res.scalar_one_or_none()


async def list_jobs_for_tenant(
    db: AsyncSession, *, tenant_id: UUID, limit: int, offset: int
) -> list[Job]:
    """List tenant jobs ordered by newest first with pagination controls."""
    res = await db.execute(
        select(Job)
        .where(Job.tenant_id == tenant_id)
        .order_by(Job.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(res.scalars().all())
