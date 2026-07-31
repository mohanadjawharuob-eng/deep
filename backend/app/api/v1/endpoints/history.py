"""Version history and the activity feed.

Like the review routes, these are generic over record type: the history of a
site and the history of an artifact differ only in which table the record came
from.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, CurrentUserOptional, DbSession
from app.core.permissions import (
    can_edit,
    can_view,
    resolve_project_id,
    visibility_filter,
)
from app.models.artifact import Artifact
from app.models.audit import ActivityLog
from app.models.context import ExcavationContext
from app.models.enums import ActivityAction, ResourceType, UserRole
from app.models.project import Project, ProjectMembership
from app.models.site import Site
from app.schemas.audit import (
    ActivityRead,
    RestoreResponse,
    RevisionRead,
    RevisionSummary,
)
from app.schemas.common import Page
from app.services import activity, records, revisions

router = APIRouter(tags=["History"])

#: Record types that carry version history, addressed by path segment.
VERSIONED: dict[str, tuple[type[Any], ResourceType, str]] = {
    "projects": (Project, ResourceType.PROJECT, "Project"),
    "sites": (Site, ResourceType.SITE, "Site"),
    "artifacts": (Artifact, ResourceType.ARTIFACT, "Artifact"),
    "contexts": (ExcavationContext, ResourceType.CONTEXT, "Context"),
}


def _resolve(kind: str) -> tuple[type[Any], ResourceType, str]:
    entry = VERSIONED.get(kind)
    if entry is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"Unknown record type {kind!r}; expected one of {', '.join(VERSIONED)}",
        )
    return entry


def _readable_record(
    session: DbSession, kind: str, record_id: uuid.UUID, user: Any
) -> tuple[Any, ResourceType, str]:
    model, resource_type, name = _resolve(kind)
    record = records.get_or_404(session, model, record_id, name)
    if not can_view(session, user, record, resource_type):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{name} not found")
    return record, resource_type, name


@router.get(
    "/{kind}/{record_id}/revisions",
    response_model=Page[RevisionSummary],
    summary="List a record's versions",
    description=(
        "Newest first. Version 1 is the record as created, so the history "
        "always reaches back to the original state rather than to the first "
        "edit. Payloads are omitted here; fetch one version to see it."
    ),
)
def list_revisions(
    kind: str,
    record_id: uuid.UUID,
    session: DbSession,
    user: CurrentUserOptional,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RevisionSummary]:
    _, resource_type, _ = _readable_record(session, kind, record_id, user)
    rows, total = revisions.history(session, resource_type, record_id, limit=limit, offset=offset)
    return Page[RevisionSummary](
        items=[RevisionSummary.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{kind}/{record_id}/revisions/{version}",
    response_model=RevisionRead,
    summary="Read one version",
    description="Includes the full snapshot of the record as it was.",
    responses={404: {"description": "No such version"}},
)
def read_revision(
    kind: str,
    record_id: uuid.UUID,
    version: int,
    session: DbSession,
    user: CurrentUserOptional,
) -> RevisionRead:
    _, resource_type, _ = _readable_record(session, kind, record_id, user)
    revision = revisions.get_revision(session, resource_type, record_id, version)
    if revision is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Version {version} not found")
    return RevisionRead.model_validate(revision)


@router.post(
    "/{kind}/{record_id}/revisions/{version}/restore",
    response_model=RestoreResponse,
    summary="Restore an earlier version",
    description=(
        "Applies the stored version to the record. The state being replaced is "
        "kept as a new version first, so a restore is itself reversible and no "
        "data is ever lost."
    ),
    responses={403: {"description": "You may not edit this record"}},
)
def restore_revision(
    kind: str,
    record_id: uuid.UUID,
    version: int,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> RestoreResponse:
    record, resource_type, name = _readable_record(session, kind, record_id, user)
    if not can_edit(session, user, record, resource_type):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail=f"You may not edit this {name.lower()}"
        )

    try:
        created, changed = revisions.restore(session, record, resource_type, version, user=user)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # Coordinates may have moved, so the geometry has to follow them back.
    records.sync_point_geometry(record)

    activity.log(
        session,
        action=ActivityAction.RESTORE,
        user=user,
        resource_type=resource_type,
        resource_id=record.id,
        resource_label=records.label_for(record),
        project_id=resolve_project_id(session, record),
        summary=f"Restored version {version}",
        request=request,
    )
    session.flush()

    return RestoreResponse(
        detail=(
            f"Restored version {version}"
            if changed
            else f"Version {version} matches the current state; nothing changed"
        ),
        restored_version=version,
        new_version=created.version,
        changed_fields=changed,
    )


# --------------------------------------------------------------------------
# Activity feed
# --------------------------------------------------------------------------
@router.get(
    "/activity",
    response_model=Page[ActivityRead],
    summary="Activity feed",
    description=(
        "Who did what, newest first. Administrators see everything; everyone "
        "else sees activity in projects they belong to, plus their own actions."
    ),
)
def activity_feed(
    session: DbSession,
    user: CurrentUser,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    resource_type: Annotated[ResourceType | None, Query()] = None,
    resource_id: Annotated[uuid.UUID | None, Query()] = None,
    action: Annotated[ActivityAction | None, Query()] = None,
    user_id: Annotated[uuid.UUID | None, Query(description="Only this user's actions")] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ActivityRead]:
    from sqlalchemy import or_

    statement = select(ActivityLog)

    if user.role is not UserRole.ADMIN:
        # Two things are legitimately visible: activity inside a project the
        # user is on, and their own actions wherever they happened. Entries
        # with no project (sign-ins, account changes) are private to the actor.
        statement = statement.where(
            or_(
                ActivityLog.user_id == user.id,
                ActivityLog.project_id.in_(
                    select(ProjectMembership.project_id).where(ProjectMembership.user_id == user.id)
                ),
            )
        )

    if project_id is not None:
        statement = statement.where(ActivityLog.project_id == project_id)
    if resource_type is not None:
        statement = statement.where(ActivityLog.resource_type == resource_type)
    if resource_id is not None:
        statement = statement.where(ActivityLog.resource_id == resource_id)
    if action is not None:
        statement = statement.where(ActivityLog.action == action)
    if user_id is not None:
        statement = statement.where(ActivityLog.user_id == user_id)
    if since is not None:
        statement = statement.where(ActivityLog.created_at >= since)
    if until is not None:
        statement = statement.where(ActivityLog.created_at <= until)

    # ``id`` breaks ties: without it, rows sharing a timestamp have no defined
    # order and pagination over them can drop or repeat entries.
    statement = statement.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())

    rows, total = records.paginate(session, statement, limit, offset)
    return Page[ActivityRead](
        items=[ActivityRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{kind}/{record_id}/activity",
    response_model=Page[ActivityRead],
    summary="One record's activity",
)
def record_activity(
    kind: str,
    record_id: uuid.UUID,
    session: DbSession,
    user: CurrentUserOptional,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ActivityRead]:
    _, resource_type, _ = _readable_record(session, kind, record_id, user)

    statement = (
        select(ActivityLog)
        .where(
            ActivityLog.resource_type == resource_type,
            ActivityLog.resource_id == record_id,
        )
        .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
    )
    rows, total = records.paginate(session, statement, limit, offset)
    return Page[ActivityRead](
        items=[ActivityRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


__all__ = ["router", "visibility_filter"]
