"""Floor plans: drawing the store, and reading it back.

The plan holds no inventory of its own. A shape says "this rectangle is
Cabinet 4"; what Cabinet 4 contains is answered by the store, every time it is
asked. A plan that cached its own object list would be a second copy of the
truth and would be wrong within a week of somebody moving a box.

Permissions follow the store: seeing a plan needs access to a module that
stores things, and changing one is a supervisor's job — moving a cabinet on
the plan is a claim about the building.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.api.deps import CurrentUserOptional, DbSession
from app.api.v1.endpoints.storage import STORABLE, StorageKeeper, StorageReader, _storable_filter
from app.models.enums import ActivityAction, ResourceType
from app.models.floorplan import FloorPlan, FloorPlanShape
from app.models.storage import StorageLocation
from app.schemas.common import Message, Page
from app.schemas.floorplan import (
    FloorPlanCreate,
    FloorPlanDetail,
    FloorPlanSummary,
    FloorPlanUpdate,
    ShapeCreate,
    ShapeRead,
    ShapeReorder,
    ShapeUpdate,
)
from app.services import activity, images, records
from app.services.storage import StorageError, storage

router = APIRouter(prefix="/floorplans", tags=["Floor plans"])

#: A plan drawing is a scan or an export, so it is larger than a thumbnail and
#: smaller than a photograph of an object.
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def _get_plan(session: DbSession, plan_id: uuid.UUID) -> FloorPlan:
    return records.get_or_404(session, FloorPlan, plan_id, "Floor plan")


def _counts(session: DbSession, user, location_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """How many things sit in each location, permission-filtered.

    One query per storable kind rather than one per shape: a gallery plan has
    forty cabinets on it, and forty round trips to draw one screen is the kind
    of thing that makes a plan feel broken on a site-house connection.
    """
    if not location_ids:
        return {}

    totals: dict[uuid.UUID, int] = dict.fromkeys(location_ids, 0)
    for entry in STORABLE.values():
        model = entry.model
        rows = session.execute(
            select(model.storage_location_id, func.count())
            .where(
                model.storage_location_id.in_(location_ids),
                _storable_filter(user, entry),
            )
            .group_by(model.storage_location_id)
        ).all()
        for location_id, count in rows:
            totals[location_id] = totals.get(location_id, 0) + count
    return totals


def _shape_read(shape: FloorPlanShape, counts: dict[uuid.UUID, int]) -> ShapeRead:
    payload = ShapeRead.model_validate(shape)
    if shape.location is not None:
        payload.location_name = shape.location.name
        payload.location_path = shape.location.display_path
        payload.item_count = counts.get(shape.location_id, 0)
    return payload


def _summary(session: DbSession, plan: FloorPlan) -> FloorPlanSummary:
    payload = FloorPlanSummary.model_validate(plan)
    if plan.location is not None:
        payload.location_name = plan.location.name
        payload.location_path = plan.location.display_path
    payload.shape_count = len(plan.shapes)
    payload.image_url = f"/api/v1/floorplans/{plan.id}/image" if plan.image_path else None
    return payload


def _detail(session: DbSession, plan: FloorPlan, user) -> FloorPlanDetail:
    location_ids = [shape.location_id for shape in plan.shapes if shape.location_id]
    counts = _counts(session, user, location_ids)

    payload = FloorPlanDetail.model_validate(_summary(session, plan).model_dump())
    payload.shapes = [_shape_read(shape, counts) for shape in plan.shapes]
    return payload


# --------------------------------------------------------------------------
# Plans
# --------------------------------------------------------------------------
@router.post(
    "",
    response_model=FloorPlanDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a floor plan",
    description=(
        "A plan of one place in the store — a building, a floor, a room. "
        "Upload a background separately with `PUT /floorplans/{id}/image`, or "
        "draw from nothing.\n\n"
        "`width_m` and `height_m` describe the real extent of the drawn area, "
        "so the viewer can show a scale bar."
    ),
)
def create_plan(
    payload: FloorPlanCreate, session: DbSession, request: Request, keeper: StorageKeeper
) -> FloorPlanDetail:
    location = records.get_or_404(session, StorageLocation, payload.location_id, "Storage location")

    plan = FloorPlan(**payload.model_dump(), owner_id=keeper.id)
    if plan.is_default:
        _clear_other_defaults(session, location.id, exclude=None)
    session.add(plan)
    session.flush()

    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=keeper,
        resource_type=ResourceType.SITE,
        resource_id=plan.id,
        resource_label=plan.name,
        summary=f"Created floor plan {plan.name!r} for {location.display_path}",
        request=request,
    )
    session.flush()
    return _detail(session, plan, keeper)


def _clear_other_defaults(
    session: DbSession, location_id: uuid.UUID, *, exclude: uuid.UUID | None
) -> None:
    """One default per location; the flag is a choice, not a free-for-all."""
    statement = select(FloorPlan).where(
        FloorPlan.location_id == location_id, FloorPlan.is_default.is_(True)
    )
    if exclude is not None:
        statement = statement.where(FloorPlan.id != exclude)
    for other in session.scalars(statement):
        other.is_default = False


@router.get("", response_model=Page[FloorPlanSummary], summary="List floor plans")
def list_plans(
    session: DbSession,
    reader: StorageReader,
    location_id: Annotated[uuid.UUID | None, Query(description="Plans of this location")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[FloorPlanSummary]:
    statement = select(FloorPlan).order_by(FloorPlan.is_default.desc(), FloorPlan.name)
    if location_id is not None:
        statement = statement.where(FloorPlan.location_id == location_id)

    rows, total = records.paginate(session, statement, limit, offset)
    return Page[FloorPlanSummary](
        items=[_summary(session, row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.get(
    "/{plan_id}",
    response_model=FloorPlanDetail,
    summary="Read a plan and its shapes",
    description=(
        "Every shape, plus — for each one that stands for a place — what that "
        "place currently holds. The count is read from the store at request "
        "time and permission-filtered, so a plan never reveals objects the "
        "caller could not otherwise see."
    ),
)
def read_plan(
    plan_id: uuid.UUID, session: DbSession, user: CurrentUserOptional, reader: StorageReader
) -> FloorPlanDetail:
    return _detail(session, _get_plan(session, plan_id), user)


@router.patch("/{plan_id}", response_model=FloorPlanDetail, summary="Update a plan")
def update_plan(
    plan_id: uuid.UUID, payload: FloorPlanUpdate, session: DbSession, keeper: StorageKeeper
) -> FloorPlanDetail:
    plan = _get_plan(session, plan_id)
    changes = payload.model_dump(exclude_unset=True)

    if changes.get("is_default"):
        _clear_other_defaults(session, plan.location_id, exclude=plan.id)

    for key, value in changes.items():
        setattr(plan, key, value)
    session.flush()
    return _detail(session, plan, keeper)


@router.delete("/{plan_id}", response_model=Message, summary="Delete a plan")
def delete_plan(
    plan_id: uuid.UUID, session: DbSession, request: Request, keeper: StorageKeeper
) -> Message:
    plan = _get_plan(session, plan_id)
    name = plan.name

    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=keeper,
        resource_type=ResourceType.SITE,
        resource_id=plan.id,
        resource_label=name,
        summary=f"Deleted floor plan {name!r}",
        request=request,
    )
    session.delete(plan)
    return Message(
        detail=(
            f"Floor plan {name!r} deleted. The locations it drew are untouched — "
            f"a plan is a picture of the store, not the store."
        )
    )


# --------------------------------------------------------------------------
# The background image
# --------------------------------------------------------------------------
@router.put(
    "/{plan_id}/image",
    response_model=FloorPlanDetail,
    summary="Upload the plan's background",
    description=(
        "The drawing the institution already has — an architect's plan, a "
        "scan, an export. Shapes are stored as fractions of the plan's "
        "extent, so replacing this image with a better scan of the same room "
        "leaves every shape where it was."
    ),
    responses={422: {"description": "Not a readable image"}},
)
async def upload_image(
    plan_id: uuid.UUID,
    session: DbSession,
    keeper: StorageKeeper,
    file: Annotated[UploadFile, File(description="PNG, JPEG or WebP")],
) -> FloorPlanDetail:
    plan = _get_plan(session, plan_id)

    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"The image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB. "
                f"Export the plan at a lower resolution."
            ),
        )

    try:
        # Decoded rather than trusted: a file claiming to be a PNG is not one
        # until something has read it, and the dimensions are needed anyway.
        facts = images.inspect(data)
    except images.ImageError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    stored = storage.save_bytes(data, category="floorplans", extension=facts.extension)
    plan.image_path = stored.path
    plan.image_width = facts.width
    plan.image_height = facts.height
    plan.image_mime = facts.mime_type
    session.flush()
    return _detail(session, plan, keeper)


@router.get(
    "/{plan_id}/image",
    summary="The plan's background image",
    response_class=FileResponse,
    responses={200: {"content": {"image/*": {}}}, 404: {"description": "No image"}},
)
def read_image(plan_id: uuid.UUID, session: DbSession, reader: StorageReader) -> FileResponse:
    plan = _get_plan(session, plan_id)
    if not plan.image_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This plan has no background image")

    try:
        path = storage.absolute_path(plan.image_path)
    except StorageError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return FileResponse(
        path,
        media_type=plan.image_mime or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=3600"},
    )


# --------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------
@router.put(
    "/{plan_id}/shapes",
    response_model=FloorPlanDetail,
    summary="Replace every shape on a plan",
    description=(
        "Drawing is a rapid sequence of small edits, so the editor sends the "
        "whole set rather than a request per drag. Replacing atomically also "
        "means a half-applied plan is not a state that can exist."
    ),
)
def replace_shapes(
    plan_id: uuid.UUID, payload: ShapeReorder, session: DbSession, keeper: StorageKeeper
) -> FloorPlanDetail:
    plan = _get_plan(session, plan_id)

    _check_locations(session, [shape.location_id for shape in payload.shapes])

    plan.shapes.clear()
    session.flush()
    for index, shape in enumerate(payload.shapes):
        data = shape.model_dump()
        data.setdefault("z_index", index)
        plan.shapes.append(FloorPlanShape(**data))
    session.flush()
    return _detail(session, plan, keeper)


def _check_locations(session: DbSession, ids: list[uuid.UUID | None]) -> None:
    """A shape pointing at a location that does not exist would draw a cabinet
    nobody can open, so it is refused rather than stored."""
    wanted = {value for value in ids if value is not None}
    if not wanted:
        return
    found = set(
        session.scalars(select(StorageLocation.id).where(StorageLocation.id.in_(wanted))).all()
    )
    missing = wanted - found
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{len(missing)} shape{'' if len(missing) == 1 else 's'} point at a "
                f"storage location that does not exist."
            ),
        )


@router.post(
    "/{plan_id}/shapes",
    response_model=ShapeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add one shape",
)
def add_shape(
    plan_id: uuid.UUID, payload: ShapeCreate, session: DbSession, keeper: StorageKeeper
) -> ShapeRead:
    plan = _get_plan(session, plan_id)
    _check_locations(session, [payload.location_id])

    shape = FloorPlanShape(plan_id=plan.id, **payload.model_dump())
    session.add(shape)
    session.flush()
    counts = _counts(session, keeper, [shape.location_id] if shape.location_id else [])
    return _shape_read(shape, counts)


@router.patch("/{plan_id}/shapes/{shape_id}", response_model=ShapeRead, summary="Update one shape")
def update_shape(
    plan_id: uuid.UUID,
    shape_id: uuid.UUID,
    payload: ShapeUpdate,
    session: DbSession,
    keeper: StorageKeeper,
) -> ShapeRead:
    shape = records.get_or_404(session, FloorPlanShape, shape_id, "Shape")
    if shape.plan_id != plan_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Shape not found on this plan")

    changes = payload.model_dump(exclude_unset=True)
    if "location_id" in changes:
        _check_locations(session, [changes["location_id"]])
    for key, value in changes.items():
        setattr(shape, key, value)
    session.flush()

    counts = _counts(session, keeper, [shape.location_id] if shape.location_id else [])
    return _shape_read(shape, counts)


@router.delete("/{plan_id}/shapes/{shape_id}", response_model=Message, summary="Delete one shape")
def delete_shape(
    plan_id: uuid.UUID, shape_id: uuid.UUID, session: DbSession, keeper: StorageKeeper
) -> Message:
    shape = records.get_or_404(session, FloorPlanShape, shape_id, "Shape")
    if shape.plan_id != plan_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Shape not found on this plan")

    session.delete(shape)
    return Message(detail="Shape deleted. Nothing filed in the store was touched.")


# --------------------------------------------------------------------------
# Finding a thing on a plan
# --------------------------------------------------------------------------
@router.get(
    "/for-location/{location_id}",
    response_model=list[FloorPlanSummary],
    summary="Which plans show this location",
    description=(
        "Plans of this location, and plans of anywhere above it that draw it. "
        "This is what answers *show me where this object is* from the object's "
        "own card: the object is in a box, the box is on a shelf, and it is the "
        "room's plan that has the cabinet drawn on it."
    ),
)
def plans_for_location(
    location_id: uuid.UUID, session: DbSession, reader: StorageReader
) -> list[FloorPlanSummary]:
    location = records.get_or_404(session, StorageLocation, location_id, "Storage location")

    # Every ancestor, by walking the materialised path back up.
    prefixes: list[str] = []
    parts = location.path.strip("/").split("/")
    for index in range(1, len(parts) + 1):
        prefixes.append("/" + "/".join(parts[:index]))

    ancestors = session.scalars(
        select(StorageLocation.id).where(StorageLocation.path.in_(prefixes))
    ).all()

    # A plan is relevant if it is *of* one of those places, or if one of its
    # shapes points at this location or at something above it.
    by_location = select(FloorPlan).where(FloorPlan.location_id.in_(ancestors))
    by_shape = (
        select(FloorPlan).join(FloorPlanShape).where(FloorPlanShape.location_id.in_(ancestors))
    )

    seen: dict[uuid.UUID, FloorPlan] = {}
    for statement in (by_location, by_shape):
        for plan in session.scalars(statement):
            seen[plan.id] = plan

    return [
        _summary(session, plan)
        for plan in sorted(seen.values(), key=lambda item: (not item.is_default, item.name))
    ]
