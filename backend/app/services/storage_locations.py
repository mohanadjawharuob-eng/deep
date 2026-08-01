"""Maintaining the storage hierarchy and the movement register.

Three things here are easy to get wrong, so they live in one place:

**The materialised path.** ``path`` and ``display_path`` are denormalised
copies of the route from the root. They make "everything in Building A" an
indexed prefix scan, but they have to be rebuilt for a whole subtree whenever a
node is renamed or reparented — otherwise a cabinet moved between rooms goes on
claiming it is in the old one.

**Cycles.** Reparenting a node under its own descendant would produce a loop
that no traversal terminates on. It is refused before it is written.

**The register.** Every change of location appends a row. The current location
answers "where is it"; the register answers "where was it, when, and who moved
it" — which is the question that matters when something cannot be found.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import MovementReason, ResourceType, StorageKind
from app.models.storage import PATH_SEPARATOR, StorageLocation, StorageMovement
from app.models.user import User

_UNSAFE_CODE = re.compile(r"[^a-z0-9-]+")

#: How deep a store may nest. The named hierarchy is eight rungs; the limit is
#: a little higher to allow repeated rungs (a box inside a box), and exists so
#: that a bug cannot build an unbounded chain.
MAX_DEPTH = 12


class StorageError(ValueError):
    """A location cannot be placed there. The message is safe to show a user."""


def slug(value: str) -> str:
    """A path-safe form of a code: ``CAB-4`` becomes ``cab-4``."""
    cleaned = _UNSAFE_CODE.sub("-", value.strip().lower()).strip("-")
    return cleaned or "unnamed"


def build_path(parent: StorageLocation | None, code: str) -> tuple[str, int]:
    """The materialised path and depth a node would have under ``parent``."""
    segment = slug(code)
    if parent is None:
        return f"{PATH_SEPARATOR}{segment}", 0
    return f"{parent.path}{PATH_SEPARATOR}{segment}", parent.depth + 1


def build_display_path(parent: StorageLocation | None, name: str) -> str:
    if parent is None:
        return name
    return f"{parent.display_path} → {name}"


def check_kind_nests(parent: StorageLocation | None, kind: StorageKind) -> None:
    """A child may not sit at a *shallower* rung than its parent.

    Three things are deliberately allowed, because real stores do all of them:

    - **Skipping rungs.** A crate standing on a room floor has no cabinet.
    - **Repeating a rung.** Finds bags inside a crate are boxes inside a box;
      an anteroom off a room is a room inside a room.
    - **Rooting anywhere.** A store catalogued from the room down need not
      invent a building to hang it from.

    What is refused is *inversion* — a room inside a shelf — because that is
    never a description of a building, only a mistake.
    """
    if parent is None:
        return
    if kind.depth < parent.kind.depth:
        raise StorageError(
            f"A {kind.value} cannot sit inside a {parent.kind.value}. "
            f"Storage nests outermost to innermost: institution, building, "
            f"floor, room, cabinet, shelf, drawer, box."
        )


def descendants(session: Session, location: StorageLocation) -> list[StorageLocation]:
    """Every location beneath this one, at any depth.

    A prefix match on the materialised path, which is why it is maintained.
    The separator is appended so ``/room-2`` does not also match ``/room-20``.
    """
    prefix = f"{location.path}{PATH_SEPARATOR}"
    return list(
        session.scalars(
            select(StorageLocation)
            .where(StorageLocation.path.startswith(prefix))
            .order_by(StorageLocation.path)
        ).all()
    )


def check_no_cycle(session: Session, location: StorageLocation, parent: StorageLocation) -> None:
    """Refuse a reparent that would place a node inside its own subtree."""
    if parent.id == location.id:
        raise StorageError("A location cannot contain itself")
    prefix = f"{location.path}{PATH_SEPARATOR}"
    if parent.path.startswith(prefix):
        raise StorageError(
            f"{parent.name!r} is already inside {location.name!r}; moving it there "
            f"would make a loop"
        )


def resolve_parent(session: Session, parent_id: uuid.UUID | None) -> StorageLocation | None:
    if parent_id is None:
        return None
    parent = session.get(StorageLocation, parent_id)
    if parent is None:
        raise StorageError("That parent location does not exist")
    if parent.depth + 1 > MAX_DEPTH:
        raise StorageError(f"Storage cannot nest more than {MAX_DEPTH} levels deep")
    return parent


def create(
    session: Session,
    *,
    kind: StorageKind,
    name: str,
    code: str,
    parent_id: uuid.UUID | None = None,
    **fields: Any,
) -> StorageLocation:
    """Add a location, computing its path from its parent."""
    parent = resolve_parent(session, parent_id)
    check_kind_nests(parent, kind)

    path, depth = build_path(parent, code)
    location = StorageLocation(
        parent_id=parent.id if parent is not None else None,
        kind=kind,
        name=name,
        code=code,
        path=path,
        display_path=build_display_path(parent, name),
        depth=depth,
        **fields,
    )
    session.add(location)
    session.flush()
    return location


def rebuild_subtree(session: Session, location: StorageLocation) -> int:
    """Recompute paths for a node's whole subtree after it moved or was renamed.

    Returns how many descendants were rewritten. Walks breadth-first from the
    node so every parent is correct before its children are read.
    """
    rewritten = 0
    queue: list[StorageLocation] = [location]

    while queue:
        current = queue.pop(0)
        children = list(
            session.scalars(
                select(StorageLocation).where(StorageLocation.parent_id == current.id)
            ).all()
        )
        for child in children:
            child.path, child.depth = build_path(current, child.code)
            child.display_path = build_display_path(current, child.name)
            session.add(child)
            rewritten += 1
        queue.extend(children)

    session.flush()
    return rewritten


def relocate(
    session: Session, location: StorageLocation, parent_id: uuid.UUID | None
) -> StorageLocation:
    """Move a location — and everything in it — under a new parent."""
    parent = resolve_parent(session, parent_id)
    if parent is not None:
        check_no_cycle(session, location, parent)
        check_kind_nests(parent, location.kind)
        if parent.depth + 1 + _subtree_height(session, location) > MAX_DEPTH:
            raise StorageError(f"That move would nest deeper than {MAX_DEPTH} levels")

    location.parent_id = parent.id if parent is not None else None
    location.path, location.depth = build_path(parent, location.code)
    location.display_path = build_display_path(parent, location.name)
    session.add(location)
    session.flush()

    rebuild_subtree(session, location)
    return location


def _subtree_height(session: Session, location: StorageLocation) -> int:
    """How many levels sit below this node; 0 for a leaf."""
    below = descendants(session, location)
    if not below:
        return 0
    return max(child.depth for child in below) - location.depth


def rename(session: Session, location: StorageLocation, *, name: str | None, code: str | None):
    """Rename or recode a location, keeping its subtree's paths correct."""
    if name is not None:
        location.name = name
    if code is not None:
        location.code = code

    parent = session.get(StorageLocation, location.parent_id) if location.parent_id else None
    location.path, location.depth = build_path(parent, location.code)
    location.display_path = build_display_path(parent, location.name)
    session.add(location)
    session.flush()

    rebuild_subtree(session, location)
    return location


def ancestors(session: Session, location: StorageLocation) -> list[StorageLocation]:
    """The chain from the root down to (but excluding) this location."""
    chain: list[StorageLocation] = []
    current = location
    seen: set[uuid.UUID] = {current.id}

    while current.parent_id is not None:
        parent = session.get(StorageLocation, current.parent_id)
        if parent is None or parent.id in seen:  # pragma: no cover - guarded on write
            break
        chain.append(parent)
        seen.add(parent.id)
        current = parent

    return list(reversed(chain))


def occupancy(session: Session, location: StorageLocation, *, include_children: bool) -> int:
    """How many objects are in this location.

    ``include_children`` counts the whole subtree, which is what somebody
    asking "how full is Room 203" means.
    """
    from app.models.artifact import Artifact

    if include_children:
        ids = [location.id, *(child.id for child in descendants(session, location))]
    else:
        ids = [location.id]

    from sqlalchemy import func

    return (
        session.scalar(
            select(func.count()).select_from(Artifact).where(Artifact.storage_location_id.in_(ids))
        )
        or 0
    )


# --------------------------------------------------------------------------
# The movement register
# --------------------------------------------------------------------------
def record_movement(
    session: Session,
    *,
    resource_type: ResourceType,
    resource_id: uuid.UUID,
    resource_label: str | None,
    from_location: StorageLocation | None,
    to_location: StorageLocation | None,
    reason: MovementReason = MovementReason.OTHER,
    notes: str | None = None,
    moved_at: datetime | None = None,
    user: User | None = None,
) -> StorageMovement:
    """Append one move to the register.

    The paths are copied in rather than joined out later: a location can be
    renamed or decommissioned, and what the register said on the day must not
    change with it.
    """
    if from_location is None and to_location is None:
        raise StorageError("A movement needs a source or a destination")

    movement = StorageMovement(
        resource_type=resource_type,
        resource_id=resource_id,
        resource_label=resource_label,
        from_location_id=from_location.id if from_location is not None else None,
        to_location_id=to_location.id if to_location is not None else None,
        from_path=from_location.display_path if from_location is not None else None,
        to_path=to_location.display_path if to_location is not None else None,
        reason=reason,
        notes=notes,
        moved_at=moved_at or datetime.now(UTC),
        moved_by_id=user.id if user is not None else None,
        moved_by_label=user.full_name if user is not None else None,
    )
    session.add(movement)
    session.flush()
    return movement


def move_object(
    session: Session,
    record: Any,
    resource_type: ResourceType,
    *,
    to_location_id: uuid.UUID | None,
    reason: MovementReason = MovementReason.OTHER,
    notes: str | None = None,
    moved_at: datetime | None = None,
    user: User | None = None,
    label: str | None = None,
) -> StorageMovement | None:
    """Put an object in a new place and register the move.

    Returns ``None`` when the object is already there — re-saving a form must
    not manufacture a movement that never happened.
    """
    current_id = getattr(record, "storage_location_id", None)
    if current_id == to_location_id:
        return None

    from_location = session.get(StorageLocation, current_id) if current_id else None

    to_location = None
    if to_location_id is not None:
        to_location = session.get(StorageLocation, to_location_id)
        if to_location is None:
            raise StorageError("That storage location does not exist")
        if not to_location.is_active:
            raise StorageError(
                f"{to_location.display_path} is not accepting objects. "
                f"Reactivate it, or choose another location."
            )

    record.storage_location_id = to_location_id
    session.add(record)

    return record_movement(
        session,
        resource_type=resource_type,
        resource_id=record.id,
        resource_label=label,
        from_location=from_location,
        to_location=to_location,
        reason=reason,
        notes=notes,
        moved_at=moved_at,
        user=user,
    )


def history(
    session: Session, resource_type: ResourceType, resource_id: uuid.UUID
) -> list[StorageMovement]:
    """Every recorded move of one object, oldest first.

    The id is a tiebreaker because two moves can share a timestamp when a
    registrar enters a day's work in one sitting.
    """
    return list(
        session.scalars(
            select(StorageMovement)
            .where(
                StorageMovement.resource_type == resource_type,
                StorageMovement.resource_id == resource_id,
            )
            .order_by(StorageMovement.moved_at.asc(), StorageMovement.id.asc())
        ).all()
    )
