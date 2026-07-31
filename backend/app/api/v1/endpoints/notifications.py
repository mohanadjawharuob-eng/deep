"""The user's notification inbox."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select, update

from app.api.deps import CurrentUser, DbSession
from app.models.audit import Notification
from app.models.enums import NotificationType, ResourceType
from app.schemas.common import Message, ORMModel, Page

router = APIRouter(prefix="/notifications", tags=["Notifications"])


class NotificationRead(ORMModel):
    id: uuid.UUID
    type: NotificationType
    title: str
    body: str | None = None
    link: str | None = None
    resource_type: ResourceType | None = None
    resource_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime


class UnreadCount(BaseModel):
    unread: int


@router.get(
    "",
    response_model=Page[NotificationRead],
    summary="List notifications",
    description="Your own inbox, newest first. Nobody can read another user's notifications.",
)
def list_notifications(
    session: DbSession,
    user: CurrentUser,
    unread_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[NotificationRead]:
    statement = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        statement = statement.where(Notification.is_read.is_(False))
    statement = statement.order_by(Notification.created_at.desc(), Notification.id.desc())

    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = session.scalars(statement.limit(limit).offset(offset)).all()
    return Page[NotificationRead](
        items=[NotificationRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/unread-count",
    response_model=UnreadCount,
    summary="Count unread notifications",
    description="Backs the badge in the header; cheap enough to poll.",
)
def unread_count(session: DbSession, user: CurrentUser) -> UnreadCount:
    count = (
        session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        )
        or 0
    )
    return UnreadCount(unread=count)


@router.post(
    "/{notification_id}/read",
    response_model=NotificationRead,
    summary="Mark one notification as read",
)
def mark_read(
    notification_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> NotificationRead:
    notification = session.get(Notification, notification_id)
    # 404 rather than 403 for someone else's notification: the id should not
    # confirm anything about another user's inbox.
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Notification not found")

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(UTC)
        session.add(notification)
    return NotificationRead.model_validate(notification)


@router.post(
    "/read-all",
    response_model=Message,
    summary="Mark every notification as read",
)
def mark_all_read(session: DbSession, user: CurrentUser) -> Message:
    result = session.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True, read_at=datetime.now(UTC))
    )
    return Message(detail=f"Marked {result.rowcount} notification(s) as read")


@router.delete(
    "/{notification_id}",
    response_model=Message,
    summary="Delete a notification",
)
def delete_notification(
    notification_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> Message:
    notification = session.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Notification not found")
    session.delete(notification)
    return Message(detail="Notification deleted")
