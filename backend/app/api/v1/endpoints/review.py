"""The approval workflow for student submissions.

One set of routes covers every record type, because the workflow is identical
whatever is being reviewed and duplicating it per module is how the rules would
drift apart.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.permissions import can_approve, can_edit, can_view, visibility_filter
from app.models.artifact import Artifact
from app.models.context import ExcavationContext
from app.models.enums import (
    ActivityAction,
    NotificationType,
    ResourceType,
    ReviewStatus,
)
from app.models.media import Document, Photograph
from app.models.site import Site
from app.schemas.common import Message
from app.services import activity, notifications, records

router = APIRouter(tags=["Review workflow"])

#: The record types that carry a review status, keyed by the path segment used
#: to address them. Adding a reviewable module means adding one line here.
REVIEWABLE: dict[str, tuple[type[Any], ResourceType, str]] = {
    "sites": (Site, ResourceType.SITE, "Site"),
    "artifacts": (Artifact, ResourceType.ARTIFACT, "Artifact"),
    "contexts": (ExcavationContext, ResourceType.CONTEXT, "Context"),
    # A student's photographs and documents queue for approval exactly as their
    # finds do. 3D models are absent because they carry no review status: a
    # model is a link or a mesh attached to a record that was itself reviewed.
    "photographs": (Photograph, ResourceType.PHOTOGRAPH, "Photograph"),
    "documents": (Document, ResourceType.DOCUMENT, "Document"),
}


class PendingItem(BaseModel):
    id: uuid.UUID
    resource_type: ResourceType
    label: str
    owner_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    review_status: ReviewStatus


class ReviewDecision(BaseModel):
    note: str | None = Field(
        default=None,
        max_length=1000,
        description="Shown to the author; required when rejecting",
    )


def _resolve(kind: str) -> tuple[type[Any], ResourceType, str]:
    entry = REVIEWABLE.get(kind)
    if entry is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"Unknown record type {kind!r}; expected one of {', '.join(REVIEWABLE)}",
        )
    return entry


@router.get(
    "/pending",
    response_model=list[PendingItem],
    summary="List submissions awaiting approval",
    description=(
        "Everything the caller could approve, across all record types. This is "
        "what the dashboard's *pending approvals* panel reads."
    ),
)
def list_pending(
    session: DbSession,
    user: CurrentUser,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[PendingItem]:
    pending: list[PendingItem] = []

    for model, resource_type, _ in REVIEWABLE.values():
        statement = (
            select(model)
            .where(
                model.review_status == ReviewStatus.PENDING,
                # The visibility filter already hides pending records from
                # users who could not act on them, so it does the scoping here.
                visibility_filter(user, model, resource_type),
            )
            .order_by(model.created_at.asc())
            .limit(limit)
        )
        for row in session.scalars(statement).all():
            if project_id is not None and _project_of(session, row) != project_id:
                continue
            if not can_approve(session, user, row, resource_type):
                continue
            pending.append(
                PendingItem(
                    id=row.id,
                    resource_type=resource_type,
                    label=records.label_for(row) or str(row.id),
                    owner_id=row.owner_id,
                    project_id=_project_of(session, row),
                    review_status=row.review_status,
                )
            )

    return pending[:limit]


def _project_of(session: DbSession, record: Any) -> uuid.UUID | None:
    from app.core.permissions import resolve_project_id

    return resolve_project_id(session, record)


@router.post(
    "/{kind}/{record_id}/submit",
    response_model=Message,
    summary="Submit a record for approval",
    description=(
        "Moves a draft or rejected record into the approval queue and notifies "
        "the project's researchers. Records created by students start here "
        "automatically; this route is for resubmitting after changes."
    ),
)
def submit(
    kind: str,
    record_id: uuid.UUID,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> Message:
    model, resource_type, name = _resolve(kind)
    record = records.get_or_404(session, model, record_id, name)

    if not can_view(session, user, record, resource_type):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{name} not found")
    if record.owner_id != user.id and not can_edit(session, user, record, resource_type):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Only the author may submit this record"
        )
    if record.review_status is ReviewStatus.PENDING:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="This record is already awaiting review"
        )

    record.review_status = ReviewStatus.PENDING
    session.add(record)

    project_id = _project_of(session, record)
    label = records.label_for(record) or str(record.id)

    if project_id is not None:
        notifications.notify_project_editors(
            session,
            project_id=project_id,
            type=NotificationType.RECORD_SUBMITTED,
            title=f"{name} {label} submitted for review",
            body=f"{user.full_name} submitted a record for approval.",
            link=f"/{kind}/{record.id}",
            resource_type=resource_type,
            resource_id=record.id,
            actor_id=user.id,
        )

    activity.log(
        session,
        action=ActivityAction.SUBMIT,
        user=user,
        resource_type=resource_type,
        resource_id=record.id,
        resource_label=label,
        project_id=project_id,
        request=request,
    )
    return Message(detail="Submitted for review")


@router.post(
    "/{kind}/{record_id}/approve",
    response_model=Message,
    summary="Approve a submission",
    description=(
        "Requires the researcher role *and* edit rights on the record, so a "
        "researcher cannot approve work in a project they are not part of."
    ),
)
def approve(
    kind: str,
    record_id: uuid.UUID,
    payload: ReviewDecision,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> Message:
    return _decide(
        kind,
        record_id,
        payload,
        session,
        request,
        user,
        outcome=ReviewStatus.APPROVED,
    )


@router.post(
    "/{kind}/{record_id}/reject",
    response_model=Message,
    summary="Reject a submission",
    description="A note explaining what needs changing is required.",
    responses={422: {"description": "A note is required when rejecting"}},
)
def reject(
    kind: str,
    record_id: uuid.UUID,
    payload: ReviewDecision,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> Message:
    if not payload.note or not payload.note.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Please say why the record is being rejected, so it can be corrected",
        )
    return _decide(
        kind,
        record_id,
        payload,
        session,
        request,
        user,
        outcome=ReviewStatus.REJECTED,
    )


def _decide(
    kind: str,
    record_id: uuid.UUID,
    payload: ReviewDecision,
    session: DbSession,
    request: Request,
    user: CurrentUser,
    *,
    outcome: ReviewStatus,
) -> Message:
    model, resource_type, name = _resolve(kind)
    record = records.get_or_404(session, model, record_id, name)

    if not can_view(session, user, record, resource_type):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{name} not found")
    if not can_approve(session, user, record, resource_type):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="You may not review records in this project"
        )
    if record.review_status is not ReviewStatus.PENDING:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"This record is {record.review_status.value}, not awaiting review",
        )

    record.review_status = outcome
    session.add(record)

    label = records.label_for(record) or str(record.id)
    approved = outcome is ReviewStatus.APPROVED

    if record.owner_id is not None:
        notifications.notify(
            session,
            user_id=record.owner_id,
            type=(
                NotificationType.RECORD_APPROVED if approved else NotificationType.RECORD_REJECTED
            ),
            title=f"{name} {label} was {outcome.value}",
            body=payload.note,
            link=f"/{kind}/{record.id}",
            resource_type=resource_type,
            resource_id=record.id,
            actor_id=user.id,
        )

    activity.log(
        session,
        action=ActivityAction.APPROVE if approved else ActivityAction.REJECT,
        user=user,
        resource_type=resource_type,
        resource_id=record.id,
        resource_label=label,
        project_id=_project_of(session, record),
        summary=payload.note,
        request=request,
    )
    return Message(detail=f"{name} {outcome.value}")
