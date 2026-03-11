"""add reliability fields and queue outage status

Revision ID: 9b2f5d5d7a11
Revises: 4a80e7c592c9
Create Date: 2026-03-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9b2f5d5d7a11"
down_revision: Union[str, Sequence[str], None] = "4a80e7c592c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE jobstatus ADD VALUE IF NOT EXISTS 'QUEUED_AI_OUTAGE'")

    op.add_column("jobs", sa.Column("enqueue_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("correlation_id", sa.String(length=36), nullable=True))
    op.add_column("jobs", sa.Column("last_enqueued_at", sa.DateTime(timezone=True), nullable=True))

    op.execute("UPDATE jobs SET correlation_id = id::text WHERE correlation_id IS NULL")

    op.alter_column("jobs", "correlation_id", nullable=False)
    op.create_index("ix_jobs_correlation_id", "jobs", ["correlation_id"], unique=False)

    op.alter_column("jobs", "enqueue_attempts", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_jobs_correlation_id", table_name="jobs")
    op.drop_column("jobs", "last_enqueued_at")
    op.drop_column("jobs", "correlation_id")
    op.drop_column("jobs", "enqueue_attempts")
