"""Users, sessions and per-record access grants."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import PermissionLevel, ResourceType, UserRole

if TYPE_CHECKING:
    from app.models.project import ProjectMembership


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda e: [m.value for m in e]),
        default=UserRole.STUDENT,
        nullable=False,
        index=True,
    )

    # Scholarly identity
    institution: Mapped[str | None] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(200))
    position: Mapped[str | None] = mapped_column(String(120))
    orcid: Mapped[str | None] = mapped_column(String(19))  # 0000-0002-1825-0097
    country: Mapped[str | None] = mapped_column(String(2))  # ISO 3166-1 alpha-2
    bio: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(40))
    avatar_path: Mapped[str | None] = mapped_column(String(500))

    # Preferences (the frontend reads these on login)
    locale: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    theme: Mapped[str] = mapped_column(String(10), default="system", nullable=False)

    # Account state
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Consecutive failed logins; reset on success, used for lockout.
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Tokens issued before this instant are rejected (password change, forced
    #: logout). Cheaper than a token blacklist and covers every device at once.
    tokens_valid_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    memberships: Mapped[list[ProjectMembership]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="ProjectMembership.user_id",
    )

    __table_args__ = (Index("ix_users_full_name", "full_name"),)

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.username} ({self.role.value})>"


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A refresh token issued to one device.

    Only the SHA-256 digest is stored, so a database leak does not hand out
    live sessions. Rows are kept after revocation for audit purposes and
    pruned by the maintenance job.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: ``jti`` claim of the JWT, for correlating logs.
    jti: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Set when this token was rotated, pointing at its successor.
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )

    user_agent: Mapped[str | None] = mapped_column(String(400))
    ip_address: Mapped[str | None] = mapped_column(INET)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > datetime.now(UTC)


class RecordPermission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An explicit viewer/editor grant on a single record.

    Polymorphic by ``(resource_type, resource_id)`` rather than one join table
    per module: grants are sparse, and this keeps permission checks to a single
    indexed lookup regardless of which module the record belongs to.
    """

    __tablename__ = "record_permissions"

    resource_type: Mapped[ResourceType] = mapped_column(
        Enum(ResourceType, name="resource_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    level: Mapped[PermissionLevel] = mapped_column(
        Enum(
            PermissionLevel,
            name="permission_level",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    granted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint(
            "resource_type", "resource_id", "user_id", name="uq_record_permissions_grant"
        ),
        Index("ix_record_permissions_resource", "resource_type", "resource_id"),
        Index("ix_record_permissions_user_lookup", "user_id", "resource_type"),
    )
