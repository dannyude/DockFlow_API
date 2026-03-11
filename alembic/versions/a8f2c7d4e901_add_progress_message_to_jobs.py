"""add progress_message to jobs

Revision ID: a8f2c7d4e901
Revises: 7ec76ae3bec7
Create Date: 2026-03-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a8f2c7d4e901"
down_revision: Union[str, Sequence[str], None] = "7ec76ae3bec7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("progress_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "progress_message")
