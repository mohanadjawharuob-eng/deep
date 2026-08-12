"""The sheet room: a spreadsheet kept as a document, not only as an import.

A file that arrived is a record in its own right. Somebody will ask for "the
finds register as Ahmad sent it in March" long after the four hundred records
it created have been corrected, and the only honest answer is the file itself.

So the platform keeps **two** copies of every sheet, and never confuses them:

**The original.** Byte for byte as it arrived, checksummed, never rewritten.
It is evidence. Overwriting it with a tidier version would destroy the one
thing that cannot be reconstructed.

**The current copy.** The same records as they stand now, in the same columns,
in the same order, under the same headings the file used. This is what somebody
means by "can I have the updated sheet" - they do not want the platform's own
export with the platform's own column names, they want *their* register with
the corrections in it, because their next step is to send it to a ministry that
expects that shape.

Built on request rather than on every edit. A sheet nobody has asked for since
2019 does not need rebuilding because somebody fixed a typo, and the rebuild
reads every record the import created.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.context import ExcavationContext
from app.models.imports import ImportBatch
from app.models.inventory import Consumable, Equipment
from app.models.museum import MuseumObject
from app.models.site import Site
from app.services import forms, workbooks

#: Which table a batch's records live in. The same map the importer uses, kept
#: here rather than imported from the endpoint so a service does not depend on
#: an endpoint.
MODELS: dict[str, Any] = {
    "museum_object": MuseumObject,
    "site": Site,
    "excavation_context": ExcavationContext,
    "artifact": Artifact,
    "equipment": Equipment,
    "consumable": Consumable,
}


class SheetError(Exception):
    """Raised when a sheet cannot be rebuilt, with the reason in words."""


def _readable(session: Session, value: Any) -> Any:
    """A value as a person would want it in a cell.

    An identifier in a spreadsheet is useless - nobody can read a UUID, and a
    ministry receiving one has been sent noise. References come out as the name
    of the thing they point at.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _resolve_reference(session: Session, field: forms.FormField, value: Any) -> Any:
    """The name behind a reference field's identifier."""
    if value is None:
        return None
    lookup = {
        "site": Site,
        "artifact": Artifact,
        "excavation_context": ExcavationContext,
        "museum_object": MuseumObject,
    }
    from app.models.museum import Collection
    from app.models.project import Project
    from app.models.storage import StorageLocation
    from app.models.taxonomy import Material, ObjectCategory, Period

    lookup.update(
        {
            "period": Period,
            "material": Material,
            "object_category": ObjectCategory,
            "collection": Collection,
            "project": Project,
            "storage_location": StorageLocation,
        }
    )
    model = lookup.get(field.references or "")
    if model is None:
        return str(value)
    try:
        row = session.get(model, value if isinstance(value, uuid.UUID) else uuid.UUID(str(value)))
    except (ValueError, AttributeError):
        return str(value)
    if row is None:
        return str(value)
    for attribute in ("display_path", "name", "title", "code"):
        found = getattr(row, attribute, None)
        if found:
            return found
    return str(value)


def _reader(session: Session, field: forms.FormField):
    """How to get one column's value off a record.

    A custom field has no column of its own - its value sits in the record's
    ``metadata_json`` - which is exactly the case a naive ``getattr`` gets
    silently wrong, filling a column with blanks and looking like data loss.
    """

    def read(record: Any) -> Any:
        if field.custom:
            bag = getattr(record, "metadata_json", None) or {}
            return bag.get(field.name)
        value = getattr(record, field.name, None)
        if field.kind == "reference":
            return _resolve_reference(session, field, value)
        return _readable(session, value)

    return read


def current_rows(session: Session, batch: ImportBatch) -> list[Any]:
    """The records this import created, as they stand now.

    Records deleted since are simply not there. A rebuilt sheet with a row for
    something that no longer exists would be a worse lie than a shorter sheet.
    """
    model = MODELS.get(batch.record_type)
    if model is None:
        raise SheetError(f"There is no table behind {batch.record_type!r} records.")
    identifiers = [uuid.UUID(str(value)) for value in (batch.created_ids or [])]
    if not identifiers:
        return []
    rows = session.scalars(select(model).where(model.id.in_(identifiers))).all()
    order = {identifier: index for index, identifier in enumerate(identifiers)}
    return sorted(rows, key=lambda row: order.get(row.id, len(order)))


def rebuild(session: Session, batch: ImportBatch, *, by: str | None = None) -> bytes:
    """The sheet's records as they stand now, in the sheet's own columns.

    The point of using the file's own headings rather than the platform's is
    that the file has somewhere to go afterwards. A register that comes back
    with columns called ``inventory_number`` and ``period_id`` is a register
    somebody has to re-key before sending it on.
    """
    if not (batch.created_ids or []):
        raise SheetError(
            "This sheet has not been imported, so there is nothing to bring up "
            "to date. The original is on the shelf and can be downloaded as it "
            "arrived."
        )

    layout = forms.get_layout(batch.record_type)
    if layout is None:
        raise SheetError(f"There is no form for {batch.record_type!r}.")
    layout = forms.with_custom(session, layout)
    known = forms.field_index(layout)

    rows = current_rows(session, batch)

    columns: list[workbooks.Column] = []
    unfilled: list[str] = []
    for heading in batch.columns or []:
        target = (batch.mapping or {}).get(heading)
        field = known.get(target) if target else None
        if field is None:
            # A column nobody mapped has no value on the platform to bring up
            # to date. Writing it as an empty column would read as four hundred
            # rows of lost data, so it is left out and named on the cover.
            unfilled.append(heading)
            continue
        columns.append(workbooks.Column(header=heading, get=_reader(session, field)))

    if not columns:
        raise SheetError("None of this sheet's columns were mapped onto a field.")

    notes = [
        "The same records as the original sheet, as they stand on the platform now.",
        "The original file is kept separately and is never overwritten.",
    ]
    if unfilled:
        notes.append(
            "Columns left out because they were never mapped onto a field, so the "
            "platform holds no value for them: " + ", ".join(unfilled)
        )
    missing = len(batch.created_ids or []) - len(rows)
    if missing > 0:
        notes.append(
            f"{missing} record(s) this import created have since been deleted and "
            "are not in this copy."
        )

    book = workbooks.Workbook(
        subject=batch.filename,
        kind="Sheet, brought up to date",
        exported_by=by,
        notes=notes,
    )
    book.add(
        workbooks.Table(
            title=batch.sheet_name or "Records",
            columns=columns,
            rows=rows,
        )
    )
    return workbooks.build(book)
