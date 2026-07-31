"""Shared behaviour for every content record.

Projects, sites, artifacts and contexts differ in their fields but not in what
must happen around a write: coordinates kept in step with the PostGIS geometry,
a review status that depends on who is writing, a snapshot before every change,
and an audit entry after it.

Endpoints call these helpers instead of repeating that sequence, which is what
stops one module from quietly forgetting the audit trail.
"""

from __future__ import annotations

import uuid
from typing import Any, TypeVar

from fastapi import Request
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.permissions import requires_approval, resolve_project_id
from app.models.enums import ActivityAction, ResourceType, ReviewStatus
from app.models.user import User
from app.services import activity, revisions

T = TypeVar("T")


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------
def sync_point_geometry(record: Any) -> None:
    """Keep ``geom`` in step with the ``latitude``/``longitude`` columns.

    The decimal columns are the editable truth — they are what forms post and
    what CSV exports carry — and ``geom`` is derived from them so PostGIS can
    answer spatial queries. Writing both by hand in every endpoint is how they
    drift, so this is the only place either is set.
    """
    if not hasattr(record, "geom"):
        return

    latitude = getattr(record, "latitude", None)
    longitude = getattr(record, "longitude", None)

    if latitude is None or longitude is None:
        record.geom = None
        return

    record.geom = f"SRID=4326;POINT({float(longitude)} {float(latitude)})"


def validate_coordinates(latitude: float | None, longitude: float | None) -> None:
    """Reject impossible coordinates before they reach PostGIS.

    Raises :class:`ValueError` with a message safe to show the user.
    """
    if latitude is not None and not (-90 <= float(latitude) <= 90):
        raise ValueError("Latitude must be between -90 and 90 degrees")
    if longitude is not None and not (-180 <= float(longitude) <= 180):
        raise ValueError("Longitude must be between -180 and 180 degrees")
    if (latitude is None) != (longitude is None):
        raise ValueError("Latitude and longitude must be given together")


# --------------------------------------------------------------------------
# Review workflow
# --------------------------------------------------------------------------
def initial_review_status(user: User | None) -> ReviewStatus:
    """What a newly created record's review status should be.

    Students submit for approval; researchers and administrators do not.
    """
    return ReviewStatus.PENDING if requires_approval(user) else ReviewStatus.APPROVED


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------
def apply_changes(record: Any, changes: dict[str, Any]) -> dict[str, Any]:
    """Assign ``changes`` onto ``record``, returning the previous values.

    Only fields whose value actually differs are reported, so an update that
    re-posts an unchanged form does not manufacture an empty revision.
    """
    before: dict[str, Any] = {}
    for key, value in changes.items():
        current = getattr(record, key, None)
        if current != value:
            before[key] = current
            setattr(record, key, value)
    return before


def on_created(
    session: Session,
    record: Any,
    resource_type: ResourceType,
    *,
    user: User | None,
    request: Request | None = None,
    label: str | None = None,
) -> None:
    """Log the creation and store version 1.

    Version 1 is the record as created, which means the history of a record
    always starts at its original state rather than at its first edit.
    """
    revisions.snapshot(
        session, record, resource_type, user=user, summary="Created", changed_fields=None
    )
    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_type=resource_type,
        resource_id=record.id,
        resource_label=label or label_for(record),
        project_id=resolve_project_id(session, record),
        request=request,
    )


def on_updated(
    session: Session,
    record: Any,
    resource_type: ResourceType,
    *,
    before: dict[str, Any],
    user: User | None,
    request: Request | None = None,
    label: str | None = None,
) -> None:
    """Snapshot the pre-change state and log what changed.

    ``before`` is the mapping returned by :func:`apply_changes`. An empty one
    means nothing actually changed, and no version or log entry is written.
    """
    if not before:
        return

    changed_fields = sorted(before)
    after = {key: getattr(record, key) for key in before}

    # The snapshot must describe the *old* state, so rebuild it from the
    # pre-change values rather than reading the record we have already mutated.
    stored = revisions.serialise(record)
    for key, old_value in before.items():
        stored[key] = revisions.to_jsonable(old_value)

    session.add(_revision_row(session, record, resource_type, stored, changed_fields, user))

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=resource_type,
        resource_id=record.id,
        resource_label=label or label_for(record),
        changes=activity.diff(before, after),
        project_id=resolve_project_id(session, record),
        request=request,
    )


def _revision_row(
    session: Session,
    record: Any,
    resource_type: ResourceType,
    data: dict[str, Any],
    changed_fields: list[str],
    user: User | None,
):
    from app.models.audit import Revision

    return Revision(
        resource_type=resource_type,
        resource_id=record.id,
        version=revisions.next_version(session, resource_type, record.id),
        data=data,
        changed_fields=changed_fields,
        change_summary=f"Updated {', '.join(changed_fields[:5])}"
        + ("…" if len(changed_fields) > 5 else ""),
        changed_by_id=user.id if user else None,
    )


def on_deleted(
    session: Session,
    record: Any,
    resource_type: ResourceType,
    *,
    user: User | None,
    request: Request | None = None,
    label: str | None = None,
) -> None:
    """Snapshot the record before it goes, then log the deletion.

    The final version outlives the row: ``revisions`` has no foreign key to the
    record, deliberately, so a deleted excavation record can still be inspected
    and — with the id — reconstructed.
    """
    project_id = resolve_project_id(session, record)
    revisions.snapshot(
        session, record, resource_type, user=user, summary="Deleted", changed_fields=None
    )
    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=user,
        resource_type=resource_type,
        resource_id=record.id,
        resource_label=label or label_for(record),
        project_id=project_id,
        request=request,
    )


def label_for(record: Any) -> str | None:
    """Best human-readable identifier for the audit trail."""
    for attribute in ("name", "title", "inventory_number", "context_number", "code"):
        value = getattr(record, attribute, None)
        if value:
            return str(value)
    return None


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------
def paginate(session: Session, statement: Select, limit: int, offset: int) -> tuple[list[Any], int]:
    """Run a query twice: once for the page, once for the total.

    The count uses the same filters, so ``total`` always describes the query
    the caller asked about rather than the table.
    """
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = list(session.scalars(statement.limit(limit).offset(offset)).all())
    return rows, total


def get_or_404(session: Session, model: type[T], record_id: uuid.UUID, name: str) -> T:
    """Fetch a record or raise the 404 the endpoints all use."""
    from fastapi import HTTPException, status

    record = session.get(model, record_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{name} not found")
    return record


def check_can_contribute(session: Session, user: User, project_id: uuid.UUID) -> Any:
    """Assert ``user`` may add records to ``project_id``; return the project.

    Three things have to hold, and they fail with different statuses:
    the project must be visible (404 if not, since its existence is itself
    information), the user's role must permit creating records at all, and they
    must actually be on the team — a student with the create capability still
    cannot file finds against someone else's excavation.
    """
    from fastapi import HTTPException, status

    from app.core.permissions import (
        Capability,
        can_edit,
        can_view,
        has_capability,
        project_level,
    )
    from app.models.project import Project

    project = get_or_404(session, Project, project_id, "Project")
    if not can_view(session, user, project, ResourceType.PROJECT):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")
    if not has_capability(user, Capability.CREATE_RECORD):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Your role does not permit creating records"
        )
    if project_level(session, user, project_id) is None and not can_edit(
        session, user, project, ResourceType.PROJECT
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="You are not a member of this project"
        )
    return project
