"""Persistence models for authentication artifacts."""

from datetime import datetime, timezone
import uuid

from sqlalchemy import (
    CheckConstraint,
    Index,
    String,
    DateTime,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID as pgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.src.database.postgres_client import Base


class RefreshToken(Base):
    """Stored refresh token metadata used for secure session management."""
    __tablename__ = "refresh_tokens"

    __table_args__ = (
        Index("ix_refresh_tokens_user_active", "user_id", "revoked_token", "used_token"),
        CheckConstraint(
            "(used_token = false) OR (used_at IS NOT NULL)",
            name="ck_used_token_needs_used_at",
        ),
        CheckConstraint(
            "(revoked_token = false) OR (revoked_at IS NOT NULL)",
            name="ck_revoked_token_needs_revoked_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pgUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        pgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    jti: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    session_version: Mapped[int] = mapped_column(nullable=False)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    used_token: Mapped[bool] = mapped_column(default=False, nullable=False)
    revoked_token: Mapped[bool] = mapped_column(default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))

    user = relationship(
        "User",
        back_populates="refresh_tokens",
    )

    def __repr__(self) -> str:
        return f"<RefreshToken {self.id} user={self.user_id}>"
