"""Keeping a copy of everything the platform deletes.

Deleting a record is the one action nobody can undo by clicking again, and the
one most likely to be done by the wrong person on the wrong row. The database
already keeps the final state as a revision — but a revision lives *in* the
database, so it is no help against the two cases that actually frighten
people: deleting the wrong thing and not noticing for a month, and losing the
database itself.

So every deletion also writes a plain JSON file to disk, outside the database,
before the row goes. It holds the record's own columns, everything that hung
off it, who deleted it, when, and the paths of any files it referred to. One
deletion, one file, named so it can be found by eye:

    2026/08/site-Tell-el-Demo-20260802T144210-a1b2c3d4.json

Three decisions worth stating.

**It writes to the backups volume, not a new one.** ``/data/backups`` is
already mounted, already on whatever disk the institution pointed
``BACKUP_ROOT`` at, and already the thing they think of as "the backups". A
deletion archive nobody can find is not an archive.

**A failure to write does not stop the deletion.** A full disk must not make
the platform unusable, and refusing to delete because the archive failed
punishes somebody for a problem they cannot see. The failure is logged loudly
and the response says the copy could not be written, so it is not silent
either.

**Uploaded files are recorded, not copied.** A photograph's bytes are
content-addressed and shared between records; copying them on every deletion
would duplicate gigabytes to guard against something that has not happened —
the media endpoints deliberately leave the bytes on disk when the record goes.
The archive stores the path, so the image is still findable.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.enums import ResourceType
from app.models.user import User
from app.services import revisions

logger = logging.getLogger("archeo.deletions")

#: Attributes that name a file on disk, recorded so a deleted photograph's
#: bytes can still be found.
_FILE_ATTRIBUTES = ("file_path", "original_filename", "thumbnails")


def root() -> Path:
    """Where deletion archives are written."""
    return Path(settings.DELETED_ROOT)


def _slug(value: str | None, limit: int = 60) -> str:
    """A filename fragment: readable, and safe on every filesystem.

    Windows refuses a colon, every system dislikes a slash, and an accession
    number like ``1974.1a-bis`` has to survive recognisably — somebody
    searching this folder is searching for the number they remember.
    """
    if not value:
        return "untitled"
    cleaned = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip("-.")
    return cleaned[:limit] or "untitled"


#: Most rows of any one child table to archive. A site with more contexts than
#: this is real; a file with a hundred thousand rows in it is not something
#: anybody will open. The count is recorded when it bites, so the archive never
#: quietly claims to be complete when it is not.
_CHILD_LIMIT = 5000


def _children(session: Session, record: Any) -> dict[str, list[dict[str, Any]]]:
    """Everything that hangs off this record, serialised.

    Two passes, because two different things count as a child and only one of
    them is visible to the ORM.

    **Mapped collections** — an activity's kit list, a budget's expenses. These
    are declared as relationships and come back by attribute access.

    **Foreign-key children** — a site's excavation contexts. Nothing declares
    ``Site.contexts``; the contexts simply carry a ``site_id``. Walking only
    the relationships would archive the site's name and lose everything that
    made it worth keeping, which is the exact failure this module exists to
    prevent. So the table metadata is swept for columns pointing back here.

    One level deep, deliberately. It captures a site's contexts without walking
    from a project into every photograph in the institution.

    Relationships that are not collections — the ``owner``, the ``project`` a
    record belongs to — are skipped either way. They are not part of what was
    deleted; they are its neighbours, and they are still there.
    """
    from sqlalchemy import select

    from app.db.base import Base

    result: dict[str, list[dict[str, Any]]] = {}
    mapper = sa_inspect(record).mapper
    table_name = mapper.local_table.name
    record_id = getattr(record, "id", None)

    for relationship in mapper.relationships:
        if not relationship.uselist:
            continue
        try:
            items = getattr(record, relationship.key)
        except Exception:  # noqa: BLE001 - a lazy load can fail on a deleted row
            continue
        rows = [revisions.serialise(item) for item in items or []]
        if rows:
            result[relationship.key] = rows

    if record_id is None:
        return result

    for other in Base.registry.mappers:
        other_table = other.local_table
        if other_table is None or other_table.name == table_name:
            continue

        for column in other_table.columns:
            if not any(fk.column.table.name == table_name for fk in column.foreign_keys):
                continue

            key = f"{other_table.name}.{column.name}"
            # Already captured as a mapped collection; archiving it twice would
            # double the file for no extra safety.
            if any(key.startswith(f"{name}.") for name in result):
                continue
            try:
                found = session.scalars(
                    select(other.class_).where(column == record_id).limit(_CHILD_LIMIT + 1)
                ).all()
            except Exception:  # noqa: BLE001 - a broken mapping must not stop the archive
                continue

            if not found:
                continue
            rows = [revisions.serialise(item) for item in found[:_CHILD_LIMIT]]
            if len(found) > _CHILD_LIMIT:
                rows.append({"_truncated": f"more than {_CHILD_LIMIT} rows; the rest are not here"})
            result[key] = rows

    return result


def _files(record: Any, children: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Paths of uploaded files this record referred to, so they stay findable."""
    found: list[str] = []

    def collect(data: dict[str, Any]) -> None:
        for name in _FILE_ATTRIBUTES:
            value = data.get(name)
            if isinstance(value, str) and value:
                found.append(value)
            elif isinstance(value, dict):
                found.extend(str(item) for item in value.values() if item)

    collect(revisions.serialise(record))
    for rows in children.values():
        for row in rows:
            collect(row)
    return found


def archive(
    session: Session,
    record: Any,
    resource_type: ResourceType,
    *,
    user: User | None,
    label: str | None = None,
    reason: str | None = None,
) -> Path | None:
    """Write a record and its children to disk before it is deleted.

    Returns the file written, or ``None`` if it could not be — see the module
    docstring for why that is not an error. Call this *before* the row goes:
    afterwards its children are already gone.
    """
    from app.services.records import label_for

    try:
        moment = datetime.now(UTC)
        name = label or label_for(record) or "untitled"
        record_id = getattr(record, "id", None)
        short = str(record_id)[:8] if record_id else uuid.uuid4().hex[:8]

        children = _children(session, record)
        payload = {
            "deleted_at": moment.isoformat(),
            "deleted_by": {
                "id": str(user.id) if user else None,
                "username": user.username if user else None,
                "full_name": user.full_name if user else None,
            },
            "reason": reason,
            "resource_type": resource_type.value,
            "resource_id": str(record_id) if record_id else None,
            "label": name,
            "record": revisions.serialise(record),
            "children": children,
            # Not copied — see the module docstring. Recorded so the bytes,
            # which are left on disk on purpose, can still be found.
            "files": _files(record, children),
            "note": (
                "Written by Stratum before this record was deleted. The "
                "uploaded files listed above were not copied; they are still "
                "in the uploads folder."
            ),
        }

        folder = root() / f"{moment:%Y}" / f"{moment:%m}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{resource_type.value}-{_slug(name)}-{moment:%Y%m%dT%H%M%S}-{short}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as error:  # noqa: BLE001 - see the module docstring
        logger.warning(
            "Could not archive %s %s before deleting it: %s",
            resource_type.value,
            getattr(record, "id", "?"),
            error,
        )
        return None

    logger.info("Archived %s %r to %s", resource_type.value, name, path)
    return path


def recent(limit: int = 100) -> list[dict[str, Any]]:
    """What has been deleted lately, newest first.

    Read from the files rather than the database on purpose: this is the view
    that still works when somebody is asking "did we lose the 2019 season?"
    and the answer has to come from something other than the database they no
    longer trust.
    """
    folder = root()
    if not folder.exists():
        return []

    files = sorted(folder.rglob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    entries: list[dict[str, Any]] = []
    for path in files[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries.append(
            {
                "file": str(path),
                "filename": path.name,
                "deleted_at": data.get("deleted_at"),
                "deleted_by": (data.get("deleted_by") or {}).get("username"),
                "resource_type": data.get("resource_type"),
                "resource_id": data.get("resource_id"),
                "label": data.get("label"),
                "reason": data.get("reason"),
                "child_count": sum(len(rows) for rows in (data.get("children") or {}).values()),
                "file_count": len(data.get("files") or []),
            }
        )
    return entries
