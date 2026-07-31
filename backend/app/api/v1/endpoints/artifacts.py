"""Artifact CRUD."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, CurrentUserOptional, DbSession
from app.core.permissions import can_delete, can_edit, can_view, visibility_filter
from app.models.artifact import Artifact
from app.models.context import ExcavationContext
from app.models.enums import (
    ConditionState,
    ConservationStatus,
    ResourceType,
    ReviewStatus,
)
from app.models.site import Site
from app.models.user import User
from app.schemas.artifact import (
    ArtifactCreate,
    ArtifactDetail,
    ArtifactSummary,
    ArtifactUpdate,
)
from app.schemas.common import Message, Page
from app.services import records

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])

RESOURCE = ResourceType.ARTIFACT


def _detail(session: DbSession, artifact: Artifact, user: User | None) -> ArtifactDetail:
    detail = ArtifactDetail.model_validate(artifact)
    detail.can_edit = can_edit(session, user, artifact, RESOURCE)
    detail.can_delete = can_delete(session, user, artifact, RESOURCE)
    return detail


def _check_context_belongs_to_site(
    session: DbSession, context_id: uuid.UUID | None, site_id: uuid.UUID
) -> None:
    """An artifact's context must be one of its own site's contexts.

    Without this a find could be attached to a context from a different
    excavation, which would silently corrupt every stratigraphic query.
    """
    if context_id is None:
        return
    owning_site = session.scalar(
        select(ExcavationContext.site_id).where(ExcavationContext.id == context_id)
    )
    if owning_site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Context not found")
    if owning_site != site_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That context belongs to a different site",
        )


@router.get(
    "",
    response_model=Page[ArtifactSummary],
    summary="List artifacts",
    description=(
        "Artifacts visible to the caller, filterable by site, project, "
        "context, material, category, period, condition and date range."
    ),
)
def list_artifacts(
    session: DbSession,
    user: CurrentUserOptional,
    q: Annotated[
        str | None, Query(description="Match inventory number, name, type or description")
    ] = None,
    site_id: Annotated[uuid.UUID | None, Query()] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    context_id: Annotated[uuid.UUID | None, Query()] = None,
    material_id: Annotated[uuid.UUID | None, Query()] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    period_id: Annotated[uuid.UUID | None, Query()] = None,
    object_type: Annotated[str | None, Query()] = None,
    condition: Annotated[ConditionState | None, Query()] = None,
    conservation_status: Annotated[ConservationStatus | None, Query()] = None,
    trench: Annotated[str | None, Query()] = None,
    current_location: Annotated[str | None, Query()] = None,
    date_from: Annotated[int | None, Query(description="Earliest year; negative is BCE")] = None,
    date_to: Annotated[int | None, Query(description="Latest year; negative is BCE")] = None,
    review_status: Annotated[ReviewStatus | None, Query()] = None,
    sort: Annotated[
        str, Query(pattern="^-?(inventory_number|name|created_at|date_from|object_type)$")
    ] = "inventory_number",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ArtifactSummary]:
    statement = select(Artifact).where(visibility_filter(user, Artifact, RESOURCE))

    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Artifact.inventory_number).like(pattern),
                func.lower(Artifact.field_number).like(pattern),
                func.lower(Artifact.name).like(pattern),
                func.lower(Artifact.object_type).like(pattern),
                func.lower(Artifact.description).like(pattern),
            )
        )
    if site_id is not None:
        statement = statement.where(Artifact.site_id == site_id)
    if project_id is not None:
        statement = statement.where(
            Artifact.site_id.in_(select(Site.id).where(Site.project_id == project_id))
        )
    if context_id is not None:
        statement = statement.where(Artifact.context_id == context_id)
    if material_id is not None:
        statement = statement.where(Artifact.material_id == material_id)
    if category_id is not None:
        statement = statement.where(Artifact.category_id == category_id)
    if period_id is not None:
        statement = statement.where(Artifact.period_id == period_id)
    if object_type:
        statement = statement.where(
            func.lower(Artifact.object_type).like(f"%{object_type.lower()}%")
        )
    if condition is not None:
        statement = statement.where(Artifact.condition == condition)
    if conservation_status is not None:
        statement = statement.where(Artifact.conservation_status == conservation_status)
    if trench:
        statement = statement.where(func.lower(Artifact.trench) == trench.lower())
    if current_location:
        statement = statement.where(
            func.lower(Artifact.current_location).like(f"%{current_location.lower()}%")
        )
    if review_status is not None:
        statement = statement.where(Artifact.review_status == review_status)

    # Overlapping ranges, as elsewhere: a find dated broadly still answers a
    # narrow query.
    if date_from is not None:
        statement = statement.where(or_(Artifact.date_to.is_(None), Artifact.date_to >= date_from))
    if date_to is not None:
        statement = statement.where(
            or_(Artifact.date_from.is_(None), Artifact.date_from <= date_to)
        )

    descending = sort.startswith("-")
    column = getattr(Artifact, sort.lstrip("-"))
    statement = statement.order_by(column.desc() if descending else column.asc())

    rows, total = records.paginate(session, statement, limit, offset)
    return Page[ArtifactSummary](
        items=[ArtifactSummary.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=ArtifactDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create an artifact",
    responses={409: {"description": "Inventory number already used at this site"}},
)
def create_artifact(
    payload: ArtifactCreate, session: DbSession, request: Request, user: CurrentUser
) -> ArtifactDetail:
    site = records.get_or_404(session, Site, payload.site_id, "Site")
    records.check_can_contribute(session, user, site.project_id)
    _check_context_belongs_to_site(session, payload.context_id, site.id)

    clash = session.scalar(
        select(Artifact.id).where(
            Artifact.site_id == payload.site_id,
            Artifact.inventory_number == payload.inventory_number,
        )
    )
    if clash is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Inventory number {payload.inventory_number!r} is already used at this site",
        )

    artifact = Artifact(
        **payload.model_dump(),
        owner_id=user.id,
        review_status=records.initial_review_status(user),
    )
    records.sync_point_geometry(artifact)
    session.add(artifact)
    session.flush()

    records.on_created(session, artifact, RESOURCE, user=user, request=request)
    session.flush()
    return _detail(session, artifact, user)


@router.get(
    "/{artifact_id}",
    response_model=ArtifactDetail,
    summary="Read an artifact",
    responses={404: {"description": "No such artifact, or not visible to you"}},
)
def read_artifact(
    artifact_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> ArtifactDetail:
    artifact = records.get_or_404(session, Artifact, artifact_id, "Artifact")
    if not can_view(session, user, artifact, RESOURCE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    return _detail(session, artifact, user)


@router.get(
    "/by-token/{public_token}",
    response_model=ArtifactDetail,
    summary="Read an artifact by its QR token",
    description=(
        "Resolves the token printed on an artifact's QR label. The token is "
        "stable across renumbering, so a label stays valid for the life of the "
        "object. Access is checked exactly as for the id route: a scanned "
        "label reveals nothing the scanner could not already see."
    ),
    responses={404: {"description": "No such token, or not visible to you"}},
)
def read_artifact_by_token(
    public_token: str, session: DbSession, user: CurrentUserOptional
) -> ArtifactDetail:
    artifact = session.scalar(select(Artifact).where(Artifact.public_token == public_token))
    if artifact is None or not can_view(session, user, artifact, RESOURCE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    return _detail(session, artifact, user)


@router.patch(
    "/{artifact_id}",
    response_model=ArtifactDetail,
    summary="Update an artifact",
    responses={403: {"description": "You may not edit this artifact"}},
)
def update_artifact(
    artifact_id: uuid.UUID,
    payload: ArtifactUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> ArtifactDetail:
    artifact = records.get_or_404(session, Artifact, artifact_id, "Artifact")
    if not can_view(session, user, artifact, RESOURCE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    if not can_edit(session, user, artifact, RESOURCE):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You may not edit this artifact")

    changes = payload.model_dump(exclude_unset=True)

    if "context_id" in changes:
        _check_context_belongs_to_site(session, changes["context_id"], artifact.site_id)

    if "inventory_number" in changes and changes["inventory_number"] != artifact.inventory_number:
        clash = session.scalar(
            select(Artifact.id).where(
                Artifact.site_id == artifact.site_id,
                Artifact.inventory_number == changes["inventory_number"],
                Artifact.id != artifact.id,
            )
        )
        if clash is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"Inventory number {changes['inventory_number']!r} is already used at this site",
            )

    latitude = changes.get("latitude", artifact.latitude)
    longitude = changes.get("longitude", artifact.longitude)
    try:
        records.validate_coordinates(latitude, longitude)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    before = records.apply_changes(artifact, changes)
    if "latitude" in before or "longitude" in before:
        records.sync_point_geometry(artifact)

    records.on_updated(session, artifact, RESOURCE, before=before, user=user, request=request)
    session.flush()
    return _detail(session, artifact, user)


@router.delete(
    "/{artifact_id}",
    response_model=Message,
    summary="Delete an artifact",
    responses={403: {"description": "You may not delete this artifact"}},
)
def delete_artifact(
    artifact_id: uuid.UUID, session: DbSession, request: Request, user: CurrentUser
) -> Message:
    artifact = records.get_or_404(session, Artifact, artifact_id, "Artifact")
    if not can_view(session, user, artifact, RESOURCE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    if not can_delete(session, user, artifact, RESOURCE):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You may not delete this artifact")

    label = artifact.inventory_number
    records.on_deleted(session, artifact, RESOURCE, user=user, request=request, label=label)
    session.delete(artifact)
    return Message(detail=f"Artifact {label!r} deleted")
