"""Periodic task that requeues jobs stuck in pending-like states."""

from datetime import datetime, timezone
from typing import Any, cast

from celery import shared_task
from celery.utils.log import get_task_logger
from sqlalchemy import or_, select

from api.src.config_package.settings import get_settings
from api.src.database.postgres_client import SyncSessionLocal
from api.src.jobs.enums import JobStatus
from api.src.jobs.models import Job
from api.src.jobs.reliability import (
    AI_BREAKER_OPEN_UNTIL_KEY,
    MAX_ENQUEUE_ATTEMPTS,
    SWEEPER_INTERVAL_MINUTES,
    pending_cutoff,
)
from api.src.tasks.celery_app import celery_app

import redis

cfg = get_settings()
redis_sync = redis.Redis.from_url(cfg.redis_url, decode_responses=True)
logger = get_task_logger(__name__)


@shared_task(bind=True)
def sweep_stuck_jobs_task(_self) -> None:
    """Find stale queued jobs and re-enqueue them when the AI circuit is closed."""
    now = datetime.now(timezone.utc)
    cutoff = pending_cutoff()

    open_until_raw = cast(Any, redis_sync.get(AI_BREAKER_OPEN_UNTIL_KEY))
    circuit_open = bool(open_until_raw and int(str(open_until_raw)) > int(now.timestamp()))

    with SyncSessionLocal() as db:
        statement = select(Job).where(
            or_(
                Job.status == JobStatus.PENDING,
                Job.status == JobStatus.QUEUED_AI_OUTAGE,
            ),
            Job.created_at <= cutoff,
        )
        jobs = list(db.execute(statement).scalars().all())

        if not jobs:
            logger.info("Sweeper found no stuck jobs")
            return

        requeued = 0
        dead = 0
        for job in jobs:
            if circuit_open:
                job.status = JobStatus.QUEUED_AI_OUTAGE
                job.error_log = "Waiting for AI circuit breaker to close"
                continue

            # Give up on poison jobs that never reach a terminal state so they
            # do not get re-enqueued on every sweep cycle forever.
            if job.enqueue_attempts >= MAX_ENQUEUE_ATTEMPTS:
                job.status = JobStatus.DEAD
                job.error_log = (
                    f"Exceeded max enqueue attempts ({MAX_ENQUEUE_ATTEMPTS}); "
                    "abandoned by sweeper"
                )
                dead += 1
                continue

            if job.status == JobStatus.QUEUED_AI_OUTAGE:
                job.status = JobStatus.PENDING

            job.enqueue_attempts += 1
            job.last_enqueued_at = now
            cast(Any, celery_app).send_task(
                "api.src.tasks.process_job.process_job_task",
                args=[str(job.id), job.correlation_id],
            )
            requeued += 1

        db.commit()
        logger.info(
            "Sweeper examined %s jobs, requeued %s, abandoned %s (interval=%s min)",
            len(jobs),
            requeued,
            dead,
            SWEEPER_INTERVAL_MINUTES,
        )
