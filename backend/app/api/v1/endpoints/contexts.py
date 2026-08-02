"""Excavation context CRUD and stratigraphic relationships."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, CurrentUserOptional, DbSession
from app.core.permissions import can_delete, can_edit, can_view, visibility_filter
from app.models.artifact import Artifact
from app.models.context import ContextRelationship, ExcavationContext
from app.models.enums import (
    INVERSE_RELATION,
    ActivityAction,
    ContextType,
    ResourceType,
    ReviewStatus,
)
from app.models.site import Site
from app.models.user import User
from app.schemas.common import Message, Page
from app.schemas.context import (
    ContextCreate,
    ContextDetail,
    ContextSummary,
    ContextUpdate,
    MatrixPlan,
    MatrixResult,
    RelationshipCreate,
    RelationshipTarget,
)
from app.services import activity, matrix, records, spreadsheets

router = APIRouter(prefix="/contexts", tags=["Excavation contexts"])

RESOURCE = ResourceType.CONTEXT


def _relationships(session: DbSession, context_id: uuid.UUID) -> list[RelationshipTarget]:
    rows = session.execute(
        select(ContextRelationship, ExcavationContext.context_number)
        .join(
            ExcavationContext,
            ExcavationContext.id == ContextRelationship.related_context_id,
        )
        .where(ContextRelationship.context_id == context_id)
        .order_by(ExcavationContext.context_number)
    ).all()
    return [
        RelationshipTarget(
            id=relationship.id,
            relation=relationship.relation,
            related_context_id=relationship.related_context_id,
            related_context_number=number,
            certainty=relationship.certainty,
            notes=relationship.notes,
        )
        for relationship, number in rows
    ]


def _detail(session: DbSession, context: ExcavationContext, user: User | None) -> ContextDetail:
    detail = ContextDetail.model_validate(context)
    detail.artifact_count = (
        session.scalar(
            select(func.count()).select_from(Artifact).where(Artifact.context_id == context.id)
        )
        or 0
    )
    detail.relationships = _relationships(session, context.id)
    detail.can_edit = can_edit(session, user, context, RESOURCE)
    detail.can_delete = can_delete(session, user, context, RESOURCE)
    return detail


@router.get(
    "",
    response_model=Page[ContextSummary],
    summary="List excavation contexts",
)
def list_contexts(
    session: DbSession,
    user: CurrentUserOptional,
    q: Annotated[
        str | None, Query(description="Match context number, description or interpretation")
    ] = None,
    site_id: Annotated[uuid.UUID | None, Query()] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    context_type: Annotated[ContextType | None, Query()] = None,
    trench: Annotated[str | None, Query()] = None,
    area: Annotated[str | None, Query()] = None,
    phase: Annotated[str | None, Query()] = None,
    period_id: Annotated[uuid.UUID | None, Query()] = None,
    review_status: Annotated[ReviewStatus | None, Query()] = None,
    sort: Annotated[
        str, Query(pattern="^-?(context_number|created_at|excavation_date)$")
    ] = "context_number",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ContextSummary]:
    statement = select(ExcavationContext).where(
        visibility_filter(user, ExcavationContext, RESOURCE)
    )

    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(ExcavationContext.context_number).like(pattern),
                func.lower(ExcavationContext.description).like(pattern),
                func.lower(ExcavationContext.interpretation).like(pattern),
                func.lower(ExcavationContext.stratigraphic_unit).like(pattern),
            )
        )
    if site_id is not None:
        statement = statement.where(ExcavationContext.site_id == site_id)
    if project_id is not None:
        statement = statement.where(
            ExcavationContext.site_id.in_(select(Site.id).where(Site.project_id == project_id))
        )
    if context_type is not None:
        statement = statement.where(ExcavationContext.context_type == context_type)
    if trench:
        statement = statement.where(func.lower(ExcavationContext.trench) == trench.lower())
    if area:
        statement = statement.where(func.lower(ExcavationContext.area) == area.lower())
    if phase:
        statement = statement.where(func.lower(ExcavationContext.phase) == phase.lower())
    if period_id is not None:
        statement = statement.where(ExcavationContext.period_id == period_id)
    if review_status is not None:
        statement = statement.where(ExcavationContext.review_status == review_status)

    descending = sort.startswith("-")
    column = getattr(ExcavationContext, sort.lstrip("-"))
    statement = statement.order_by(column.desc() if descending else column.asc())

    rows, total = records.paginate(session, statement, limit, offset)
    return Page[ContextSummary](
        items=[ContextSummary.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=ContextDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create an excavation context",
    responses={409: {"description": "Context number already used at this site"}},
)
def create_context(
    payload: ContextCreate, session: DbSession, request: Request, user: CurrentUser
) -> ContextDetail:
    site = records.get_or_404(session, Site, payload.site_id, "Site")
    records.check_can_contribute(session, user, site.project_id)

    clash = session.scalar(
        select(ExcavationContext.id).where(
            ExcavationContext.site_id == payload.site_id,
            ExcavationContext.context_number == payload.context_number,
        )
    )
    if clash is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Context {payload.context_number!r} already exists at this site",
        )

    context = ExcavationContext(
        **payload.model_dump(),
        owner_id=user.id,
        review_status=records.initial_review_status(user),
    )
    records.sync_point_geometry(context)
    session.add(context)
    session.flush()

    records.on_created(session, context, RESOURCE, user=user, request=request)
    session.flush()
    return _detail(session, context, user)


@router.get(
    "/{context_id}",
    response_model=ContextDetail,
    summary="Read an excavation context",
    responses={404: {"description": "No such context, or not visible to you"}},
)
def read_context(
    context_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> ContextDetail:
    context = records.get_or_404(session, ExcavationContext, context_id, "Context")
    if not can_view(session, user, context, RESOURCE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Context not found")
    return _detail(session, context, user)


@router.patch(
    "/{context_id}",
    response_model=ContextDetail,
    summary="Update an excavation context",
    responses={403: {"description": "You may not edit this context"}},
)
def update_context(
    context_id: uuid.UUID,
    payload: ContextUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> ContextDetail:
    context = records.get_or_404(session, ExcavationContext, context_id, "Context")
    if not can_view(session, user, context, RESOURCE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Context not found")
    if not can_edit(session, user, context, RESOURCE):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You may not edit this context")

    changes = payload.model_dump(exclude_unset=True)

    if "context_number" in changes and changes["context_number"] != context.context_number:
        clash = session.scalar(
            select(ExcavationContext.id).where(
                ExcavationContext.site_id == context.site_id,
                ExcavationContext.context_number == changes["context_number"],
                ExcavationContext.id != context.id,
            )
        )
        if clash is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"Context {changes['context_number']!r} already exists at this site",
            )

    # The elevation constraint is enforced by the database too; checking here
    # turns a 409 from a raw constraint violation into a clear 422.
    top = changes.get("top_elevation", context.top_elevation)
    bottom = changes.get("bottom_elevation", context.bottom_elevation)
    if top is not None and bottom is not None and float(top) < float(bottom):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="top_elevation cannot be below bottom_elevation",
        )

    latitude = changes.get("latitude", context.latitude)
    longitude = changes.get("longitude", context.longitude)
    try:
        records.validate_coordinates(latitude, longitude)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    before = records.apply_changes(context, changes)
    if "latitude" in before or "longitude" in before:
        records.sync_point_geometry(context)

    records.on_updated(session, context, RESOURCE, before=before, user=user, request=request)
    session.flush()
    return _detail(session, context, user)


@router.delete(
    "/{context_id}",
    response_model=Message,
    summary="Delete an excavation context",
    description=(
        "Artifacts recorded in this context are kept; their `context_id` is "
        "cleared, because losing a find is worse than losing its stratigraphy."
    ),
    responses={403: {"description": "You may not delete this context"}},
)
def delete_context(
    context_id: uuid.UUID, session: DbSession, request: Request, user: CurrentUser
) -> Message:
    context = records.get_or_404(session, ExcavationContext, context_id, "Context")
    if not can_view(session, user, context, RESOURCE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Context not found")
    if not can_delete(session, user, context, RESOURCE):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You may not delete this context")

    label = context.context_number
    records.on_deleted(session, context, RESOURCE, user=user, request=request, label=label)
    session.delete(context)
    return Message(detail=f"Context {label!r} deleted")


# --------------------------------------------------------------------------
# Stratigraphic relationships
# --------------------------------------------------------------------------
@router.get(
    "/{context_id}/relationships",
    response_model=list[RelationshipTarget],
    summary="List a context's stratigraphic relationships",
)
def list_relationships(
    context_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> list[RelationshipTarget]:
    context = records.get_or_404(session, ExcavationContext, context_id, "Context")
    if not can_view(session, user, context, RESOURCE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Context not found")
    return _relationships(session, context.id)


@router.post(
    "/{context_id}/relationships",
    response_model=list[RelationshipTarget],
    status_code=status.HTTP_201_CREATED,
    summary="Record a stratigraphic relationship",
    description=(
        "Creates the edge and its mirror image: recording that 1041 *fills* "
        "1042 also records that 1042 is *filled by* 1041, so the Harris matrix "
        "cannot become one-sided."
    ),
    responses={
        409: {"description": "That relationship already exists"},
        422: {"description": "Contexts are at different sites, or the same context"},
    },
)
def add_relationship(
    context_id: uuid.UUID,
    payload: RelationshipCreate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> list[RelationshipTarget]:
    context = records.get_or_404(session, ExcavationContext, context_id, "Context")
    if not can_edit(session, user, context, RESOURCE):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You may not edit this context")

    if payload.related_context_id == context_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A context cannot be related to itself",
        )

    other = records.get_or_404(
        session, ExcavationContext, payload.related_context_id, "Related context"
    )
    if other.site_id != context.site_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Contexts can only be related within the same site",
        )

    existing = session.scalar(
        select(ContextRelationship).where(
            ContextRelationship.context_id == context_id,
            ContextRelationship.related_context_id == payload.related_context_id,
            ContextRelationship.relation == payload.relation,
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="That relationship is already recorded"
        )

    session.add(
        ContextRelationship(
            context_id=context_id,
            related_context_id=payload.related_context_id,
            relation=payload.relation,
            certainty=payload.certainty,
            notes=payload.notes,
        )
    )

    # The mirrored edge is what keeps reads to a single indexed lookup. It is
    # added only if absent, so re-recording the pair from the other side is
    # harmless rather than a constraint violation.
    inverse = INVERSE_RELATION[payload.relation]
    mirrored = session.scalar(
        select(ContextRelationship).where(
            ContextRelationship.context_id == payload.related_context_id,
            ContextRelationship.related_context_id == context_id,
            ContextRelationship.relation == inverse,
        )
    )
    if mirrored is None:
        session.add(
            ContextRelationship(
                context_id=payload.related_context_id,
                related_context_id=context_id,
                relation=inverse,
                certainty=payload.certainty,
                notes=payload.notes,
            )
        )

    from app.models.enums import ActivityAction
    from app.services import activity

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=context.id,
        resource_label=context.context_number,
        project_id=session.scalar(select(Site.project_id).where(Site.id == context.site_id)),
        summary=f"{context.context_number} {payload.relation.value} {other.context_number}",
        request=request,
    )
    session.flush()
    return _relationships(session, context_id)


@router.delete(
    "/{context_id}/relationships/{relationship_id}",
    response_model=Message,
    summary="Remove a stratigraphic relationship",
    description="Removes the mirrored edge as well, so the matrix stays symmetric.",
)
def remove_relationship(
    context_id: uuid.UUID,
    relationship_id: uuid.UUID,
    session: DbSession,
    user: CurrentUser,
) -> Message:
    context = records.get_or_404(session, ExcavationContext, context_id, "Context")
    if not can_edit(session, user, context, RESOURCE):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You may not edit this context")

    relationship = session.get(ContextRelationship, relationship_id)
    if relationship is None or relationship.context_id != context_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Relationship not found")

    mirrored = session.scalar(
        select(ContextRelationship).where(
            ContextRelationship.context_id == relationship.related_context_id,
            ContextRelationship.related_context_id == context_id,
            ContextRelationship.relation == INVERSE_RELATION[relationship.relation],
        )
    )
    session.delete(relationship)
    if mirrored is not None:
        session.delete(mirrored)

    return Message(detail="Relationship removed")


# --------------------------------------------------------------------------
# Building the matrix from a spreadsheet
# --------------------------------------------------------------------------
@router.post(
    "/sites/{site_id}/stratigraphy/preview",
    response_model=MatrixPlan,
    summary="Check a stratigraphy spreadsheet before importing it",
    description=(
        "Reads a sheet of relationships and says what it *would* do. Nothing "
        "is written.\n\n"
        "The sheet needs three columns — the context, the relationship, and "
        "the related context — under any of the usual headings. Certainty and "
        "notes are taken if they are there.\n\n"
        "Relationships are read as words: *above*, *below*, *cuts*, *cut by*, "
        "*fills*, *filled by*, *same as*, *abuts*, and the obvious synonyms, "
        "so a sheet written for people does not have to be rewritten for a "
        "computer.\n\n"
        "**An impossible sequence stops the import.** If the sheet says 1001 "
        "is above 1002, 1002 above 1003 and 1003 above 1001, no stratigraphy "
        "could produce that — it is nearly always two columns the wrong way "
        "round. The loop is reported in full so the wrong link can be found."
    ),
)
async def preview_stratigraphy(
    site_id: uuid.UUID,
    session: DbSession,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="An .xlsx or .csv of relationships")],
    sheet_name: Annotated[str | None, Form()] = None,
) -> MatrixPlan:
    site = _site_for_matrix(session, site_id, user)
    sheet = _read_sheet(await file.read(), file.filename or "upload.xlsx", sheet_name)
    columns = matrix.match_columns(sheet.columns)
    return _as_plan(matrix.plan(session, site.id, sheet.rows, columns), sheet)


@router.post(
    "/sites/{site_id}/stratigraphy/import",
    response_model=MatrixResult,
    summary="Build the matrix from a spreadsheet",
    description=(
        "The same reading as the preview, then it writes. Both directions of "
        "each relationship are stored, so the matrix reads correctly from "
        "either context.\n\n"
        "Rows already in the database are skipped rather than duplicated — "
        "re-importing a corrected sheet is the normal way to use this."
    ),
)
async def import_stratigraphy(
    site_id: uuid.UUID,
    session: DbSession,
    request: Request,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
    sheet_name: Annotated[str | None, Form()] = None,
) -> MatrixResult:
    site = _site_for_matrix(session, site_id, user, writing=True)
    sheet = _read_sheet(await file.read(), file.filename or "upload.xlsx", sheet_name)
    columns = matrix.match_columns(sheet.columns)
    planned = matrix.plan(session, site.id, sheet.rows, columns)

    if planned.contradictions:
        loops = "; ".join(" → ".join(loop) for loop in planned.contradictions[:3])
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "This sheet describes a sequence that cannot exist, so nothing "
                f"was imported. {loops}. Two columns the wrong way round is the "
                "usual cause."
            ),
        )
    if not planned.edges:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No usable relationships were found in that sheet.",
        )

    written = matrix.apply(session, site.id, planned)
    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_type=ResourceType.SITE,
        resource_id=site.id,
        resource_label=site.name,
        summary=f"Imported {written} stratigraphic relationships for {site.name}",
        request=request,
    )
    session.flush()

    result = MatrixResult.model_validate(_as_plan(planned, sheet).model_dump())
    result.written = written
    return result


def _site_for_matrix(
    session: DbSession, site_id: uuid.UUID, user: User, *, writing: bool = False
) -> Site:
    site = records.get_or_404(session, Site, site_id, "Site")
    if not can_view(session, user, site, ResourceType.SITE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Site not found")
    if writing and not can_edit(session, user, site, ResourceType.SITE):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="You may not change this site's stratigraphy"
        )
    return site


def _read_sheet(data: bytes, filename: str, sheet_name: str | None):
    try:
        return spreadsheets.read(data, filename=filename, sheet_name=sheet_name)
    except spreadsheets.SpreadsheetError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error


def _as_plan(planned: matrix.Plan, sheet) -> MatrixPlan:
    return MatrixPlan(
        sheet_name=sheet.name,
        row_count=len(sheet.rows),
        columns=planned.columns,
        usable=len(planned.edges),
        already_there=planned.already_there,
        problems=[{"row": item.row, "message": item.message} for item in planned.problems],
        contradictions=planned.contradictions,
        can_apply=planned.can_apply,
        relationships=[
            {
                "row": edge.row,
                "context": edge.context_number,
                "relation": edge.relation.value,
                "related": edge.related_number,
            }
            for edge in planned.edges[:200]
        ],
    )
