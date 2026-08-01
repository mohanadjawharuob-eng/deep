"""Storage locations, and the register of what moved where.

Every physical object in the platform — a find, an accessioned museum object, a
total station — is filed against a node in one shared hierarchy, and every
change of place is appended to a register that is never rewritten.

Permissions: reading the tree needs viewer access to any module that stores
things; changing it is a supervisor's job, because renaming a room silently
changes what every label in it claims.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, CurrentUserOptional, DbSession, require_module
from app.core.permissions import (
    ModuleLevel,
    can_edit,
    has_module_access,
    visibility_filter,
)
from app.models.artifact import Artifact
from app.models.enums import ActivityAction, Module, ResourceType, StorageKind
from app.models.storage import StorageLocation, StorageMovement
from app.models.user import User
from app.schemas.common import Message, Page
from app.schemas.storage import (
    LocationOfRecord,
    MovementCreate,
    MovementRead,
    StorageLocationCreate,
    StorageLocationDetail,
    StorageLocationMove,
    StorageLocationNode,
    StorageLocationRead,
    StorageLocationSummary,
    StorageLocationUpdate,
)
from app.services import activity, records
from app.services import storage_locations as tree

router = APIRouter(prefix="/storage", tags=["Storage locations"])

RESOURCE = ResourceType.ARTIFACT

#: Modules whose users need to see the store. Reading the hierarchy is not
#: sensitive — it describes a building, not the objects in it — so holding any
#: of these is enough.
STORING_MODULES = (Module.ARCHAEOLOGY, Module.MUSEUM, Module.INVENTORY)

#: Which record types can be filed in a location. Museum objects and inventory
#: items join this as those modules are built; the movement register already
#: stores the resource type, so nothing here changes when they do.
STORABLE: dict[str, tuple[type, ResourceType, str]] = {
    "artifacts": (Artifact, ResourceType.ARTIFACT, "Artifact"),
}


def _may_read_storage(user: User | None) -> bool:
    return any(has_module_access(user, module, ModuleLevel.VIEWER) for module in STORING_MODULES)


def require_storage_reader(user: CurrentUser) -> User:
    if not _may_read_storage(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=(
                "Seeing the store needs access to the archaeology, museum or " "inventory module"
            ),
        )
    return user


StorageReader = Annotated[User, Depends(require_storage_reader)]
#: Changing the shape of the store is a supervisor's job: renaming a room
#: changes what every label inside it claims.
StorageKeeper = Annotated[User, Depends(require_module(Module.ARCHAEOLOGY, ModuleLevel.SUPERVISOR))]


def _translate(error: tree.StorageError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))


def _get_location(session: DbSession, location_id: uuid.UUID) -> StorageLocation:
    location = session.get(StorageLocation, location_id)
    if location is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Storage location not found")
    return location


# --------------------------------------------------------------------------
# The hierarchy
# --------------------------------------------------------------------------
@router.post(
    "/locations",
    response_model=StorageLocationDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Add a storage location",
    description=(
        "Adds one node to the hierarchy: institution, building, floor, room, "
        "cabinet, shelf, drawer or box. Omit `parent_id` for a root.\n\n"
        "Levels may be skipped — a crate standing on a room floor has no "
        "cabinet — but a child must nest *deeper* than its parent, so a room "
        "cannot be placed inside a shelf."
    ),
    responses={422: {"description": "That kind cannot sit inside that parent"}},
)
def create_location(
    payload: StorageLocationCreate, session: DbSession, request: Request, keeper: StorageKeeper
) -> StorageLocationDetail:
    try:
        location = tree.create(
            session,
            kind=payload.kind,
            name=payload.name,
            code=payload.code,
            parent_id=payload.parent_id,
            description=payload.description,
            capacity=payload.capacity,
            is_active=payload.is_active,
            target_temperature_c=payload.target_temperature_c,
            target_humidity_percent=payload.target_humidity_percent,
            environment_notes=payload.environment_notes,
            metadata_json=payload.metadata_json,
        )
    except tree.StorageError as exc:
        raise _translate(exc) from exc

    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=keeper,
        resource_type=ResourceType.SITE,
        resource_id=location.id,
        resource_label=location.display_path,
        summary=f"Created storage location {location.display_path}",
        request=request,
    )
    session.flush()
    return _detail(session, location)


@router.get(
    "/locations",
    response_model=Page[StorageLocationSummary],
    summary="List storage locations",
)
def list_locations(
    session: DbSession,
    reader: StorageReader,
    q: Annotated[str | None, Query(description="Match name, code or path")] = None,
    kind: Annotated[StorageKind | None, Query()] = None,
    parent_id: Annotated[
        uuid.UUID | None, Query(description="Direct children of this node")
    ] = None,
    within: Annotated[
        uuid.UUID | None, Query(description="Everything beneath this node, at any depth")
    ] = None,
    is_active: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[StorageLocationSummary]:
    statement = select(StorageLocation)

    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(StorageLocation.name).like(pattern),
                func.lower(StorageLocation.code).like(pattern),
                func.lower(StorageLocation.display_path).like(pattern),
            )
        )
    if kind is not None:
        statement = statement.where(StorageLocation.kind == kind)
    if parent_id is not None:
        statement = statement.where(StorageLocation.parent_id == parent_id)
    if within is not None:
        root = _get_location(session, within)
        # Prefix match on the materialised path — the separator keeps
        # ``/room-2`` from also matching ``/room-20``.
        statement = statement.where(StorageLocation.path.startswith(f"{root.path}/"))
    if is_active is not None:
        statement = statement.where(StorageLocation.is_active.is_(is_active))

    statement = statement.order_by(StorageLocation.path)
    rows, total = records.paginate(session, statement, limit, offset)
    return Page[StorageLocationSummary](
        items=[StorageLocationSummary.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/tree",
    response_model=list[StorageLocationNode],
    summary="The whole hierarchy, nested",
    description=(
        "The store as a tree, ready to render. Built from one query rather "
        "than one per level, so a deep hierarchy costs the same as a shallow "
        "one."
    ),
)
def read_tree(
    session: DbSession,
    reader: StorageReader,
    root_id: Annotated[uuid.UUID | None, Query(description="Start below this node")] = None,
    include_inactive: Annotated[bool, Query()] = False,
) -> list[StorageLocationNode]:
    statement = select(StorageLocation).order_by(StorageLocation.path)
    if not include_inactive:
        statement = statement.where(StorageLocation.is_active.is_(True))
    if root_id is not None:
        root = _get_location(session, root_id)
        statement = statement.where(
            or_(StorageLocation.id == root.id, StorageLocation.path.startswith(f"{root.path}/"))
        )

    rows = list(session.scalars(statement).all())

    # Built from the *summary* fields, not by validating the ORM object
    # directly. ``StorageLocation.children`` is a relationship, so validating
    # the node schema against the row would populate the subtree from the ORM
    # — lazily, one query per node — and the manual linking below would then
    # append every child a second time.
    nodes = {
        row.id: StorageLocationNode(
            **StorageLocationSummary.model_validate(row).model_dump(), children=[]
        )
        for row in rows
    }

    roots: list[StorageLocationNode] = []
    for row in rows:
        node = nodes[row.id]
        parent = nodes.get(row.parent_id) if row.parent_id else None
        # A node whose parent was filtered out becomes a root of the result,
        # so an inactive room does not hide the shelves inside it.
        if parent is None:
            roots.append(node)
        else:
            parent.children.append(node)
    return roots


def _detail(session: DbSession, location: StorageLocation) -> StorageLocationDetail:
    # Same reason as in ``read_tree``: ``StorageLocationRead`` has no
    # ``children`` field, so building from it does not drag the relationship in
    # only for it to be replaced below.
    payload = StorageLocationDetail(**StorageLocationRead.model_validate(location).model_dump())
    payload.ancestors = [
        StorageLocationSummary.model_validate(row) for row in tree.ancestors(session, location)
    ]
    payload.children = [
        StorageLocationSummary.model_validate(row)
        for row in session.scalars(
            select(StorageLocation)
            .where(StorageLocation.parent_id == location.id)
            .order_by(StorageLocation.name)
        ).all()
    ]
    payload.object_count = tree.occupancy(session, location, include_children=False)
    payload.subtree_object_count = tree.occupancy(session, location, include_children=True)
    return payload


@router.get(
    "/locations/{location_id}",
    response_model=StorageLocationDetail,
    summary="Read a storage location",
)
def read_location(
    location_id: uuid.UUID, session: DbSession, reader: StorageReader
) -> StorageLocationDetail:
    return _detail(session, _get_location(session, location_id))


@router.patch(
    "/locations/{location_id}",
    response_model=StorageLocationDetail,
    summary="Update a storage location",
    description=(
        "Renaming or recoding a location rewrites the stored path of "
        "everything inside it, so the tree stays consistent."
    ),
)
def update_location(
    location_id: uuid.UUID,
    payload: StorageLocationUpdate,
    session: DbSession,
    request: Request,
    keeper: StorageKeeper,
) -> StorageLocationDetail:
    location = _get_location(session, location_id)
    changes = payload.model_dump(exclude_unset=True)

    name = changes.pop("name", None)
    code = changes.pop("code", None)
    before_path = location.display_path

    for field, value in changes.items():
        setattr(location, field, value)

    if name is not None or code is not None:
        try:
            tree.rename(session, location, name=name, code=code)
        except tree.StorageError as exc:
            raise _translate(exc) from exc
    session.add(location)
    session.flush()

    summary = f"Updated storage location {location.display_path}"
    if before_path != location.display_path:
        summary = f"Renamed storage location {before_path} to {location.display_path}"
    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=keeper,
        resource_type=ResourceType.SITE,
        resource_id=location.id,
        resource_label=location.display_path,
        summary=summary,
        request=request,
    )
    session.flush()
    return _detail(session, location)


@router.post(
    "/locations/{location_id}/move",
    response_model=StorageLocationDetail,
    summary="Move a location and everything in it",
    description=(
        "Reparents a node — a cabinet moved to another room takes its shelves, "
        "drawers and boxes with it. Refused if it would place the node inside "
        "its own subtree, which would make a loop."
    ),
    responses={422: {"description": "That move would make a loop or invert the hierarchy"}},
)
def move_location(
    location_id: uuid.UUID,
    payload: StorageLocationMove,
    session: DbSession,
    request: Request,
    keeper: StorageKeeper,
) -> StorageLocationDetail:
    location = _get_location(session, location_id)
    before = location.display_path

    try:
        tree.relocate(session, location, payload.parent_id)
    except tree.StorageError as exc:
        raise _translate(exc) from exc

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=keeper,
        resource_type=ResourceType.SITE,
        resource_id=location.id,
        resource_label=location.display_path,
        summary=f"Moved storage location {before} to {location.display_path}",
        request=request,
    )
    session.flush()
    return _detail(session, location)


@router.delete(
    "/locations/{location_id}",
    response_model=Message,
    summary="Delete an empty storage location",
    description=(
        "Only an empty leaf can be deleted. A location holding objects, or "
        "containing other locations, is refused — deleting it would leave "
        "material with no recorded place, which is exactly the state this "
        "hierarchy exists to prevent. Mark it inactive instead."
    ),
    responses={409: {"description": "The location still holds objects or child locations"}},
)
def delete_location(
    location_id: uuid.UUID, session: DbSession, request: Request, keeper: StorageKeeper
) -> Message:
    location = _get_location(session, location_id)

    children = session.scalar(
        select(func.count())
        .select_from(StorageLocation)
        .where(StorageLocation.parent_id == location.id)
    )
    if children:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"{location.display_path} still contains {children} location(s). "
                f"Empty it first, or mark it inactive."
            ),
        )

    held = tree.occupancy(session, location, include_children=False)
    if held:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"{location.display_path} still holds {held} object(s). Move them "
                f"first, or mark it inactive."
            ),
        )

    label = location.display_path
    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=keeper,
        resource_type=ResourceType.SITE,
        resource_id=location.id,
        resource_label=label,
        summary=f"Deleted storage location {label}",
        request=request,
    )
    session.delete(location)
    return Message(detail=f"Storage location {label!r} deleted")


@router.get(
    "/locations/{location_id}/contents",
    response_model=Page[dict],
    summary="What is filed in a location",
    description=(
        "Objects filed here. `include_children` widens the answer to the whole "
        "subtree, which is what 'what is in Room 203' usually means.\n\n"
        "Results are permission-filtered per object, so this cannot be used to "
        "enumerate records the caller could not otherwise see."
    ),
)
def read_contents(
    location_id: uuid.UUID,
    session: DbSession,
    user: CurrentUserOptional,
    reader: StorageReader,
    include_children: Annotated[bool, Query()] = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[dict]:
    location = _get_location(session, location_id)

    ids = [location.id]
    if include_children:
        ids.extend(child.id for child in tree.descendants(session, location))

    statement = (
        select(Artifact)
        .where(
            Artifact.storage_location_id.in_(ids),
            # The store is not a way around record permissions.
            visibility_filter(user, Artifact, ResourceType.ARTIFACT),
        )
        .order_by(Artifact.inventory_number, Artifact.id)
    )
    rows, total = records.paginate(session, statement, limit, offset)

    items = [
        {
            "resource_type": ResourceType.ARTIFACT.value,
            "id": str(row.id),
            "inventory_number": row.inventory_number,
            "name": row.name,
            "storage_location_id": str(row.storage_location_id)
            if row.storage_location_id
            else None,
        }
        for row in rows
    ]
    return Page[dict](items=items, total=total, limit=limit, offset=offset)


# --------------------------------------------------------------------------
# The movement register
# --------------------------------------------------------------------------
def _resolve_storable(kind: str) -> tuple[type, ResourceType, str]:
    entry = STORABLE.get(kind)
    if entry is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"{kind!r} cannot be filed in storage; expected one of {', '.join(STORABLE)}",
        )
    return entry


@router.post(
    "/{kind}/{record_id}/move",
    response_model=MovementRead,
    status_code=status.HTTP_201_CREATED,
    summary="Move an object to a new location",
    description=(
        "Files an object in a new place and appends the move to the register. "
        "Send `to_location_id: null` to record it leaving storage entirely — "
        "repatriated, or consumed by destructive analysis.\n\n"
        "Moving an object to where it already is changes nothing and is "
        "reported as such, so re-submitting a form cannot manufacture a "
        "movement that never happened."
    ),
    responses={
        409: {"description": "The object is already there"},
        422: {"description": "No such location, or it is not accepting objects"},
    },
)
def move_record(
    kind: str,
    record_id: uuid.UUID,
    payload: MovementCreate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> MovementRead:
    model, resource_type, name = _resolve_storable(kind)
    record = records.get_or_404(session, model, record_id, name)

    # Moving an object is editing it: whoever may correct the record may say
    # where it is, and nobody else.
    if not can_edit(session, user, record, resource_type):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail=f"You may not move this {name.lower()}"
        )

    try:
        movement = tree.move_object(
            session,
            record,
            resource_type,
            to_location_id=payload.to_location_id,
            reason=payload.reason,
            notes=payload.notes,
            moved_at=payload.moved_at,
            user=user,
            label=records.label_for(record),
        )
    except tree.StorageError as exc:
        raise _translate(exc) from exc

    if movement is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="That object is already in this location; nothing was recorded",
        )

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=resource_type,
        resource_id=record.id,
        resource_label=records.label_for(record),
        project_id=getattr(record, "project_id", None),
        summary=(
            f"Moved to {movement.to_path}"
            if movement.to_path
            else f"Removed from storage ({movement.reason.value})"
        ),
        request=request,
    )
    session.flush()
    return MovementRead.model_validate(movement)


@router.get(
    "/{kind}/{record_id}/movements",
    response_model=list[MovementRead],
    summary="Where an object has been",
    description=(
        "The full movement history, oldest first. Paths are recorded as they "
        "read on the day of the move, so renaming a room later does not "
        "rewrite what the register said at the time."
    ),
)
def read_movements(
    kind: str, record_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> list[MovementRead]:
    model, resource_type, name = _resolve_storable(kind)
    record = records.get_or_404(session, model, record_id, name)

    from app.core.permissions import can_view

    if not can_view(session, user, record, resource_type):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{name} not found")

    return [
        MovementRead.model_validate(row) for row in tree.history(session, resource_type, record_id)
    ]


@router.get(
    "/{kind}/{record_id}/location",
    response_model=LocationOfRecord,
    summary="Where an object is now",
    description=(
        "The current location, as one line. Falls back to the free-text "
        "location from before the hierarchy existed when nothing structured "
        "has been recorded yet — an honest 'we only know this much' rather "
        "than an empty field."
    ),
)
def read_location_of(
    kind: str, record_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> LocationOfRecord:
    model, resource_type, name = _resolve_storable(kind)
    record = records.get_or_404(session, model, record_id, name)

    from app.core.permissions import can_view

    if not can_view(session, user, record, resource_type):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{name} not found")

    location = (
        session.get(StorageLocation, record.storage_location_id)
        if record.storage_location_id
        else None
    )
    last_move = session.scalar(
        select(StorageMovement)
        .where(
            StorageMovement.resource_type == resource_type,
            StorageMovement.resource_id == record_id,
        )
        .order_by(StorageMovement.moved_at.desc(), StorageMovement.id.desc())
        .limit(1)
    )

    return LocationOfRecord(
        resource_type=resource_type,
        resource_id=record_id,
        location_id=location.id if location is not None else None,
        display_path=location.display_path if location is not None else None,
        legacy_location=getattr(record, "current_location", None) if location is None else None,
        moved_at=last_move.moved_at if last_move is not None else None,
    )
