"""The museum collection module.

Collections, accessioned objects, conservation history, exhibitions, loans and
environmental readings — everything an institution records about an object once
it has taken formal responsibility for it.

Permissions run through the **museum** module, independently of archaeology: a
collections manager needs no excavation access, and a field director needs no
access to the store's valuations.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import Numeric, Select, cast, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, CurrentUserOptional, DbSession, require_module
from app.core.permissions import (
    flat_can_edit,
    flat_visibility_filter,
    has_module_access,
)
from app.models.enums import (
    ActivityAction,
    ConditionState,
    Module,
    MovementReason,
    ObjectStatus,
    ResourceType,
)
from app.models.enums import (
    ModuleLevel as Level,
)
from app.models.museum import (
    Collection,
    ConservationRecord,
    EnvironmentalReading,
    Exhibition,
    ExhibitionItem,
    Loan,
    LoanItem,
    MuseumObject,
)
from app.models.storage import StorageLocation
from app.models.user import User
from app.schemas.common import Message, Page
from app.schemas.museum import (
    AccessionPreview,
    CollectionCreate,
    CollectionDetail,
    CollectionRead,
    CollectionUpdate,
    ConservationCreate,
    ConservationRead,
    ConservationUpdate,
    ExcursionSummary,
    ExhibitionCreate,
    ExhibitionItemCreate,
    ExhibitionItemRead,
    ExhibitionRead,
    ExhibitionUpdate,
    LoanCreate,
    LoanItemCreate,
    LoanItemRead,
    LoanRead,
    LoanUpdate,
    MuseumObjectCreate,
    MuseumObjectDetail,
    MuseumObjectRead,
    MuseumObjectSummary,
    MuseumObjectUpdate,
    ReadingCreate,
    ReadingRead,
)
from app.services import accession, activity, qrcodes, records
from app.services import storage_locations as tree

router = APIRouter(prefix="/museum", tags=["Museum"])

MODULE = Module.MUSEUM
#: An accessioned object is its own kind of record, not a find. They share a
#: storage hierarchy and a movement register, so the register has to be able to
#: tell them apart — a museum object filed as an ``artifact`` cannot be looked
#: up as itself.
RESOURCE = ResourceType.MUSEUM_OBJECT

#: Reading the collection needs viewer access to the museum module.
MuseumViewer = Annotated[User, Depends(require_module(MODULE, Level.VIEWER))]
#: Cataloguing needs contributor access.
MuseumContributor = Annotated[User, Depends(require_module(MODULE, Level.CONTRIBUTOR))]
#: Configuring a collection's numbering, or deleting anything, is a
#: supervisor's job — the numbering scheme is institutional, not personal.
MuseumSupervisor = Annotated[User, Depends(require_module(MODULE, Level.SUPERVISOR))]


def _museum_visible(user: User | None) -> bool:
    return has_module_access(user, MODULE, Level.VIEWER)


def _may_edit(session: DbSession, user: User | None, record: Any) -> bool:
    """Whether this caller may change a museum record.

    Museum records are not project-scoped, so the archaeology policy's project
    membership has nothing to say about them; the rule is the module level plus
    ownership. The policy itself lives in ``core.permissions`` so that the
    storage register, which also moves museum objects, reaches the same answer.
    """
    return flat_can_edit(user, record, MODULE)


def _visible_filter(user: User | None, model: Any) -> Any:
    """Rows this caller may read — the SQL mirror of :func:`_may_edit`'s sibling."""
    return flat_visibility_filter(user, model, MODULE)


def _require_readable(session: DbSession, user: User | None, record: Any, name: str) -> None:
    if _museum_visible(user) or getattr(record, "is_public", False):
        return
    raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{name} not found")


def _require_editable(session: DbSession, user: User | None, record: Any, name: str) -> None:
    _require_readable(session, user, record, name)
    if not _may_edit(session, user, record):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail=f"You may not edit this {name.lower()}"
        )


def _translate(error: accession.AccessionError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))


# --------------------------------------------------------------------------
# Collections
# --------------------------------------------------------------------------
def _collection_detail(
    session: DbSession, collection: Collection, user: User | None
) -> CollectionDetail:
    payload = CollectionDetail.model_validate(collection)
    payload.object_count = (
        session.scalar(
            select(func.count())
            .select_from(MuseumObject)
            .where(MuseumObject.collection_id == collection.id)
        )
        or 0
    )
    try:
        pattern = collection.accession_pattern or accession.DEFAULT_PATTERN
        payload.next_accession_number = accession.render(
            pattern,
            prefix=collection.accession_prefix,
            code=collection.code,
            year=date.today().year,
            sequence=collection.accession_sequence + 1,
        )
    except accession.AccessionError:  # pragma: no cover - pattern validated on write
        payload.next_accession_number = None

    payload.can_edit = _may_edit(session, user, collection)
    payload.can_delete = has_module_access(user, MODULE, Level.SUPERVISOR)
    return payload


@router.post(
    "/collections",
    response_model=CollectionDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a collection",
    description=(
        "A collection carries its own accession numbering. The platform "
        "imposes no format — declare the one this institution already uses.\n\n"
        "Placeholders: `{prefix}`, `{code}`, `{year}`, `{yy}`, `{seq}`. The "
        "sequence may be padded: `{seq:04d}`. So `{prefix}.{year}.{seq:04d}` "
        "produces `NM.2024.0001`."
    ),
)
def create_collection(
    payload: CollectionCreate, session: DbSession, request: Request, user: MuseumSupervisor
) -> CollectionDetail:
    existing = session.scalar(select(Collection).where(Collection.code == payload.code.upper()))
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"A collection with code {payload.code!r} exists"
        )

    if payload.accession_pattern:
        try:
            accession.validate_pattern(payload.accession_pattern)
        except accession.AccessionError as exc:
            raise _translate(exc) from exc

    data = payload.model_dump()
    data["code"] = data["code"].upper()
    collection = Collection(**data, owner_id=user.id)
    session.add(collection)
    session.flush()

    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_type=ResourceType.PROJECT,
        resource_id=collection.id,
        resource_label=collection.code,
        summary=f"Created collection {collection.code}",
        request=request,
    )
    session.flush()
    return _collection_detail(session, collection, user)


@router.get("/collections", response_model=Page[CollectionRead], summary="List collections")
def list_collections(
    session: DbSession,
    user: CurrentUserOptional,
    q: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CollectionRead]:
    statement = select(Collection).where(_visible_filter(user, Collection))
    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Collection.name).like(pattern),
                func.lower(Collection.code).like(pattern),
            )
        )
    statement = statement.order_by(Collection.code)
    rows, total = records.paginate(session, statement, limit, offset)
    return Page[CollectionRead](
        items=[CollectionRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/collections/{collection_id}", response_model=CollectionDetail, summary="Read a collection"
)
def read_collection(
    collection_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> CollectionDetail:
    collection = records.get_or_404(session, Collection, collection_id, "Collection")
    _require_readable(session, user, collection, "Collection")
    return _collection_detail(session, collection, user)


@router.patch(
    "/collections/{collection_id}", response_model=CollectionDetail, summary="Update a collection"
)
def update_collection(
    collection_id: uuid.UUID,
    payload: CollectionUpdate,
    session: DbSession,
    request: Request,
    user: MuseumSupervisor,
) -> CollectionDetail:
    collection = records.get_or_404(session, Collection, collection_id, "Collection")

    changes = payload.model_dump(exclude_unset=True)
    if changes.get("accession_pattern"):
        try:
            accession.validate_pattern(changes["accession_pattern"])
        except accession.AccessionError as exc:
            raise _translate(exc) from exc

    before = records.apply_changes(collection, changes)
    if before:
        activity.log(
            session,
            action=ActivityAction.UPDATE,
            user=user,
            resource_type=ResourceType.PROJECT,
            resource_id=collection.id,
            resource_label=collection.code,
            changes=activity.diff(before, {key: getattr(collection, key) for key in before}),
            summary=f"Updated collection {collection.code}",
            request=request,
        )
    session.flush()
    return _collection_detail(session, collection, user)


@router.get(
    "/collections/{collection_id}/next-number",
    response_model=AccessionPreview,
    summary="Preview the next accession number",
    description=(
        "What the next number in this collection's sequence would be, without "
        "issuing it. Pass `candidate` to check a number typed by hand: the "
        "answer says whether it fits the collection's pattern and whether it "
        "is still free."
    ),
)
def preview_number(
    collection_id: uuid.UUID,
    session: DbSession,
    user: MuseumViewer,
    candidate: Annotated[str | None, Query(max_length=120)] = None,
) -> AccessionPreview:
    collection = records.get_or_404(session, Collection, collection_id, "Collection")

    pattern = collection.accession_pattern or accession.DEFAULT_PATTERN
    preview = AccessionPreview(
        collection_id=collection.id,
        next_accession_number=accession.render(
            pattern,
            prefix=collection.accession_prefix,
            code=collection.code,
            year=date.today().year,
            sequence=collection.accession_sequence + 1,
        ),
        pattern=collection.accession_pattern,
    )

    if candidate:
        result = accession.check(collection, candidate)
        taken = session.scalar(
            select(func.count())
            .select_from(MuseumObject)
            .where(
                MuseumObject.collection_id == collection.id,
                MuseumObject.accession_number == candidate.strip(),
            )
        )
        preview.candidate = candidate.strip()
        preview.candidate_matches_pattern = result.matches
        preview.candidate_is_available = not taken
        if taken:
            preview.message = "That number is already used in this collection."
        elif not result.matches:
            preview.message = (
                f"{result.reason} It will be recorded as given and flagged as a legacy number."
                if not collection.enforce_pattern
                else f"{result.reason} This collection requires its pattern."
            )
    return preview


# --------------------------------------------------------------------------
# Objects
# --------------------------------------------------------------------------
def _object_detail(
    session: DbSession, obj: MuseumObject, user: User | None, *, warning: str | None = None
) -> MuseumObjectDetail:
    payload = MuseumObjectDetail.model_validate(obj)
    editable = _may_edit(session, user, obj)

    # A valuation on a record anyone can read is an invitation.
    if not editable:
        payload.valuation_amount = None
        payload.valuation_currency = None
        payload.valuation_date = None
        payload.insurance_reference = None

    collection = session.get(Collection, obj.collection_id)
    payload.collection_name = collection.name if collection else None

    if obj.storage_location_id:
        location = session.get(StorageLocation, obj.storage_location_id)
        payload.storage_path = location.display_path if location else None

    payload.treatment_count = (
        session.scalar(
            select(func.count())
            .select_from(ConservationRecord)
            .where(ConservationRecord.museum_object_id == obj.id)
        )
        or 0
    )
    payload.accession_warning = warning
    payload.can_edit = editable
    payload.can_delete = has_module_access(user, MODULE, Level.SUPERVISOR)
    return payload


@router.post(
    "/objects",
    response_model=MuseumObjectDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Catalogue an object",
    description=(
        "Leave `accession_number` blank to take the next number in the "
        "collection's sequence.\n\n"
        "A number that does not match the collection's pattern is **still "
        "recorded**, flagged as a legacy number, unless the collection is set "
        "to enforce its pattern. Collections are full of inherited oddities, "
        "and refusing to store them is how a migration stalls."
    ),
    responses={422: {"description": "The number is taken, or the collection enforces its pattern"}},
)
def create_object(
    payload: MuseumObjectCreate, session: DbSession, request: Request, user: MuseumContributor
) -> MuseumObjectDetail:
    collection = records.get_or_404(session, Collection, payload.collection_id, "Collection")

    try:
        number, is_legacy, warning = accession.assign(
            session,
            collection,
            requested=payload.accession_number,
            when=payload.acquisition_date,
        )
    except accession.AccessionError as exc:
        raise _translate(exc) from exc

    if payload.artifact_id is not None:
        _check_artifact_link(session, payload.artifact_id, exclude=None)

    data = payload.model_dump(exclude={"accession_number"})
    obj = MuseumObject(
        **data,
        accession_number=number,
        number_is_legacy=is_legacy,
        owner_id=user.id,
        review_status=records.initial_review_status(user, Module.MUSEUM),
    )
    session.add(obj)
    session.flush()

    # An object catalogued straight into a location gets a movement, so its
    # register begins where the object did rather than at its first move.
    if obj.storage_location_id is not None:
        tree.record_movement(
            session,
            resource_type=RESOURCE,
            resource_id=obj.id,
            resource_label=obj.accession_number,
            from_location=None,
            to_location=session.get(StorageLocation, obj.storage_location_id),
            reason=MovementReason.ACCESSION,
            user=user,
        )

    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=obj.id,
        resource_label=obj.accession_number,
        summary=f"Catalogued {obj.accession_number} — {obj.title}",
        request=request,
    )
    session.flush()
    return _object_detail(session, obj, user, warning=warning)


def _check_artifact_link(
    session: DbSession, artifact_id: uuid.UUID, *, exclude: uuid.UUID | None
) -> None:
    """One excavation record maps to at most one museum object.

    Two museum records claiming the same find would make "what happened to
    this artifact" unanswerable, which is the whole reason for the link.
    """
    from app.models.artifact import Artifact

    artifact = session.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That artifact does not exist"
        )

    statement = select(MuseumObject).where(MuseumObject.artifact_id == artifact_id)
    if exclude is not None:
        statement = statement.where(MuseumObject.id != exclude)
    existing = session.scalar(statement)
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"That artifact is already catalogued as {existing.accession_number}. "
                f"An excavation record maps to one museum object."
            ),
        )


def _object_search(
    session: Session,
    user: User | None,
    *,
    q: str | None = None,
    collection_id: uuid.UUID | None = None,
    object_status: ObjectStatus | None = None,
    condition: ConditionState | None = None,
    period_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    material: str | None = None,
    storage_location_id: uuid.UUID | None = None,
    within_location: uuid.UUID | None = None,
    has_artifact: bool | None = None,
    acquired_after: date | None = None,
    acquired_before: date | None = None,
    sort: str = "accession_number",
) -> Select[tuple[MuseumObject]]:
    """The catalogue search, as a statement.

    Shared rather than repeated: the list, the grid and the export have to
    agree about what a filter means, or the same search gives three different
    answers depending on which screen asked.
    """
    statement = select(MuseumObject).where(_visible_filter(user, MuseumObject))

    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(MuseumObject.accession_number).like(pattern),
                func.lower(MuseumObject.former_number).like(pattern),
                func.lower(MuseumObject.title).like(pattern),
                func.lower(MuseumObject.description).like(pattern),
                func.lower(MuseumObject.maker).like(pattern),
                func.lower(MuseumObject.culture).like(pattern),
            )
        )
    if collection_id is not None:
        statement = statement.where(MuseumObject.collection_id == collection_id)
    if object_status is not None:
        statement = statement.where(MuseumObject.status == object_status)
    if condition is not None:
        statement = statement.where(MuseumObject.condition == condition)
    if period_id is not None:
        statement = statement.where(MuseumObject.period_id == period_id)
    if category_id is not None:
        statement = statement.where(MuseumObject.category_id == category_id)
    if material:
        statement = statement.where(MuseumObject.materials.any(material))
    if storage_location_id is not None:
        statement = statement.where(MuseumObject.storage_location_id == storage_location_id)
    if within_location is not None:
        root = records.get_or_404(session, StorageLocation, within_location, "Storage location")
        ids = [root.id, *(child.id for child in tree.descendants(session, root))]
        statement = statement.where(MuseumObject.storage_location_id.in_(ids))
    if has_artifact is not None:
        statement = statement.where(
            MuseumObject.artifact_id.is_not(None)
            if has_artifact
            else MuseumObject.artifact_id.is_(None)
        )
    if acquired_after is not None:
        statement = statement.where(MuseumObject.acquisition_date >= acquired_after)
    if acquired_before is not None:
        statement = statement.where(MuseumObject.acquisition_date <= acquired_before)

    descending = sort.startswith("-")
    column = getattr(MuseumObject, sort.lstrip("-"))
    return statement.order_by(column.desc() if descending else column.asc(), MuseumObject.id)


# Every filter both list-shaped endpoints accept, named once. Two endpoints
# search the same catalogue; declaring the query twice is how they drift.
QSearch = Annotated[
    str | None, Query(description="Match accession number, title, description or maker")
]
QCollection = Annotated[uuid.UUID | None, Query()]
QStatus = Annotated[ObjectStatus | None, Query(alias="status")]
QCondition = Annotated[ConditionState | None, Query()]
QPeriod = Annotated[uuid.UUID | None, Query()]
QCategory = Annotated[uuid.UUID | None, Query()]
QMaterial = Annotated[str | None, Query()]
QLocation = Annotated[uuid.UUID | None, Query()]
QWithin = Annotated[uuid.UUID | None, Query(description="Anywhere beneath this storage location")]
QHasArtifact = Annotated[
    bool | None, Query(description="Only objects with (or without) an excavation record")
]
QAcquiredAfter = Annotated[date | None, Query()]
QAcquiredBefore = Annotated[date | None, Query()]
QSort = Annotated[str, Query(pattern="^-?(accession_number|title|created_at|acquisition_date)$")]


@router.get("/objects", response_model=Page[MuseumObjectSummary], summary="Search the collection")
def list_objects(
    session: DbSession,
    user: CurrentUserOptional,
    q: QSearch = None,
    collection_id: QCollection = None,
    object_status: QStatus = None,
    condition: QCondition = None,
    period_id: QPeriod = None,
    category_id: QCategory = None,
    material: QMaterial = None,
    storage_location_id: QLocation = None,
    within_location: QWithin = None,
    has_artifact: QHasArtifact = None,
    acquired_after: QAcquiredAfter = None,
    acquired_before: QAcquiredBefore = None,
    sort: QSort = "accession_number",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[MuseumObjectSummary]:
    statement = _object_search(
        session,
        user,
        q=q,
        collection_id=collection_id,
        object_status=object_status,
        condition=condition,
        period_id=period_id,
        category_id=category_id,
        material=material,
        storage_location_id=storage_location_id,
        within_location=within_location,
        has_artifact=has_artifact,
        acquired_after=acquired_after,
        acquired_before=acquired_before,
        sort=sort,
    )

    rows, total = records.paginate(session, statement, limit, offset)
    return Page[MuseumObjectSummary](
        items=[MuseumObjectSummary.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/objects/grid",
    response_model=Page[MuseumObjectRead],
    summary="Search the collection, whole records",
    description=(
        "The same search as `/objects`, returning every field rather than the "
        "handful the list view shows.\n\n"
        "The grid lets a cataloguer put any of the record's fields on screen "
        "as a column. Served from the summary, a column the summary happens "
        "not to carry would be a column of blanks — indistinguishable from a "
        "field nobody has filled in, and quietly wrong."
    ),
)
def list_objects_for_grid(
    session: DbSession,
    user: CurrentUserOptional,
    q: QSearch = None,
    collection_id: QCollection = None,
    object_status: QStatus = None,
    condition: QCondition = None,
    period_id: QPeriod = None,
    category_id: QCategory = None,
    material: QMaterial = None,
    storage_location_id: QLocation = None,
    within_location: QWithin = None,
    has_artifact: QHasArtifact = None,
    acquired_after: QAcquiredAfter = None,
    acquired_before: QAcquiredBefore = None,
    sort: QSort = "accession_number",
    # Lower than the list's ceiling on purpose: a grid row is the whole record,
    # so two hundred of them is a payload nobody asked for.
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[MuseumObjectRead]:
    statement = _object_search(
        session,
        user,
        q=q,
        collection_id=collection_id,
        object_status=object_status,
        condition=condition,
        period_id=period_id,
        category_id=category_id,
        material=material,
        storage_location_id=storage_location_id,
        within_location=within_location,
        has_artifact=has_artifact,
        acquired_after=acquired_after,
        acquired_before=acquired_before,
        sort=sort,
    )

    rows, total = records.paginate(session, statement, limit, offset)
    return Page[MuseumObjectRead](
        items=[MuseumObjectRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/objects/export.csv",
    summary="Download the catalogue as a spreadsheet",
    description=(
        "The same records the grid shows, as CSV — openable in Excel, "
        "LibreOffice or Numbers.\n\n"
        "`columns` selects which fields to include, comma-separated, in the "
        "order given. Omit it for the whole record.\n\n"
        "The file is written with a byte-order mark, because Excel on Windows "
        "otherwise reads UTF-8 as its own legacy encoding and turns every "
        "diacritic in a site name into mojibake — which is precisely the data "
        "an archaeological catalogue is full of.\n\n"
        "What comes out can be edited and imported back through "
        "`/imports`, so a correction pass in a spreadsheet is a round trip "
        "rather than a dead end."
    ),
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "The catalogue"}},
)
def export_objects_csv(
    session: DbSession,
    user: CurrentUserOptional,
    q: QSearch = None,
    collection_id: QCollection = None,
    object_status: QStatus = None,
    condition: QCondition = None,
    period_id: QPeriod = None,
    category_id: QCategory = None,
    material: QMaterial = None,
    storage_location_id: QLocation = None,
    within_location: QWithin = None,
    has_artifact: QHasArtifact = None,
    acquired_after: QAcquiredAfter = None,
    acquired_before: QAcquiredBefore = None,
    sort: QSort = "accession_number",
    columns: Annotated[
        str | None, Query(description="Field names, comma-separated, in order")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=20_000)] = 5_000,
) -> Response:
    from app.services import forms

    layout = forms.get_layout("museum_object")
    known = forms.field_index(layout) if layout else {}

    chosen = [name.strip() for name in (columns or "").split(",") if name.strip()]
    wanted = [name for name in chosen if name in known] or list(known)

    # The same search the grid ran. Exporting "what I am looking at" is the
    # whole point, and it fails the moment the two disagree about a filter.
    statement = _object_search(
        session,
        user,
        q=q,
        collection_id=collection_id,
        object_status=object_status,
        condition=condition,
        period_id=period_id,
        category_id=category_id,
        material=material,
        storage_location_id=storage_location_id,
        within_location=within_location,
        has_artifact=has_artifact,
        acquired_after=acquired_after,
        acquired_before=acquired_before,
        sort=sort,
    ).limit(limit)

    rows = session.scalars(statement).all()

    # Value lists are resolved to their labels. A column of UUIDs is not a
    # spreadsheet somebody can read, correct, and hand back.
    lookups = forms.value_lists(session, layout.value_lists) if layout else {}
    by_value = {
        name: {option["value"]: option["label"] for option in options}
        for name, options in lookups.items()
    }

    def as_text(field: forms.FormField, value: object) -> str:
        """One value, written the way the grid shows it."""
        if value is None:
            return ""
        if hasattr(value, "value"):  # an enum
            value = value.value
        # Multi-valued fields resolve item by item. Doing the join first is the
        # obvious shortcut and the wrong one: a materials column then leaves a
        # row of raw identifiers where the grid shows "Bronze, Bone", and the
        # file is neither readable nor correctable.
        if isinstance(value, list):
            return "; ".join(as_text(field, item) for item in value)
        if field.value_list:
            return by_value.get(field.value_list, {}).get(str(value), str(value))
        return str(value)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([known[name].label for name in wanted])

    for row in rows:
        writer.writerow([as_text(known[name], getattr(row, name, None)) for name in wanted])

    # utf-8-sig, not utf-8. See the endpoint description.
    payload = buffer.getvalue().encode("utf-8-sig")
    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="catalogue.csv"'},
    )


@router.get("/objects/{object_id}", response_model=MuseumObjectDetail, summary="Read an object")
def read_object(
    object_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> MuseumObjectDetail:
    obj = records.get_or_404(session, MuseumObject, object_id, "Object")
    _require_readable(session, user, obj, "Object")
    return _object_detail(session, obj, user)


@router.get(
    "/objects/by-number/{accession_number:path}",
    response_model=MuseumObjectDetail,
    summary="Read an object by its accession number",
    description=(
        "The number is how a cataloguer refers to an object, so it is a way "
        "in. Give `collection_id` when the same number exists in more than "
        "one collection."
    ),
)
def read_object_by_number(
    accession_number: str,
    session: DbSession,
    user: CurrentUserOptional,
    collection_id: Annotated[uuid.UUID | None, Query()] = None,
) -> MuseumObjectDetail:
    statement = select(MuseumObject).where(MuseumObject.accession_number == accession_number)
    if collection_id is not None:
        statement = statement.where(MuseumObject.collection_id == collection_id)

    found = list(session.scalars(statement).all())
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Object not found")
    if len(found) > 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"{accession_number!r} exists in {len(found)} collections. "
                f"Add collection_id to say which."
            ),
        )

    obj = found[0]
    _require_readable(session, user, obj, "Object")
    return _object_detail(session, obj, user)


@router.patch("/objects/{object_id}", response_model=MuseumObjectDetail, summary="Update an object")
def update_object(
    object_id: uuid.UUID,
    payload: MuseumObjectUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> MuseumObjectDetail:
    obj = records.get_or_404(session, MuseumObject, object_id, "Object")
    _require_editable(session, user, obj, "Object")

    changes = payload.model_dump(exclude_unset=True)
    if changes.get("artifact_id") is not None:
        _check_artifact_link(session, changes["artifact_id"], exclude=obj.id)

    before = records.apply_changes(obj, changes)
    records.on_updated(session, obj, RESOURCE, before=before, user=user, request=request)
    session.flush()
    return _object_detail(session, obj, user)


@router.delete("/objects/{object_id}", response_model=Message, summary="Delete an object")
def delete_object(
    object_id: uuid.UUID, session: DbSession, request: Request, user: MuseumSupervisor
) -> Message:
    obj = records.get_or_404(session, MuseumObject, object_id, "Object")

    label = obj.accession_number
    records.on_deleted(session, obj, RESOURCE, user=user, request=request, label=label)
    session.delete(obj)
    return Message(
        detail=(
            f"Object {label!r} deleted. Its conservation history went with it; "
            f"deaccessioning rather than deleting keeps the record."
        )
    )


# --------------------------------------------------------------------------
# Conservation
# --------------------------------------------------------------------------
@router.post(
    "/objects/{object_id}/conservation",
    response_model=ConservationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record an examination or treatment",
    description=(
        "Appends to the object's care history. By default the object's own "
        "condition is updated to `condition_after`, which is almost always "
        "what is meant — set `update_object_condition` to false when recording "
        "a historical treatment out of order."
    ),
)
def add_conservation(
    object_id: uuid.UUID,
    payload: ConservationCreate,
    session: DbSession,
    request: Request,
    user: MuseumContributor,
) -> ConservationRead:
    obj = records.get_or_404(session, MuseumObject, object_id, "Object")
    _require_editable(session, user, obj, "Object")

    data = payload.model_dump(exclude={"update_object_condition"})
    record = ConservationRecord(**data, museum_object_id=obj.id, owner_id=user.id)
    session.add(record)
    session.flush()

    if payload.update_object_condition and payload.condition_after is not None:
        obj.condition = payload.condition_after
        obj.last_checked_on = payload.performed_on
        obj.last_checked_by_id = user.id
        session.add(obj)

    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=obj.id,
        resource_label=obj.accession_number,
        summary=f"{payload.treatment_type.value.capitalize()} recorded for {obj.accession_number}",
        request=request,
    )
    session.flush()
    return ConservationRead.model_validate(record)


@router.get(
    "/objects/{object_id}/conservation",
    response_model=list[ConservationRead],
    summary="An object's care history",
    description="Oldest first, which is the order a conservator reads it in.",
)
def read_conservation(
    object_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> list[ConservationRead]:
    obj = records.get_or_404(session, MuseumObject, object_id, "Object")
    _require_readable(session, user, obj, "Object")

    rows = session.scalars(
        select(ConservationRecord)
        .where(ConservationRecord.museum_object_id == obj.id)
        .order_by(ConservationRecord.performed_on.asc(), ConservationRecord.id.asc())
    ).all()
    return [ConservationRead.model_validate(row) for row in rows]


@router.patch(
    "/conservation/{record_id}",
    response_model=ConservationRead,
    summary="Correct a conservation record",
)
def update_conservation(
    record_id: uuid.UUID,
    payload: ConservationUpdate,
    session: DbSession,
    user: CurrentUser,
) -> ConservationRead:
    record = records.get_or_404(session, ConservationRecord, record_id, "Conservation record")
    obj = session.get(MuseumObject, record.museum_object_id)
    _require_editable(session, user, obj, "Object")

    records.apply_changes(record, payload.model_dump(exclude_unset=True))
    session.flush()
    return ConservationRead.model_validate(record)


@router.get(
    "/conservation/due",
    response_model=Page[ConservationRead],
    summary="Treatments due for review",
    description=(
        "Records whose `next_review_on` has arrived. The list a conservator works from on a Monday."
    ),
)
def conservation_due(
    session: DbSession,
    user: MuseumViewer,
    before: Annotated[date | None, Query(description="Defaults to today")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ConservationRead]:
    cutoff = before or date.today()
    statement = (
        select(ConservationRecord)
        .where(
            ConservationRecord.next_review_on.is_not(None),
            ConservationRecord.next_review_on <= cutoff,
        )
        .order_by(ConservationRecord.next_review_on.asc(), ConservationRecord.id.asc())
    )
    rows, total = records.paginate(session, statement, limit, offset)
    return Page[ConservationRead](
        items=[ConservationRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# --------------------------------------------------------------------------
# Exhibitions
# --------------------------------------------------------------------------
def _exhibition_read(session: DbSession, exhibition: Exhibition) -> ExhibitionRead:
    payload = ExhibitionRead.model_validate(exhibition)
    payload.item_count = (
        session.scalar(
            select(func.count())
            .select_from(ExhibitionItem)
            .where(ExhibitionItem.exhibition_id == exhibition.id)
        )
        or 0
    )
    return payload


@router.post(
    "/exhibitions",
    response_model=ExhibitionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an exhibition",
)
def create_exhibition(
    payload: ExhibitionCreate, session: DbSession, request: Request, user: MuseumContributor
) -> ExhibitionRead:
    exhibition = Exhibition(**payload.model_dump(), owner_id=user.id)
    session.add(exhibition)
    session.flush()

    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_type=ResourceType.PROJECT,
        resource_id=exhibition.id,
        resource_label=exhibition.title,
        summary=f"Created exhibition {exhibition.title!r}",
        request=request,
    )
    session.flush()
    return _exhibition_read(session, exhibition)


@router.get("/exhibitions", response_model=Page[ExhibitionRead], summary="List exhibitions")
def list_exhibitions(
    session: DbSession,
    user: CurrentUserOptional,
    q: Annotated[str | None, Query()] = None,
    exhibition_status: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ExhibitionRead]:
    statement = select(Exhibition).where(_visible_filter(user, Exhibition))
    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Exhibition.title).like(pattern),
                func.lower(Exhibition.venue).like(pattern),
            )
        )
    if exhibition_status:
        statement = statement.where(Exhibition.status == exhibition_status)

    statement = statement.order_by(Exhibition.opens_on.desc().nullslast(), Exhibition.title)
    rows, total = records.paginate(session, statement, limit, offset)
    return Page[ExhibitionRead](
        items=[_exhibition_read(session, row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/exhibitions/{exhibition_id}", response_model=ExhibitionRead, summary="Read an exhibition"
)
def read_exhibition(
    exhibition_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> ExhibitionRead:
    exhibition = records.get_or_404(session, Exhibition, exhibition_id, "Exhibition")
    _require_readable(session, user, exhibition, "Exhibition")
    return _exhibition_read(session, exhibition)


@router.patch(
    "/exhibitions/{exhibition_id}", response_model=ExhibitionRead, summary="Update an exhibition"
)
def update_exhibition(
    exhibition_id: uuid.UUID,
    payload: ExhibitionUpdate,
    session: DbSession,
    user: CurrentUser,
) -> ExhibitionRead:
    exhibition = records.get_or_404(session, Exhibition, exhibition_id, "Exhibition")
    _require_editable(session, user, exhibition, "Exhibition")
    records.apply_changes(exhibition, payload.model_dump(exclude_unset=True))
    session.flush()
    return _exhibition_read(session, exhibition)


@router.post(
    "/exhibitions/{exhibition_id}/items",
    response_model=ExhibitionItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Put an object in an exhibition",
)
def add_exhibition_item(
    exhibition_id: uuid.UUID,
    payload: ExhibitionItemCreate,
    session: DbSession,
    user: MuseumContributor,
) -> ExhibitionItemRead:
    exhibition = records.get_or_404(session, Exhibition, exhibition_id, "Exhibition")
    _require_editable(session, user, exhibition, "Exhibition")
    obj = records.get_or_404(session, MuseumObject, payload.museum_object_id, "Object")

    existing = session.scalar(
        select(ExhibitionItem).where(
            ExhibitionItem.exhibition_id == exhibition.id,
            ExhibitionItem.museum_object_id == obj.id,
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"{obj.accession_number} is already in this exhibition"
        )

    item = ExhibitionItem(**payload.model_dump(), exhibition_id=exhibition.id)
    session.add(item)
    session.flush()

    return ExhibitionItemRead(
        id=item.id,
        exhibition_id=exhibition.id,
        museum_object_id=obj.id,
        accession_number=obj.accession_number,
        object_title=obj.title,
        label_text=item.label_text,
        case_number=item.case_number,
        display_order=item.display_order,
        notes=item.notes,
    )


@router.get(
    "/exhibitions/{exhibition_id}/items",
    response_model=list[ExhibitionItemRead],
    summary="What is in an exhibition",
)
def read_exhibition_items(
    exhibition_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> list[ExhibitionItemRead]:
    exhibition = records.get_or_404(session, Exhibition, exhibition_id, "Exhibition")
    _require_readable(session, user, exhibition, "Exhibition")

    rows = session.execute(
        select(ExhibitionItem, MuseumObject)
        .join(MuseumObject, MuseumObject.id == ExhibitionItem.museum_object_id)
        .where(ExhibitionItem.exhibition_id == exhibition.id)
        .order_by(ExhibitionItem.display_order, MuseumObject.accession_number)
    ).all()

    return [
        ExhibitionItemRead(
            id=item.id,
            exhibition_id=item.exhibition_id,
            museum_object_id=item.museum_object_id,
            accession_number=obj.accession_number,
            object_title=obj.title,
            label_text=item.label_text,
            case_number=item.case_number,
            display_order=item.display_order,
            notes=item.notes,
        )
        for item, obj in rows
    ]


@router.get(
    "/objects/{object_id}/exhibitions",
    response_model=list[ExhibitionRead],
    summary="Where an object has been shown",
)
def object_exhibitions(
    object_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> list[ExhibitionRead]:
    obj = records.get_or_404(session, MuseumObject, object_id, "Object")
    _require_readable(session, user, obj, "Object")

    rows = session.scalars(
        select(Exhibition)
        .join(ExhibitionItem, ExhibitionItem.exhibition_id == Exhibition.id)
        .where(ExhibitionItem.museum_object_id == obj.id)
        .order_by(Exhibition.opens_on.desc().nullslast())
    ).all()
    return [_exhibition_read(session, row) for row in rows]


@router.delete(
    "/exhibitions/{exhibition_id}/items/{item_id}",
    response_model=Message,
    summary="Take an object out of an exhibition",
)
def remove_exhibition_item(
    exhibition_id: uuid.UUID, item_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> Message:
    exhibition = records.get_or_404(session, Exhibition, exhibition_id, "Exhibition")
    _require_editable(session, user, exhibition, "Exhibition")

    item = session.get(ExhibitionItem, item_id)
    if item is None or item.exhibition_id != exhibition.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Item not found in this exhibition")

    session.delete(item)
    return Message(detail="Object removed from the exhibition")


# --------------------------------------------------------------------------
# Loans
# --------------------------------------------------------------------------
def _loan_read(session: DbSession, loan: Loan) -> LoanRead:
    payload = LoanRead.model_validate(loan)
    payload.item_count = (
        session.scalar(
            select(func.count()).select_from(LoanItem).where(LoanItem.loan_id == loan.id)
        )
        or 0
    )
    return payload


@router.post(
    "/loans",
    response_model=LoanRead,
    status_code=status.HTTP_201_CREATED,
    summary="Open a loan",
    description=(
        "Outgoing (we lend) or incoming (we borrow). Both are supported "
        "because they are different paperwork with different obligations, and "
        "an institution that only lends today may borrow next season."
    ),
)
def create_loan(
    payload: LoanCreate, session: DbSession, request: Request, user: MuseumContributor
) -> LoanRead:
    existing = session.scalar(select(Loan).where(Loan.reference == payload.reference))
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"Loan reference {payload.reference!r} is in use"
        )

    loan = Loan(**payload.model_dump(), owner_id=user.id)
    session.add(loan)
    session.flush()

    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_type=ResourceType.PROJECT,
        resource_id=loan.id,
        resource_label=loan.reference,
        summary=f"Opened {loan.direction.value} loan {loan.reference}",
        request=request,
    )
    session.flush()
    return _loan_read(session, loan)


@router.get("/loans", response_model=Page[LoanRead], summary="List loans")
def list_loans(
    session: DbSession,
    user: MuseumViewer,
    direction: Annotated[str | None, Query()] = None,
    loan_status: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[LoanRead]:
    statement = select(Loan)
    if direction:
        statement = statement.where(Loan.direction == direction)
    if loan_status:
        statement = statement.where(Loan.status == loan_status)

    statement = statement.order_by(Loan.starts_on.desc().nullslast(), Loan.reference)
    rows, total = records.paginate(session, statement, limit, offset)
    return Page[LoanRead](
        items=[_loan_read(session, row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.get("/loans/{loan_id}", response_model=LoanRead, summary="Read a loan")
def read_loan(loan_id: uuid.UUID, session: DbSession, user: MuseumViewer) -> LoanRead:
    loan = records.get_or_404(session, Loan, loan_id, "Loan")
    return _loan_read(session, loan)


@router.patch("/loans/{loan_id}", response_model=LoanRead, summary="Update a loan")
def update_loan(
    loan_id: uuid.UUID, payload: LoanUpdate, session: DbSession, user: MuseumContributor
) -> LoanRead:
    loan = records.get_or_404(session, Loan, loan_id, "Loan")
    _require_editable(session, user, loan, "Loan")

    changes = payload.model_dump(exclude_unset=True)
    records.apply_changes(loan, changes)

    # An outgoing loan moving to "on loan" is the objects leaving the building,
    # and their own status should say so without anybody editing each one.
    if changes.get("status") is not None and loan.direction.value == "outgoing":
        _sync_loan_object_status(session, loan)

    session.flush()
    return _loan_read(session, loan)


def _sync_loan_object_status(session: DbSession, loan: Loan) -> None:
    items = session.scalars(select(LoanItem).where(LoanItem.loan_id == loan.id)).all()
    for item in items:
        if item.museum_object_id is None:
            continue
        obj = session.get(MuseumObject, item.museum_object_id)
        if obj is None:
            continue
        if loan.status.value == "on_loan":
            obj.status = ObjectStatus.ON_LOAN
        elif loan.status.value == "returned" and obj.status is ObjectStatus.ON_LOAN:
            obj.status = ObjectStatus.ACCESSIONED
        session.add(obj)


@router.post(
    "/loans/{loan_id}/items",
    response_model=LoanItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add an object to a loan",
)
def add_loan_item(
    loan_id: uuid.UUID, payload: LoanItemCreate, session: DbSession, user: MuseumContributor
) -> LoanItemRead:
    loan = records.get_or_404(session, Loan, loan_id, "Loan")
    _require_editable(session, user, loan, "Loan")

    obj = None
    if payload.museum_object_id is not None:
        obj = records.get_or_404(session, MuseumObject, payload.museum_object_id, "Object")

    item = LoanItem(**payload.model_dump(), loan_id=loan.id)
    session.add(item)
    session.flush()

    return LoanItemRead(
        id=item.id,
        loan_id=loan.id,
        museum_object_id=item.museum_object_id,
        accession_number=obj.accession_number if obj else None,
        object_title=obj.title if obj else None,
        external_description=item.external_description,
        condition_out=item.condition_out,
        condition_in=item.condition_in,
        condition_note=item.condition_note,
        insurance_value=item.insurance_value,
    )


@router.get(
    "/loans/{loan_id}/items", response_model=list[LoanItemRead], summary="What is on a loan"
)
def read_loan_items(
    loan_id: uuid.UUID, session: DbSession, user: MuseumViewer
) -> list[LoanItemRead]:
    loan = records.get_or_404(session, Loan, loan_id, "Loan")

    rows = session.scalars(select(LoanItem).where(LoanItem.loan_id == loan.id)).all()
    result: list[LoanItemRead] = []
    for item in rows:
        obj = session.get(MuseumObject, item.museum_object_id) if item.museum_object_id else None
        result.append(
            LoanItemRead(
                id=item.id,
                loan_id=loan.id,
                museum_object_id=item.museum_object_id,
                accession_number=obj.accession_number if obj else None,
                object_title=obj.title if obj else None,
                external_description=item.external_description,
                condition_out=item.condition_out,
                condition_in=item.condition_in,
                condition_note=item.condition_note,
                insurance_value=item.insurance_value,
            )
        )
    return result


# --------------------------------------------------------------------------
# Environmental readings
# --------------------------------------------------------------------------
@router.post(
    "/readings",
    response_model=ReadingRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record environmental conditions",
    description=(
        "One measurement in one place. Storage locations carry *target* "
        "conditions; this is what was actually measured, and the two together "
        "are what proves conditions were held — to a conservator, an auditor "
        "or a lender."
    ),
)
def add_reading(payload: ReadingCreate, session: DbSession, user: MuseumContributor) -> ReadingRead:
    location = records.get_or_404(session, StorageLocation, payload.location_id, "Storage location")

    reading = EnvironmentalReading(
        **payload.model_dump(exclude={"recorded_at"}),
        recorded_at=payload.recorded_at or datetime.now(UTC),
        recorded_by_id=user.id,
    )
    reading.location_id = location.id
    session.add(reading)
    session.flush()
    return ReadingRead.model_validate(reading)


@router.get(
    "/locations/{location_id}/readings",
    response_model=Page[ReadingRead],
    summary="Readings for a location",
)
def read_readings(
    location_id: uuid.UUID,
    session: DbSession,
    user: MuseumViewer,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ReadingRead]:
    records.get_or_404(session, StorageLocation, location_id, "Storage location")

    statement = select(EnvironmentalReading).where(EnvironmentalReading.location_id == location_id)
    if since is not None:
        statement = statement.where(EnvironmentalReading.recorded_at >= since)
    if until is not None:
        statement = statement.where(EnvironmentalReading.recorded_at <= until)

    statement = statement.order_by(
        EnvironmentalReading.recorded_at.desc(), EnvironmentalReading.id.desc()
    )
    rows, total = records.paginate(session, statement, limit, offset)
    return Page[ReadingRead](
        items=[ReadingRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/locations/{location_id}/conditions",
    response_model=ExcursionSummary,
    summary="How a location has actually performed",
    description=(
        "Readings measured against the location's targets: range, mean, and "
        "how many readings fell outside tolerance. A target with no readings "
        "cannot be shown to have been met; readings with no target cannot be "
        "judged. This puts the two together."
    ),
)
def read_conditions(
    location_id: uuid.UUID,
    session: DbSession,
    user: MuseumViewer,
    since: Annotated[datetime | None, Query()] = None,
    tolerance_temperature_c: Annotated[float, Query(ge=0, le=20)] = 2.0,
    tolerance_humidity: Annotated[float, Query(ge=0, le=50)] = 5.0,
) -> ExcursionSummary:
    location = records.get_or_404(session, StorageLocation, location_id, "Storage location")

    conditions = [EnvironmentalReading.location_id == location_id]
    if since is not None:
        conditions.append(EnvironmentalReading.recorded_at >= since)

    aggregate = session.execute(
        select(
            func.count(),
            func.min(EnvironmentalReading.recorded_at),
            func.max(EnvironmentalReading.recorded_at),
            func.min(EnvironmentalReading.temperature_c),
            func.max(EnvironmentalReading.temperature_c),
            func.avg(EnvironmentalReading.temperature_c),
            func.min(EnvironmentalReading.relative_humidity),
            func.max(EnvironmentalReading.relative_humidity),
            func.avg(EnvironmentalReading.relative_humidity),
        ).where(*conditions)
    ).one()

    summary = ExcursionSummary(
        location_id=location.id,
        display_path=location.display_path,
        target_temperature_c=float(location.target_temperature_c)
        if location.target_temperature_c is not None
        else None,
        target_humidity_percent=float(location.target_humidity_percent)
        if location.target_humidity_percent is not None
        else None,
        reading_count=aggregate[0] or 0,
        first_reading_at=aggregate[1],
        last_reading_at=aggregate[2],
        min_temperature_c=_as_float(aggregate[3]),
        max_temperature_c=_as_float(aggregate[4]),
        mean_temperature_c=_as_float(aggregate[5], places=2),
        min_humidity=_as_float(aggregate[6]),
        max_humidity=_as_float(aggregate[7]),
        mean_humidity=_as_float(aggregate[8], places=2),
        tolerance_temperature_c=tolerance_temperature_c,
        tolerance_humidity=tolerance_humidity,
    )

    # Excursions are only meaningful against a target, so a location with none
    # reports zero rather than an arbitrary judgement.
    if location.target_temperature_c is not None:
        target = cast(location.target_temperature_c, Numeric)
        summary.temperature_excursions = (
            session.scalar(
                select(func.count())
                .select_from(EnvironmentalReading)
                .where(
                    *conditions,
                    EnvironmentalReading.temperature_c.is_not(None),
                    func.abs(EnvironmentalReading.temperature_c - target) > tolerance_temperature_c,
                )
            )
            or 0
        )
    if location.target_humidity_percent is not None:
        target = cast(location.target_humidity_percent, Numeric)
        summary.humidity_excursions = (
            session.scalar(
                select(func.count())
                .select_from(EnvironmentalReading)
                .where(
                    *conditions,
                    EnvironmentalReading.relative_humidity.is_not(None),
                    func.abs(EnvironmentalReading.relative_humidity - target) > tolerance_humidity,
                )
            )
            or 0
        )

    return summary


def _as_float(value: Any, *, places: int | None = None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return round(number, places) if places is not None else number


# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------
@router.get(
    "/objects/{object_id}/qr.png",
    summary="QR code image for an object label",
    description=(
        "A PNG for the label that goes in the box with the object. Scanning it "
        "opens the object's record, subject to the same permissions as the "
        "record itself — a label reveals nothing the scanner could not already "
        "see.\n\n"
        "`size` is the pixel size of each module; larger prints more crisply."
    ),
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "The QR code"}},
)
def read_object_qr(
    object_id: uuid.UUID,
    session: DbSession,
    user: CurrentUserOptional,
    size: Annotated[int, Query(ge=2, le=40, description="Pixels per module")] = 10,
    for_label: Annotated[bool, Query(description="Higher error correction, for print")] = True,
) -> Response:
    obj = records.get_or_404(session, MuseumObject, object_id, "Object")
    _require_readable(session, user, obj, "Object")

    png = qrcodes.render_for_record(RESOURCE, obj.public_token, box_size=size, for_label=for_label)
    return Response(
        content=png,
        media_type="image/png",
        headers={
            # The token never changes, so the image never changes.
            "Cache-Control": "public, max-age=86400",
            "Content-Disposition": f'inline; filename="object-{object_id}.png"',
        },
    )
