"""Celery task that executes the document extraction lifecycle for a job.

This module coordinates storage download, text extraction, LLM extraction,
database status transitions, webhook delivery, retry logic, and AI outage
circuit-breaker behavior.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, cast

import httpx
import redis
from celery import shared_task
from celery.utils.log import get_task_logger
from openai import BadRequestError
from sqlalchemy.exc import SQLAlchemyError

from api.src.config_package.settings import get_settings
from api.src.database.model_registry import import_models
from api.src.database.postgres_client import SyncSessionLocal
from api.src.jobs.enums import JobStatus
from api.src.jobs.models import Job
from api.src.jobs.reliability import (
    AI_BREAKER_FAILURE_KEY,
    AI_BREAKER_FAILURE_THRESHOLD,
    AI_BREAKER_OPEN_SECONDS,
    AI_BREAKER_OPEN_UNTIL_KEY,
)
from api.src.services.extractor import extract_text
from api.src.services.llm import run_extraction
from api.src.services.storage import download_from_s3
from api.src.services.webhook import deliver_webhook

cfg = get_settings()
import_models()
redis_sync = redis.Redis.from_url(cfg.redis_url, decode_responses=True)
logger = get_task_logger(__name__)


def _is_ai_outage_open() -> bool:
    """Return True when the AI outage circuit is currently open."""
    open_until_raw = cast(Any, redis_sync.get(AI_BREAKER_OPEN_UNTIL_KEY))
    if not open_until_raw:
        return False
    return int(str(open_until_raw)) > int(datetime.now(timezone.utc).timestamp())


def _trip_ai_circuit() -> int:
    """Open the AI outage circuit for a fixed cooldown period."""
    open_until_ts = int(datetime.now(timezone.utc).timestamp()) + AI_BREAKER_OPEN_SECONDS
    redis_sync.set(AI_BREAKER_OPEN_UNTIL_KEY, open_until_ts, ex=AI_BREAKER_OPEN_SECONDS)
    redis_sync.delete(AI_BREAKER_FAILURE_KEY)
    return open_until_ts


def _register_ai_success() -> None:
    """Clear tracked AI failures after a successful provider call."""
    redis_sync.delete(AI_BREAKER_FAILURE_KEY)


def _register_ai_failure() -> int:
    """Increment and return consecutive AI failure count."""
    return int(str(cast(Any, redis_sync.incr(AI_BREAKER_FAILURE_KEY))))


def _is_ai_upstream_failure(exc: Exception) -> bool:
    """Detect likely provider-side failures that should affect the circuit breaker."""
    message = str(exc).lower()
    ai_related_markers = (
        "upstream provider",
        "openai",
        "deepseek",
        "temporarily unavailable",
        "internal server error",
        "status code: 500",
        "500",
    )
    return any(marker in message for marker in ai_related_markers)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    retry_backoff=True,
    retry_backoff_max=600,
    acks_late=True,
)
def process_job_task(self, job_id: str, correlation_id: str) -> None:
    """Process one extraction job from queued state to terminal state."""
    with SyncSessionLocal() as db:
        job = db.get(Job, job_id)
        if not job:
            logger.error("Job %s not found correlation_id=%s", job_id, correlation_id)
            return

        if job.status == JobStatus.COMPLETE:
            logger.info("Skipping already completed job %s correlation_id=%s", job_id, correlation_id)
            return

        if _is_ai_outage_open():
            job.status = JobStatus.QUEUED_AI_OUTAGE
            job.progress_message = None
            job.error_log = "AI provider outage circuit breaker is open; job re-queued"
            db.commit()
            logger.warning("Circuit open. Job %s queued correlation_id=%s", job_id, correlation_id)
            return

        try:
            # Main processing path: fetch file, extract text, run LLM, persist result.
            job.status = JobStatus.PROCESSING
            job.progress_message = "Starting extraction..."
            job.error_log = None
            db.commit()

            file_bytes = download_from_s3(job.file_s3_key)
            document_text = extract_text(file_bytes, job.file_mime_type)

            last_progress_message = ""

            def update_progress(current: int, total: int, phase: str) -> None:
                nonlocal last_progress_message
                pct = int((current / total) * 100) if total > 0 else 0
                status_message = f"{phase}: {pct}% ({current}/{total})"

                # Avoid repeated commits for duplicate status text.
                if status_message == last_progress_message:
                    return

                try:
                    last_progress_message = status_message
                    job.progress_message = status_message
                    db.commit()

                    self.update_state(
                        state="PROCESSING",
                        meta={"current": current, "total": total, "phase": phase, "pct": pct},
                    )
                    logger.info("Job %s progress correlation_id=%s: %s", job_id, correlation_id, status_message)
                except (SQLAlchemyError, RuntimeError, ValueError, TypeError) as progress_exc:
                    logger.warning(
                        "Job %s progress update failed correlation_id=%s: %s",
                        job_id,
                        correlation_id,
                        progress_exc,
                    )

            result = asyncio.run(
                run_extraction(
                    job.extraction_schema,
                    document_text,
                    progress_callback=update_progress,
                )
            )

            job.status = JobStatus.COMPLETE
            job.result = result
            job.progress_message = None
            job.error_log = None
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

            _register_ai_success()

            if job.webhook_url:
                try:
                    deliver_webhook(job.webhook_url, job_id, result)
                except (ValueError, httpx.HTTPError) as webhook_exc:
                    job.error_log = f"Webhook delivery failed: {webhook_exc}"
                    db.commit()
                    logger.exception(
                        "Webhook delivery failed for job %s correlation_id=%s",
                        job_id,
                        correlation_id,
                    )

            logger.info("Job completed %s correlation_id=%s", job_id, correlation_id)

        except BadRequestError as exc:
            # Context-limit and similar malformed API requests are treated as permanent.
            job.status = JobStatus.DEAD
            job.progress_message = None
            job.error_log = f"Permanent failure (context limit exceeded): {exc}"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            logger.error(
                "Job %s failed permanently (BadRequestError) correlation_id=%s: %s",
                job_id, correlation_id, exc,
            )

        except json.JSONDecodeError as exc:
            # Truncated/invalid model JSON can be transient; retry before declaring DEAD.
            job.retry_count += 1
            job.status = JobStatus.PROCESSING
            job.progress_message = f"AI output truncated. Retrying ({job.retry_count}/{self.max_retries})..."
            job.error_log = None
            db.commit()
            logger.error(
                "Job %s JSON decode failure correlation_id=%s (retry %s/%s): %s",
                job_id,
                correlation_id,
                self.request.retries + 1,
                self.max_retries,
                exc,
            )

            if self.request.retries >= self.max_retries:
                job.status = JobStatus.DEAD
                job.progress_message = None
                job.error_log = f"Permanent failure (invalid/truncated AI JSON): {exc}"
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
                return

            raise self.retry(exc=exc, countdown=30)

        except Exception as exc:
            # Unknown/transient failures can be retried with backoff.
            job.retry_count += 1
            job.progress_message = None
            # Show the user only the first 100 chars of the error to avoid leaking sensitive info,
            # but log full traceback internally.
            job.error_log = f"Unexpected error: {str(exc)[:100]}. Retrying..."
            db.commit()

            if _is_ai_upstream_failure(exc):
                failures = _register_ai_failure()
                if failures >= AI_BREAKER_FAILURE_THRESHOLD:
                    open_until_ts = _trip_ai_circuit()
                    job.status = JobStatus.QUEUED_AI_OUTAGE
                    job.progress_message = None
                    job.error_log = (
                        "AI provider outage detected. Circuit breaker tripped until "
                        f"{datetime.fromtimestamp(open_until_ts, tz=timezone.utc).isoformat()}"
                    )
                    db.commit()
                    logger.error(
                        "Circuit breaker tripped after %s AI failures. job=%s correlation_id=%s",
                        failures,
                        job_id,
                        correlation_id,
                    )
                    return

            if self.request.retries >= self.max_retries:
                job.status = JobStatus.DEAD
                job.progress_message = None
                job.error_log = f"Maximum retries reached. Last error: {str(exc)[:100]}"
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
                logger.exception("Job %s moved to DEAD correlation_id=%s", job_id, correlation_id)
                return

            job.status = JobStatus.FAILED
            job.error_log = str(exc)
            db.commit()
            raise self.retry(exc=exc)
