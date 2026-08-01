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
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import select

from app.api.deps import DbSession, require_module
from app.core.permissions import has_module_access
from app.models.audit import Revision
from app.models.enums import ActivityAction, ImportStatus, Module, ResourceType
from app.models.enums import ModuleLevel as Level
from app.models.imports import ImportBatch
from app.models.museum import Collection, MuseumObject
from app.models.user import User
from app.schemas.common import Message, Page
from app.schemas.imports import (
    ImportBatchDetail,
    ImportBatchSummary,
    ImportColumn,
    ImportMappingUpdate,
    ImportPreview,
    ImportRowResult,
)
from app.services import accession, activity, importer, records, spreadsheets
from app.services.storage import storage

router = APIRouter(prefix="/imports", tags=["Import"])

#: Which record types can be imported, and what each needs.
#:
#: Importing writes records into a module, so it is permissioned by that
#: module — not by a separate "may import" right, which would be a way around
#: the module ceiling.
SUPPORTED: dict[str, Module] = {"museum_object": Module.MUSEUM}

#: Importing creates records in bulk and is hard to undo by hand, so it is a
#: supervisor's job rather than a contributor's.
Importer = Annotated[User, Depends(require_module(Module.MUSEUM, Level.SUPERVISOR))]


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


def _get_batch(session: DbSession, batch_id: uuid.UUID, user: User) -> ImportBatch:
    batch = records.get_or_404(session, ImportBatch, batch_id, "Import")
    # An import batch holds a file somebody uploaded and a mapping they
    # approved; it is theirs, not the module's.
    if batch.owner_id != user.id and not has_module_access(
        user, Module.MUSEUM, Level.ADMINISTRATOR
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Import not found")
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
    payload.available_fields = _available_fields(batch.record_type)
    return payload


def _available_fields(record_type: str) -> list[dict[str, Any]]:
    """Every field a column may be mapped onto, for the verification screen."""
    from app.services import forms

    layout = forms.get_layout(record_type)
    if layout is None:
        return []
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
    header_row: Annotated[int, Form()] = 1,
) -> ImportBatchDetail:
    _check_record_type(record_type)

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
        header_row=header_row,
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
        resource_type=ResourceType.MUSEUM_OBJECT,
        resource_id=batch.id,
        resource_label=filename,
        summary=f"Uploaded {filename} for import ({len(sheet.rows)} rows)",
        request=request,
    )
    session.flush()
    return _detail(session, batch, sheet=sheet)


@router.get("", response_model=Page[ImportBatchSummary], summary="List imports")
def list_batches(
    session: DbSession,
    user: Importer,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ImportBatchSummary]:
    statement = (
        select(ImportBatch)
        .where(ImportBatch.owner_id == user.id)
        .order_by(ImportBatch.created_at.desc())
    )
    rows, total = records.paginate(session, statement, limit, offset)
    return Page[ImportBatchSummary](
        items=[ImportBatchSummary.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


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
        fields = {item["name"] for item in _available_fields(batch.record_type)}
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
            record = _create_museum_object(session, row.values, user=user)
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
        resource_type=ResourceType.MUSEUM_OBJECT,
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

    ids = [uuid.UUID(value) for value in batch.created_ids]
    rows = session.scalars(select(MuseumObject).where(MuseumObject.id.in_(ids))).all()

    # A record that has been edited has a revision; one that has not, has none.
    # That is a better test than comparing timestamps, because ``updated_at``
    # defaults to the *transaction* clock and two changes inside one
    # transaction share an instant.
    edited = set(
        session.scalars(
            select(Revision.resource_id).where(
                Revision.resource_type == ResourceType.MUSEUM_OBJECT,
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
        resource_type=ResourceType.MUSEUM_OBJECT,
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
