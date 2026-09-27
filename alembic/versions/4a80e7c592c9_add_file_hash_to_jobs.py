"""add file_hash to jobs

Revision ID: 4a80e7c592c9
Revises: 0a1b2c3d4e5f
Create Date: 2026-03-03 15:41:21.900318

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4a80e7c592c9'
down_revision: Union[str, Sequence[str], None] = '0a1b2c3d4e5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add the column, but allow it to be empty for old test data!
    op.add_column('jobs', sa.Column('file_hash', sa.String(length=64), nullable=True))

    # 2. Add the missing speed-boost index!
    op.create_index(op.f('ix_jobs_file_hash'), 'jobs', ['file_hash'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Make sure to drop the index BEFORE dropping the column
    op.drop_index(op.f('ix_jobs_file_hash'), table_name='jobs')
    op.drop_column('jobs', 'file_hash')
