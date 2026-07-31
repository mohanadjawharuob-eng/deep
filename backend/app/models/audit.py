"""Activity log, revision history, notifications and comments.

Together these implement the specification's promise that nothing is silently
overwritten: every write is logged, every version is retained, and every
restore is itself a new version.
"""

from __future__ import annotations

import uuid
from datetime import datetime

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
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ActivityAction, NotificationType, ResourceType
from app.models.user import User


class ActivityLog(UUIDPrimaryKeyMixin, Base):
    """Append-only audit trail.

    No ``updated_at``: rows are never modified. ``user_id`` is nullable and
    ``SET NULL`` so deleting an account cannot erase the trail, while
    ``user_label`` keeps a readable name for entries whose account is gone.
    """

    __tablename__ = "activity_logs"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, server_default=func.now()
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    user_label: Mapped[str | None] = mapped_column(String(200))

    action: Mapped[ActivityAction] = mapped_column(
        Enum(
            ActivityAction, name="activity_action", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
        index=True,
    )
    resource_type: Mapped[ResourceType | None] = mapped_column(
        Enum(ResourceType, name="resource_type", values_callable=lambda e: [m.value for m in e]),
        index=True,
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    #: Human-readable identifier of the target at the time of the action, so
    #: the log still reads sensibly after the record is renamed or deleted.
    resource_label: Mapped[str | None] = mapped_column(String(300))

    #: ``{"field": {"old": ..., "new": ...}}`` for updates.
    changes: Mapped[dict | None] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(Text)

    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(400))
    request_id: Mapped[str | None] = mapped_column(String(36), index=True)

    user: Mapped[User | None] = relationship()

    __table_args__ = (
        Index("ix_activity_logs_resource", "resource_type", "resource_id", "created_at"),
        Index("ix_activity_logs_user_time", "user_id", "created_at"),
    )


class Revision(UUIDPrimaryKeyMixin, Base):
    """A full snapshot of a record as it was before a change.

    Storing the whole row (rather than a diff) makes restore trivial and
    survives schema evolution: an old snapshot is still readable even after new
    columns appear.
    """

    __tablename__ = "revisions"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, server_default=func.now()
    )
    resource_type: Mapped[ResourceType] = mapped_column(
        Enum(ResourceType, name="resource_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    #: 1-based, monotonically increasing per record.
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    changed_fields: Mapped[list | None] = mapped_column(JSONB)
    change_summary: Mapped[str | None] = mapped_column(Text)
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    #: True when this version was produced by restoring an earlier one.
    is_restore: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    changed_by: Mapped[User | None] = relationship()

    __table_args__ = (
        UniqueConstraint("resource_type", "resource_id", "version", name="uq_revisions_version"),
        Index("ix_revisions_resource", "resource_type", "resource_id", "version"),
    )


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[NotificationType] = mapped_column(
        Enum(
            NotificationType,
            name="notification_type",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    #: Frontend route to open when the notification is clicked.
    link: Mapped[str | None] = mapped_column(String(500))

    resource_type: Mapped[ResourceType | None] = mapped_column(
        Enum(ResourceType, name="resource_type", values_callable=lambda e: [m.value for m in e])
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    actor: Mapped[User | None] = relationship(foreign_keys=[actor_id])

    __table_args__ = (Index("ix_notifications_inbox", "user_id", "is_read", "created_at"),)


class Comment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Threaded discussion attached to any record."""

    __tablename__ = "comments"

    resource_type: Mapped[ResourceType] = mapped_column(
        Enum(ResourceType, name="resource_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("comments.id", ondelete="CASCADE"), index=True
    )
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    author: Mapped[User | None] = relationship()

    __table_args__ = (Index("ix_comments_resource", "resource_type", "resource_id", "created_at"),)
