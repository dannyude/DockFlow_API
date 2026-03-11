"""Periodic task that removes expired refresh tokens from persistence."""

from datetime import datetime, timezone
from typing import cast

from celery import shared_task
from celery.utils.log import get_task_logger
from sqlalchemy.engine import CursorResult
from sqlalchemy import delete

from api.src.auth.models import RefreshToken
from api.src.database.postgres_client import SyncSessionLocal

logger = get_task_logger(__name__)


@shared_task(bind=True)
def sweep_expired_tokens_task(_self) -> None:
    """Delete refresh tokens that have expired or been revoked/used."""
    now = datetime.now(timezone.utc)

    with SyncSessionLocal() as db:
        result = cast(
            CursorResult,
            db.execute(
            delete(RefreshToken).where(
                RefreshToken.expires_at < now,
            )
            ),
        )
        db.commit()
        logger.info("Pruned %d expired refresh tokens", result.rowcount)
