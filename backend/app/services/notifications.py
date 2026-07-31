"""Creating notifications.

Notifications are written in the same transaction as the event that caused
them, so a user is never told about a change that was subsequently rolled back.
Delivery beyond the in-app inbox (e-mail, push) is a later concern; this module
is the single place that would gain it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import Notification
from app.models.enums import NotificationType, ResourceType


def notify(
    session: Session,
    *,
    user_id: uuid.UUID,
    type: NotificationType,
    title: str,
    body: str | None = None,
    link: str | None = None,
    resource_type: ResourceType | None = None,
    resource_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> Notification | None:
    """Add one notification, unless the user is notifying themselves.

    Self-notifications are noise: a researcher approving their own record does
    not need an inbox entry announcing it.
    """
    if actor_id is not None and actor_id == user_id:
        return None

    notification = Notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        link=link,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_id=actor_id,
    )
    session.add(notification)
    return notification


def notify_project_editors(
    session: Session,
    *,
    project_id: uuid.UUID,
    type: NotificationType,
    title: str,
    body: str | None = None,
    link: str | None = None,
    resource_type: ResourceType | None = None,
    resource_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> int:
    """Notify everyone on a project who could act on the event.

    Used when a student submits work for approval: the people who can approve
    it are the project's directors and researchers, and they should not have to
    poll for pending submissions.
    """
    from app.models.enums import ProjectRole
    from app.models.project import ProjectMembership

    recipients = session.scalars(
        select(ProjectMembership.user_id).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.role.in_([ProjectRole.DIRECTOR, ProjectRole.RESEARCHER]),
        )
    ).all()

    sent = 0
    for user_id in recipients:
        created = notify(
            session,
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            link=link,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_id=actor_id,
        )
        if created is not None:
            sent += 1
    return sent
