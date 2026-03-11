"""Celery application bootstrap and periodic task schedule configuration."""

from celery import Celery
from celery.schedules import crontab
from rich.traceback import install

from api.src.config_package.settings import get_settings

cfg = get_settings()

install(show_locals=True)

celery_app = Celery(
    "docflow",
    broker=cfg.redis_url,
    backend=cfg.redis_url,
    include=[
        "api.src.tasks.process_job",
        "api.src.tasks.sweep_pending_jobs",
        "api.src.tasks.sweep_expired_tokens",
    ],
)

celery_app.conf.update(
    task_default_queue=cfg.celery_task_default_queue,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "sweep-stuck-pending-jobs": {
            "task": "api.src.tasks.sweep_pending_jobs.sweep_stuck_jobs_task",
            "schedule": crontab(minute="*/5"),
        },
        "sweep-expired-refresh-tokens": {
            "task": "api.src.tasks.sweep_expired_tokens.sweep_expired_tokens_task",
            "schedule": crontab(hour="3", minute="0"),
        },
    },
)
