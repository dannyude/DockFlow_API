"""add composite indexes on jobs for listing and sweeper scans

Revision ID: b7c9e1f2a3d4
Revises: a8f2c7d4e901
Create Date: 2026-09-10 00:00:00.000000

Adds two composite indexes that back the hottest job queries:

* ``ix_jobs_tenant_created`` — tenant-scoped listing ordered by ``created_at``.
* ``ix_jobs_status_created`` — the stuck-job sweeper's ``status`` + age scan.

Both replace sequential scans that grow linearly with the ``jobs`` table.
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c9e1f2a3d4"
down_revision: Union[str, Sequence[str], None] = "a8f2c7d4e901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_jobs_tenant_created", "jobs", ["tenant_id", "created_at"], unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_jobs_status_created", "jobs", ["status", "created_at"], unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_status_created", table_name="jobs", if_exists=True)
    op.drop_index("ix_jobs_tenant_created", table_name="jobs", if_exists=True)
