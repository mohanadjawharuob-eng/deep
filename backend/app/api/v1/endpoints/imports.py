"""Importing a catalogue from a spreadsheet.

Four steps, and the separation between them is the feature:

``POST /imports``
    Upload the file. It is read, its columns reported with sample values, and a
    mapping *suggested*. Nothing is written to the catalogue.

``PATCH /imports/{id}``
    A person confirms or corrects the mapping, column by column, and sets any
    values that apply to every row. This is the verification the whole design
    exists for: the platform never decides for itself that the column headed
    "Date" is the acquisition date.

``POST /imports/{id}/preview``
    Every row is validated against the approved mapping and the outcome
    reported — what would be created, what would fail, and why, by row number
    as it appears in Excel. Still nothing written.

``POST /imports/{id}/commit``
    The rows that pass are created. The identifiers are kept on the batch, so
    the run can be undone with ``DELETE /imports/{id}/records``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.core.permissions import has_module_access
from app.models.artifact import Artifact
from app.models.audit import Revision
from app.models.context import ExcavationContext
from app.models.enums import ActivityAction, ImportStatus, Module, ResourceType
from app.models.enums import ModuleLevel as Level
from app.models.imports import ImportBatch
from app.models.museum import Collection, MuseumObject
from app.models.project import Project
from app.models.site import Site
from app.models.user import User
from app.schemas.common import Message, Page
from app.schemas.imports import (
    ImportBatchDetail,
    ImportBatchSummary,
    ImportColumn,
    ImportMappingUpdate,
    ImportPreview,
    ImportRowResult,
    ShelfUpdate,
)
from app.services import accession, activity, importer, records, sheets, spreadsheets
from app.services.storage import storage

router = APIRouter(prefix="/imports", tags=["Import"])

#: Which record types can be imported, and into which module.
#:
#: Importing writes records into a module, so it is permissioned by that
#: module — not by a separate "may import" right, which would be a way around
#: the module ceiling. That is also why the permission is checked per batch
#: rather than by one dependency on the router: a museum supervisor must not be
#: able to write four thousand contexts into an excavation they have no access
#: to, and a single ``require_module(Module.MUSEUM, …)`` on every endpoint
#: would let them.
SUPPORTED: dict[str, Module] = {
    "museum_object": Module.MUSEUM,
    "equipment": Module.INVENTORY,
    "consumable": Module.INVENTORY,
    "site": Module.ARCHAEOLOGY,
    "excavation_context": Module.ARCHAEOLOGY,
    "artifact": Module.ARCHAEOLOGY,
}

#: What each imported record needs before a row can become a record, and which
#: field carries it. Set once for the whole file on the verification screen, or
#: mapped from a column when the sheet covers several sites.
PARENT_OF: dict[str, tuple[str, str]] = {
    "site": ("project_id", "project"),
    "excavation_context": ("site_id", "site"),
    "artifact": ("site_id", "site"),
    "museum_object": ("collection_id", "collection"),
}

#: Anybody signed in may hold an import batch; what they may *do* with it is
#: decided per record type by :func:`_require_import_access`, which every
#: endpoint calls. Gating the router on one module instead would either lock
#: out somebody who legitimately imports into another, or let a supervisor in
#: one module write into a second — and the second failure is silent.
Importer = CurrentUser


def _check_record_type(record_type: str) -> Module:
    module = SUPPORTED.get(record_type)
    if module is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{record_type!r} cannot be imported from a spreadsheet. "
                f"Available: {', '.join(sorted(SUPPORTED))}."
            ),
        )
    return module


def _require_import_access(user: User, record_type: str) -> Module:
    """Supervisor in the module this file writes into.

    Importing creates records in bulk and is hard to undo by hand, so it is a
    supervisor's job rather than a contributor's — and it is the *destination*
    module that decides, not whichever module the person happens to run.
    """
    module = _check_record_type(record_type)
    if not has_module_access(user, module, Level.SUPERVISOR):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=(
                f"Importing {record_type.replace('_', ' ')} records needs supervisor "
                f"access to the {module.value.replace('_', ' ')} module."
            ),
        )
    return module


def _get_batch(session: DbSession, batch_id: uuid.UUID, user: User) -> ImportBatch:
    batch = records.get_or_404(session, ImportBatch, batch_id, "Import")
    # An import batch holds a file somebody uploaded and a mapping they
    # approved; it is theirs, not the module's.
    module = SUPPORTED.get(batch.record_type, Module.MUSEUM)
    if batch.owner_id != user.id and not has_module_access(user, module, Level.ADMINISTRATOR):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Import not found")
    _require_import_access(user, batch.record_type)
    return batch


def _load_sheet(batch: ImportBatch) -> spreadsheets.Sheet:
    """Re-read the stored file. Cheap enough, and means no parsed copy to stale."""
    try:
        with storage.open(batch.stored_path) as handle:
            data = handle.read()
        return spreadsheets.read(
            data,
            filename=batch.filename,
            sheet_name=batch.sheet_name,
            header_row=batch.header_row,
        )
    except spreadsheets.SpreadsheetError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


def _detail(session: DbSession, batch: ImportBatch, *, sheet: spreadsheets.Sheet | None = None):
    sheet = sheet or _load_sheet(batch)
    reports = spreadsheets.describe_columns(batch.record_type, sheet, batch.mapping or None)

    payload = ImportBatchDetail.model_validate(batch)
    payload.columns_detail = [
        ImportColumn(
            column=report.column,
            suggested_field=report.suggested_field,
            field_label=report.field_label,
            field_kind=report.field_kind,
            samples=[str(value) for value in report.samples],
            filled=report.filled,
            total=report.total,
        )
        for report in reports
    ]
    payload.unmapped_required = spreadsheets.unmapped_required(
        batch.record_type, {report.column: report.suggested_field for report in reports}
    )
    payload.available_fields = _available_fields(batch.record_type, session)
    return payload


def _available_fields(record_type: str, session: DbSession | None = None) -> list[dict[str, Any]]:
    """Every field a column may be mapped onto, for the verification screen."""
    from app.services import forms

    layout = forms.get_layout(record_type)
    if layout is None:
        return []
    # An institution's own fields are mappable too - otherwise a column the
    # field was invented for cannot be imported into it.
    if session is not None:
        layout = forms.with_custom(session, layout)
    return [
        {
            "name": name,
            "label": item.label,
            "kind": item.kind,
            "required": item.required,
            "help": item.help,
            "value_list": item.value_list,
        }
        for name, item in forms.field_index(layout).items()
        if not item.read_only
    ]


# --------------------------------------------------------------------------
# 1. Upload and analyse
# --------------------------------------------------------------------------
@router.post(
    "",
    response_model=ImportBatchDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a spreadsheet and see what is in it",
    description=(
        "Reads the file and reports every column: its heading, what it "
        "contains, how many rows have a value, and a **suggested** platform "
        "field.\n\n"
        "The suggestion is a convenience, never a decision. Nothing is written "
        "to the catalogue by this call — confirm the mapping with `PATCH`, "
        "check the result with `preview`, and only then `commit`."
    ),
    responses={422: {"description": "The file could not be read"}},
)
async def create_batch(
    session: DbSession,
    request: Request,
    user: Importer,
    file: Annotated[UploadFile, File(description=".xlsx or .csv")],
    record_type: Annotated[str, Form()] = "museum_object",
    sheet_name: Annotated[str | None, Form()] = None,
    header_row: Annotated[
        int | None,
        Form(
            description=(
                "Which row holds the column headings. Left out, it is worked "
                "out from the file - most spreadsheets start at row 1, and the "
                "ones that do not usually open with a title and a blank line."
            )
        ),
    ] = None,
) -> ImportBatchDetail:
    _require_import_access(user, record_type)

    data = await file.read()
    filename = file.filename or "upload.xlsx"

    try:
        sheet = spreadsheets.read(
            data, filename=filename, sheet_name=sheet_name, header_row=header_row
        )
        suggested = spreadsheets.suggest_mapping(record_type, sheet.columns)
    except spreadsheets.SpreadsheetError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    extension = ".xlsx" if filename.lower().endswith((".xlsx", ".xlsm")) else ".csv"
    stored = storage.save_bytes(data, category="imports", extension=extension)

    batch = ImportBatch(
        record_type=record_type,
        filename=filename,
        stored_path=stored.path,
        checksum=stored.checksum,
        size_bytes=stored.size,
        sheet_name=sheet.name if extension == ".xlsx" else None,
        # What was *used*, which may have been worked out rather than given.
        header_row=sheet.header_row,
        columns=sheet.columns,
        mapping=suggested,
        defaults={},
        status=ImportStatus.ANALYSED,
        total_rows=len(sheet.rows),
        owner_id=user.id,
    )
    session.add(batch)
    session.flush()

    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_type=_MODELS[record_type][1],
        resource_id=batch.id,
        resource_label=filename,
        summary=f"Uploaded {filename} for import ({len(sheet.rows)} rows)",
        request=request,
    )
    session.flush()
    return _detail(session, batch, sheet=sheet)


@router.get(
    "",
    response_model=Page[ImportBatchSummary],
    summary="The sheet room",
    description=(
        "Every spreadsheet the platform holds, with the state of each.\n\n"
        "`mine=true` narrows it to your own, which is what the import screen "
        "wants. The room itself shows everybody's: a file somebody else "
        "loaded is still the institution's document, and a colleague looking "
        "for last season's finds register should not have to know who "
        "uploaded it."
    ),
)
def list_batches(
    session: DbSession,
    user: Importer,
    mine: Annotated[bool, Query(description="Only sheets you uploaded")] = False,
    record_type: Annotated[str | None, Query()] = None,
    state: Annotated[
        str | None,
        Query(description="received, imported, superseded, archived or failed"),
    ] = None,
    include_archived: Annotated[bool, Query()] = False,
    q: Annotated[str | None, Query(description="Match the filename")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ImportBatchSummary]:
    statement = select(ImportBatch).order_by(ImportBatch.created_at.desc())
    if mine:
        statement = statement.where(ImportBatch.owner_id == user.id)
    if record_type:
        statement = statement.where(ImportBatch.record_type == record_type)
    if q:
        statement = statement.where(func.lower(ImportBatch.filename).like(f"%{q.lower()}%"))
    # Archived sheets are put away, not deleted - out of the working list and
    # one filter from being back.
    if not include_archived and state != "archived":
        statement = statement.where(ImportBatch.is_archived.is_(False))
    rows, total = records.paginate(session, statement, limit, offset)
    items = [_summary(session, row) for row in rows]
    # The state is computed from several columns, so it is filtered here rather
    # than in SQL. A room holds tens of sheets, not tens of thousands.
    if state:
        items = [item for item in items if item.state == state]
        total = len(items)
    return Page[ImportBatchSummary](
        items=items, total=total, limit=limit, offset=offset
    )


def _summary(session: DbSession, batch: ImportBatch) -> ImportBatchSummary:
    payload = ImportBatchSummary.model_validate(batch)
    payload.state = batch.shelf_state
    owner = session.get(User, batch.owner_id)
    payload.owner_label = (owner.full_name or owner.username) if owner else None
    payload.has_current_copy = bool(batch.refreshed_path)
    return payload


@router.get("/{batch_id}", response_model=ImportBatchDetail, summary="Read one import")
def read_batch(batch_id: uuid.UUID, session: DbSession, user: Importer) -> ImportBatchDetail:
    return _detail(session, _get_batch(session, batch_id, user))


# --------------------------------------------------------------------------
# 2. Verify the mapping
# --------------------------------------------------------------------------
@router.patch(
    "/{batch_id}",
    response_model=ImportBatchDetail,
    summary="Confirm what each column fills",
    description=(
        'Send the mapping a person has approved: `{"Acc. No.": '
        '"accession_number", "Loc.": null}`. A column mapped to `null` is '
        "deliberately not imported.\n\n"
        "`defaults` sets values applied to every row — the collection, "
        "usually, when the file does not name one.\n\n"
        "Changing the sheet or the heading row re-reads the file, because both "
        "change what the columns are."
    ),
    responses={409: {"description": "This import has already been committed"}},
)
def update_batch(
    batch_id: uuid.UUID, payload: ImportMappingUpdate, session: DbSession, user: Importer
) -> ImportBatchDetail:
    batch = _get_batch(session, batch_id, user)
    if batch.status is ImportStatus.COMMITTED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                "This import has already been committed; its mapping is part of "
                "the record. Upload the file again to import more rows."
            ),
        )

    if payload.sheet_name is not None or payload.header_row is not None:
        batch.sheet_name = (
            payload.sheet_name if payload.sheet_name is not None else batch.sheet_name
        )
        batch.header_row = (
            payload.header_row if payload.header_row is not None else batch.header_row
        )
        sheet = _load_sheet(batch)
        batch.columns = sheet.columns
        batch.total_rows = len(sheet.rows)
        # The old mapping named columns that may no longer exist.
        batch.mapping = spreadsheets.suggest_mapping(batch.record_type, sheet.columns)

    if payload.mapping is not None:
        known = set(batch.columns)
        unknown = set(payload.mapping) - known
        if unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"The file has no column named {', '.join(sorted(unknown))}. "
                    f"Its columns are: {', '.join(batch.columns)}."
                ),
            )
        fields = {item["name"] for item in _available_fields(batch.record_type, session)}
        bad = {value for value in payload.mapping.values() if value and value not in fields}
        if bad:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Not fields on this record: {', '.join(sorted(bad))}.",
            )
        # A field filled by two columns is a mistake with a silent outcome —
        # whichever column happens to come last wins.
        filled = [value for value in payload.mapping.values() if value]
        duplicates = {name for name in filled if filled.count(name) > 1}
        if duplicates:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"More than one column is mapped to "
                    f"{', '.join(sorted(duplicates))}. Each field can be filled "
                    f"by one column."
                ),
            )
        batch.mapping = {**batch.mapping, **payload.mapping}

    if payload.defaults is not None:
        batch.defaults = payload.defaults
    if payload.note is not None:
        batch.note = payload.note

    batch.status = ImportStatus.MAPPED
    session.flush()
    return _detail(session, batch)


# --------------------------------------------------------------------------
# 3. Preview
# --------------------------------------------------------------------------
def _run(session: DbSession, batch: ImportBatch) -> importer.Plan:
    sheet = _load_sheet(batch)
    try:
        return importer.plan(
            session,
            batch.record_type,
            sheet.rows,
            batch.mapping,
            defaults=batch.defaults,
            header_row=batch.header_row,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


def _as_preview(plan: importer.Plan, *, limit: int) -> ImportPreview:
    return ImportPreview(
        total_rows=len(plan.rows),
        valid_rows=len(plan.valid),
        invalid_rows=len(plan.invalid),
        # Failures first: they are what the caller has to act on, and a preview
        # truncated to the first fifty successes hides them.
        rows=[
            ImportRowResult(
                row_number=row.row_number,
                ok=row.ok,
                values=row.values,
                errors=row.errors,
                warnings=row.warnings,
            )
            for row in (plan.invalid + plan.valid)[:limit]
        ],
    )


@router.post(
    "/{batch_id}/preview",
    response_model=ImportPreview,
    summary="Check every row without writing anything",
    description=(
        "Validates each row against the approved mapping and reports what "
        "would happen. Row numbers are the ones in the file, so a failure can "
        "be found in Excel.\n\n"
        "Failures are listed first. This writes nothing."
    ),
)
def preview_batch(
    batch_id: uuid.UUID,
    session: DbSession,
    user: Importer,
    limit: Annotated[int, Query(ge=1, le=1000, description="How many rows to report")] = 200,
) -> ImportPreview:
    batch = _get_batch(session, batch_id, user)
    plan = _run(session, batch)

    batch.status = ImportStatus.PREVIEWED
    batch.total_rows = len(plan.rows)
    batch.failed_count = len(plan.invalid)
    batch.errors = [{"row": row.row_number, "errors": row.errors} for row in plan.invalid[:500]]
    session.flush()
    return _as_preview(plan, limit=limit)


# --------------------------------------------------------------------------
# 4. Commit
# --------------------------------------------------------------------------
@router.post(
    "/{batch_id}/commit",
    response_model=ImportPreview,
    summary="Create the records",
    description=(
        "Creates every row that passes. Rows that fail are reported and "
        "skipped; the rest still import, because a single bad date in a file "
        "of four thousand objects is not a reason to import none of them.\n\n"
        "Send `all_or_nothing=true` to refuse the whole file unless every row "
        "passes.\n\n"
        "The identifiers created are kept on the batch, so the run can be "
        "undone with `DELETE /imports/{id}/records`."
    ),
    responses={409: {"description": "Already committed, or rows failed under all-or-nothing"}},
)
def commit_batch(
    batch_id: uuid.UUID,
    session: DbSession,
    request: Request,
    user: Importer,
    all_or_nothing: Annotated[
        bool, Query(description="Refuse the whole file unless every row passes")
    ] = False,
) -> ImportPreview:
    batch = _get_batch(session, batch_id, user)
    if batch.status is ImportStatus.COMMITTED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"This import already created {batch.created_count} records.",
        )

    plan = _run(session, batch)

    if all_or_nothing and plan.invalid:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"{len(plan.invalid)} of {len(plan.rows)} rows would fail and "
                f"all-or-nothing was asked for, so nothing was written. Run "
                f"preview to see which rows."
            ),
        )

    created: list[str] = []
    for row in plan.valid:
        # A savepoint per row, not a rollback: a bare ``session.rollback()``
        # would discard every record created before the failure *and* the batch
        # itself, so one bad row three thousand in would undo the whole run
        # while reporting success for the rows it had just destroyed.
        savepoint = session.begin_nested()
        try:
            record = _create_record(session, batch.record_type, row.values, user=user)
            savepoint.commit()
        except Exception as exc:  # noqa: BLE001 - the reason goes back to the user
            savepoint.rollback()
            row.errors.append(str(exc))
            continue
        created.append(str(record.id))

    batch.status = ImportStatus.COMMITTED
    batch.created_ids = created
    batch.created_count = len(created)
    batch.failed_count = len(plan.rows) - len(created)
    batch.errors = [
        {"row": row.row_number, "errors": row.errors} for row in plan.rows if row.errors
    ][:500]
    session.flush()

    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_type=_MODELS[batch.record_type][1],
        resource_id=batch.id,
        resource_label=batch.filename,
        summary=(
            f"Imported {len(created)} records from {batch.filename}"
            + (f", {batch.failed_count} rows failed" if batch.failed_count else "")
        ),
        request=request,
    )
    session.flush()
    return _as_preview(plan, limit=200)


def _create_record(session: DbSession, record_type: str, values: dict, *, user: User) -> Any:
    """One row, as a record of whichever kind this file holds."""
    builder = _CREATORS.get(record_type)
    if builder is None:  # pragma: no cover - guarded by _check_record_type
        raise ValueError(f"{record_type!r} cannot be imported")
    return builder(session, values, user=user)


def _parent(session: DbSession, values: dict, record_type: str, model: Any) -> Any:
    """The record this row hangs off, or a message saying what is missing.

    Every excavation record belongs to something — a context to a site, a site
    to a project — and a spreadsheet of contexts almost never says which site,
    because whoever made it knew. So the message has to name both ways of
    supplying it, or the answer to "no site" is a shrug.
    """
    field, label = PARENT_OF[record_type]
    identifier = values.get(field)
    if not identifier:
        raise ValueError(
            f"No {label}. Map a column to {label.capitalize()}, or set one as a "
            f"default for every row."
        )
    parent = session.get(model, uuid.UUID(str(identifier)))
    if parent is None:
        raise ValueError(f"No {label} with id {identifier}")
    return parent


def _fields_for(model: Any, values: dict, *, drop: set[str]) -> dict:
    """The values this model can actually hold.

    A column mapped to a field the model does not have is dropped rather than
    raised on: the mapping is checked on the verification screen, and a row
    that fails here fails three thousand rows in.

    Except for an institution's own fields. Those have no column by design -
    their values live in ``metadata_json`` - so anything left over after the
    real columns are taken is gathered there rather than thrown away. Without
    this, a custom field could be defined, offered on the mapping screen,
    mapped, previewed, committed, and silently store nothing.
    """
    kept: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key, value in values.items():
        if key in drop or value is None:
            continue
        if hasattr(model, key):
            kept[key] = value
        else:
            extra[key] = value

    if extra and hasattr(model, "metadata_json"):
        kept["metadata_json"] = {**(kept.get("metadata_json") or {}), **extra}
    return kept


def _create_site(session: DbSession, values: dict, *, user: User) -> Site:
    project = _parent(session, values, "site", Project)
    record = Site(
        project_id=project.id,
        owner_id=user.id,
        **_fields_for(Site, values, drop={"project_id"}),
    )
    session.add(record)
    session.flush()
    return record


def _create_context(session: DbSession, values: dict, *, user: User) -> ExcavationContext:
    site = _parent(session, values, "excavation_context", Site)
    record = ExcavationContext(
        site_id=site.id,
        owner_id=user.id,
        **_fields_for(ExcavationContext, values, drop={"site_id"}),
    )
    session.add(record)
    session.flush()
    return record


def _create_artifact(session: DbSession, values: dict, *, user: User) -> Artifact:
    site = _parent(session, values, "artifact", Site)

    # A finds register names its context by number — "1042", not a UUID — and
    # the number is only unique within a site, so this cannot be a value list
    # like Period is. Resolved here, against the site the row belongs to.
    context_id = _resolve_context(session, site, values.pop("context_id", None))

    record = Artifact(
        site_id=site.id,
        context_id=context_id,
        owner_id=user.id,
        **_fields_for(Artifact, values, drop={"site_id", "context_id"}),
    )
    session.add(record)
    session.flush()
    return record


def _resolve_context(session: DbSession, site: Site, raw: Any) -> uuid.UUID | None:
    """A context number, as the context on this site with that number."""
    if raw in (None, ""):
        return None

    text = str(raw).strip()
    try:
        # A file exported from this platform holds the identifier itself.
        return records.get_or_404(session, ExcavationContext, uuid.UUID(text), "Context").id
    except (ValueError, AttributeError, HTTPException):
        pass

    found = session.scalar(
        select(ExcavationContext).where(
            ExcavationContext.site_id == site.id,
            ExcavationContext.context_number == text,
        )
    )
    if found is None:
        raise ValueError(
            f"No context {text!r} on {site.code}. Import the contexts first, or "
            f"leave the column unmapped."
        )
    return found.id


def _create_museum_object(session: DbSession, values: dict, *, user: User) -> MuseumObject:
    """One row, as a catalogue record.

    Numbering goes through the same service the cataloguing form uses, so an
    imported object is numbered by the collection's own rule and a number that
    does not fit is flagged as legacy — exactly as if it had been typed.
    """
    collection_id = values.get("collection_id")
    if not collection_id:
        raise ValueError(
            "No collection. Map a column to Collection, or set one as a default for every row."
        )
    collection = session.get(Collection, uuid.UUID(str(collection_id)))
    if collection is None:
        raise ValueError(f"No collection with id {collection_id}")

    number, is_legacy, _warning = accession.assign(
        session, collection, requested=values.get("accession_number")
    )

    payload = {
        key: value
        for key, value in values.items()
        if key not in ("collection_id", "accession_number") and hasattr(MuseumObject, key)
    }
    record = MuseumObject(
        collection_id=collection.id,
        accession_number=number,
        number_is_legacy=is_legacy,
        owner_id=user.id,
        **payload,
    )
    session.add(record)
    session.flush()
    return record


#: Record type to the function that turns one row into one record. A dictionary
#: rather than a chain of ``if``s so that adding a type is adding a line.
_CREATORS: dict[str, Any] = {
    "museum_object": _create_museum_object,
    "site": _create_site,
    "excavation_context": _create_context,
    "artifact": _create_artifact,
}

#: What ``DELETE /{id}/records`` deletes, and which revision rows say a record
#: has been worked on since.
_MODELS: dict[str, tuple[Any, ResourceType]] = {
    "museum_object": (MuseumObject, ResourceType.MUSEUM_OBJECT),
    "site": (Site, ResourceType.SITE),
    "excavation_context": (ExcavationContext, ResourceType.CONTEXT),
    "artifact": (Artifact, ResourceType.ARTIFACT),
}


# --------------------------------------------------------------------------
# The sheet room
#
# A spreadsheet that arrived is a document, not only a step in an import.
# Everything below treats it as one: it can be downloaded as it came, brought
# up to date from the records it made, put away, or marked as replaced.
# --------------------------------------------------------------------------
@router.get(
    "/{batch_id}/original",
    summary="Download the sheet exactly as it arrived",
    description=(
        "Byte for byte as uploaded. This is the evidence - what was actually "
        "received, before anybody mapped a column or corrected a row - and it "
        "is never rewritten."
    ),
    response_class=FileResponse,
)
def download_original(batch_id: uuid.UUID, session: DbSession, user: Importer) -> FileResponse:
    batch = records.get_or_404(session, ImportBatch, batch_id, "Sheet")
    try:
        path = storage.absolute_path(batch.stored_path)
    except Exception as exc:  # pragma: no cover - a missing file is a disk fault
        raise HTTPException(
            status.HTTP_410_GONE,
            detail=(
                f"The stored copy of {batch.filename!r} is not on disk. Restore "
                "from a backup, or upload the file again."
            ),
        ) from exc
    return FileResponse(path, filename=batch.filename)


@router.post(
    "/{batch_id}/refresh",
    response_model=ImportBatchSummary,
    summary="Bring the sheet up to date from the records",
    description=(
        "Rebuilds the sheet from the records it created, as they stand now, "
        "**in the sheet's own columns and headings**. That last part is the "
        "point: a register that comes back with columns called "
        "`inventory_number` and `period_id` is a register somebody has to "
        "re-key before sending it to a ministry.\n\n"
        "The original is untouched. Built on request rather than on every "
        "edit - a sheet nobody has opened since 2019 does not need rebuilding "
        "because somebody fixed a typo."
    ),
    responses={409: {"description": "There is nothing to bring up to date"}},
)
def refresh_sheet(
    batch_id: uuid.UUID, session: DbSession, request: Request, user: Importer
) -> ImportBatchSummary:
    batch = records.get_or_404(session, ImportBatch, batch_id, "Sheet")
    _require_import_access(user, batch.record_type)

    try:
        payload = sheets.rebuild(session, batch, by=user.full_name or user.username)
    except sheets.SheetError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    stored = storage.save_bytes(payload, category="sheets", extension=".xlsx")
    batch.refreshed_path = stored.path
    batch.refreshed_at = datetime.now(UTC)
    session.add(batch)

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_label=batch.filename,
        summary=f"Brought {batch.filename!r} up to date from the records it made",
        request=request,
    )
    session.flush()
    return _summary(session, batch)


@router.get(
    "/{batch_id}/current.xlsx",
    summary="Download the sheet brought up to date",
    description=(
        "The copy built by `POST /refresh`. Ask for that first if there is "
        "none, or if the one on file is older than the edits you care about."
    ),
    response_class=FileResponse,
    responses={404: {"description": "No up-to-date copy has been built yet"}},
)
def download_current(batch_id: uuid.UUID, session: DbSession, user: Importer) -> FileResponse:
    batch = records.get_or_404(session, ImportBatch, batch_id, "Sheet")
    if not batch.refreshed_path:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=(
                "No up-to-date copy of this sheet has been built yet. Use "
                "'Bring it up to date' first."
            ),
        )
    stem = batch.filename.rsplit(".", 1)[0]
    return FileResponse(
        storage.absolute_path(batch.refreshed_path), filename=f"{stem} (up to date).xlsx"
    )


@router.patch(
    "/{batch_id}/shelf",
    response_model=ImportBatchSummary,
    summary="Put a sheet away, or say what replaced it",
    description=(
        "Archiving takes a sheet out of the working list and deletes nothing - "
        "it is still downloadable, and the records it made are untouched.\n\n"
        "Marking one as superseded points at the sheet that replaced it, so "
        "the room shows one current file and its history rather than four "
        "files with confusingly similar names."
    ),
)
def update_shelf(
    batch_id: uuid.UUID,
    payload: ShelfUpdate,
    session: DbSession,
    request: Request,
    user: Importer,
) -> ImportBatchSummary:
    batch = records.get_or_404(session, ImportBatch, batch_id, "Sheet")

    if payload.superseded_by_id is not None:
        if payload.superseded_by_id == batch.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A sheet cannot replace itself.",
            )
        records.get_or_404(session, ImportBatch, payload.superseded_by_id, "Sheet")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(batch, key, value)
    session.add(batch)

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_label=batch.filename,
        summary=f"Changed where {batch.filename!r} sits in the sheet room",
        request=request,
    )
    session.flush()
    return _summary(session, batch)


@router.delete(
    "/{batch_id}/records",
    response_model=Message,
    summary="Undo an import",
    description=(
        "Deletes the records this import created, and nothing else. A record "
        "that has been edited since the import is **kept** — somebody has "
        "worked on it, and undoing the import should not discard that."
    ),
    responses={409: {"description": "This import created nothing"}},
)
def revert_batch(
    batch_id: uuid.UUID, session: DbSession, request: Request, user: Importer
) -> Message:
    batch = _get_batch(session, batch_id, user)
    if batch.status is not ImportStatus.COMMITTED or not batch.created_ids:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="This import has not created any records."
        )

    model, resource_type = _MODELS[batch.record_type]
    ids = [uuid.UUID(value) for value in batch.created_ids]
    rows = session.scalars(select(model).where(model.id.in_(ids))).all()

    # A record that has been edited has a revision; one that has not, has none.
    # That is a better test than comparing timestamps, because ``updated_at``
    # defaults to the *transaction* clock and two changes inside one
    # transaction share an instant.
    edited = set(
        session.scalars(
            select(Revision.resource_id).where(
                Revision.resource_type == resource_type,
                Revision.resource_id.in_(ids),
            )
        ).all()
    )

    deleted = 0
    kept = 0
    for record in rows:
        if record.id in edited:
            kept += 1
            continue
        session.delete(record)
        deleted += 1

    batch.status = ImportStatus.REVERTED
    batch.created_ids = []
    session.flush()

    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=user,
        resource_type=resource_type,
        resource_id=batch.id,
        resource_label=batch.filename,
        summary=f"Reverted import of {batch.filename}: {deleted} records deleted",
        request=request,
    )

    detail = f"{deleted} record{'' if deleted == 1 else 's'} deleted."
    if kept:
        detail += (
            f" {kept} were kept because they have been edited since the import; "
            f"delete those individually if you mean to."
        )
    return Message(detail=detail)
