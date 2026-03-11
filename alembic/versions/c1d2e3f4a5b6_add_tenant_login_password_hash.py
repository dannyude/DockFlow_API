"""add tenant login password hash

Revision ID: c1d2e3f4a5b6
Revises: 9b2f5d5d7a11
Create Date: 2026-03-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "9b2f5d5d7a11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_PASSWORD_HASH = "ccc0b903bce51fb554262d742d0a282e1f8a87d064f1cf44f8ff5148ca4beb42"


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("login_password_hash", sa.String(length=64), nullable=False, server_default=DEFAULT_PASSWORD_HASH),
    )
    op.alter_column("tenants", "login_password_hash", server_default=None)


def downgrade() -> None:
    op.drop_column("tenants", "login_password_hash")
