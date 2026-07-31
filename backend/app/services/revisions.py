"""Version history.

The specification is emphatic that data is never permanently overwritten. This
module is how that promise is kept: before any update, the record's current
state is snapshotted into ``revisions``, and any earlier version can be
restored — which is itself recorded as a new version, so a restore never
destroys the state it replaced either.

Snapshots store the **whole row** rather than a diff. That makes restore a
straight assignment instead of a replay, and it keeps old snapshots readable
after the schema gains columns.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import Date, DateTime, Integer, Numeric, func, inspect, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Session

from app.models.audit import Revision
from app.models.enums import ResourceType
from app.models.user import User

#: Never overwritten by a restore.
#:
#: ``id`` and ``created_at`` are facts about the row rather than editable
#: content, and ``updated_at`` is maintained by the database.
#:
#: ``review_status`` is excluded for a different reason: it is *workflow* state,
#: owned by the approval endpoints, not content owned by the editor. Restoring
#: an old version would otherwise silently un-approve a record — sending it back
#: to the pending queue, and out of public listings, with nobody told why.
#:
#: ``public_token`` backs the QR code printed on an artifact's physical label,
#: which must keep resolving for the life of the object.
IMMUTABLE_FIELDS = frozenset({"id", "created_at", "updated_at", "review_status", "public_token"})


def to_jsonable(value: Any) -> Any:
    """Convert a column value into something JSONB can hold."""
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        # Coordinates and measurements: float is lossy in principle but exact
        # for the precisions this schema uses, and JSON has no decimal type.
        return float(value)
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    return str(value)


def serialise(record: Any) -> dict[str, Any]:
    """Snapshot a record's columns as a JSON-safe dictionary.

    Geometry columns are skipped. They are derived from the ``latitude`` and
    ``longitude`` columns, which *are* captured, so nothing is lost — and
    round-tripping WKB through JSON would only invite precision bugs.
    """
    mapper = inspect(record).mapper
    return {
        column.key: to_jsonable(getattr(record, column.key))
        for column in mapper.columns
        if not isinstance(column.type, Geometry)
    }


def _restore_value(column: Any, value: Any) -> Any:
    """Turn a snapshot value back into what the column expects."""
    if value is None:
        return None

    column_type = column.type

    if isinstance(column_type, PGUUID):
        return uuid.UUID(value) if isinstance(value, str) else value
    if isinstance(column_type, DateTime):
        return datetime.fromisoformat(value) if isinstance(value, str) else value
    if isinstance(column_type, Date):
        return date.fromisoformat(value) if isinstance(value, str) else value
    if isinstance(column_type, Numeric) and not isinstance(column_type, Integer):
        return Decimal(str(value))
    # Enums, arrays, JSONB, strings and numbers are handed back as they are:
    # SQLAlchemy coerces enum values and the rest already match.
    return value


def next_version(session: Session, resource_type: ResourceType, resource_id: uuid.UUID) -> int:
    """The version number the next snapshot of this record should take."""
    highest = session.scalar(
        select(func.max(Revision.version)).where(
            Revision.resource_type == resource_type,
            Revision.resource_id == resource_id,
        )
    )
    return (highest or 0) + 1


def snapshot(
    session: Session,
    record: Any,
    resource_type: ResourceType,
    *,
    user: User | None = None,
    summary: str | None = None,
    changed_fields: list[str] | None = None,
    is_restore: bool = False,
) -> Revision:
    """Record the current state of ``record`` as a new version.

    Call this *before* applying an update, so the stored version is the state
    being replaced. The caller owns the transaction.
    """
    revision = Revision(
        resource_type=resource_type,
        resource_id=record.id,
        version=next_version(session, resource_type, record.id),
        data=serialise(record),
        changed_fields=changed_fields,
        change_summary=summary,
        changed_by_id=user.id if user else None,
        is_restore=is_restore,
    )
    session.add(revision)
    return revision


def history(
    session: Session,
    resource_type: ResourceType,
    resource_id: uuid.UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Revision], int]:
    """Versions of one record, newest first, with the total count."""
    base = select(Revision).where(
        Revision.resource_type == resource_type, Revision.resource_id == resource_id
    )
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = list(
        session.scalars(base.order_by(Revision.version.desc()).limit(limit).offset(offset)).all()
    )
    return rows, total


def get_revision(
    session: Session, resource_type: ResourceType, resource_id: uuid.UUID, version: int
) -> Revision | None:
    return session.scalar(
        select(Revision).where(
            Revision.resource_type == resource_type,
            Revision.resource_id == resource_id,
            Revision.version == version,
        )
    )


def restore(
    session: Session,
    record: Any,
    resource_type: ResourceType,
    version: int,
    *,
    user: User | None = None,
) -> tuple[Revision, list[str]]:
    """Roll a record back to an earlier version.

    Returns the newly created snapshot of the *pre-restore* state along with
    the fields that changed. Nothing is deleted: the version being replaced
    becomes the newest entry in the history, so a restore can itself be undone.
    """
    target = get_revision(session, resource_type, record.id, version)
    if target is None:
        raise ValueError(f"Version {version} does not exist for this record")

    mapper = inspect(record).mapper
    columns = {column.key: column for column in mapper.columns}

    changed: list[str] = []
    pending: dict[str, Any] = {}
    for key, stored in target.data.items():
        if key in IMMUTABLE_FIELDS or key not in columns:
            # Unknown keys come from snapshots taken before a column was
            # dropped or renamed; ignoring them is what makes old versions
            # survive schema change.
            continue
        value = _restore_value(columns[key], stored)
        if getattr(record, key) != value:
            changed.append(key)
            pending[key] = value

    created = snapshot(
        session,
        record,
        resource_type,
        user=user,
        summary=f"Restored version {version}",
        changed_fields=changed,
        is_restore=True,
    )

    for key, value in pending.items():
        setattr(record, key, value)
    session.add(record)

    return created, changed
