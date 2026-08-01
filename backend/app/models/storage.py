"""Physical storage: where things actually are, and where they have been.

One hierarchy serves the archaeology, museum and inventory modules, because an
institution has one building. A find, an accessioned object and a total station
all end up on a shelf, and that shelf should not be described three times in
three tables.

Two models:

:class:`StorageLocation`
    A node in the tree — institution, building, floor, room, cabinet, shelf,
    drawer or box. Self-referencing, with a materialised path so that "show me
    everything in Building A" is an indexed prefix scan rather than a recursive
    query on every page load.

:class:`StorageMovement`
    An append-only record of one object leaving one place for another. This is
    the part that matters when something goes missing: the current location
    answers "where is it", the movement history answers "where was it, when,
    and who moved it".

The movement table is polymorphic over ``(resource_type, resource_id)`` rather
than one table per module, for the same reason ``record_permissions`` is: the
question "where has this been" has one answer shape whatever the object is.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import MovementReason, ResourceType, StorageKind

if TYPE_CHECKING:
    from app.models.user import User

#: Separator for the materialised path. Slash, so a path reads like a route
#: through the building: ``/main/building-a/203/cab-4/shelf-b``.
PATH_SEPARATOR = "/"


class StorageLocation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One place something can be, at any depth of the hierarchy."""

    __tablename__ = "storage_locations"

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        # Restricted rather than cascading: deleting a room should not silently
        # delete the cabinets in it and orphan everything they held.
        ForeignKey("storage_locations.id", ondelete="RESTRICT"),
        index=True,
    )
    kind: Mapped[StorageKind] = mapped_column(
        Enum(StorageKind, name="storage_kind", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    #: Short identifier used in the path and on labels — "203", "CAB-4".
    code: Mapped[str] = mapped_column(String(60), nullable=False)

    #: Full route from the root, rebuilt whenever a node moves or is renamed.
    #: Denormalised on purpose: every listing shows it, and every "what is in
    #: here" query is a prefix match against it.
    path: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    #: Human-readable equivalent — "Main Store → Building A → Room 203".
    display_path: Mapped[str] = mapped_column(String(1200), nullable=False)
    #: Distance from the root, so a query can ask for one level at a time.
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)

    description: Mapped[str | None] = mapped_column(Text)
    #: How many objects this place is meant to hold; advisory, not enforced.
    capacity: Mapped[int | None] = mapped_column(Integer)
    #: A store that is full, sealed or decommissioned stops accepting objects
    #: without losing the history of what was in it.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # --- Environmental monitoring ----------------------------------------
    #: Target conditions for the material stored here. Recorded per location
    #: because a metals cabinet and a textile store want different numbers, and
    #: a conservator needs to know the target to judge a reading against it.
    target_temperature_c: Mapped[float | None] = mapped_column(Numeric(4, 1))
    target_humidity_percent: Mapped[float | None] = mapped_column(Numeric(4, 1))
    environment_notes: Mapped[str | None] = mapped_column(Text)

    #: Stable token for a printed shelf label, matching artifacts and sites.
    public_token: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True, default=lambda: uuid.uuid4().hex
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    parent: Mapped[StorageLocation | None] = relationship(
        back_populates="children", remote_side="StorageLocation.id"
    )
    children: Mapped[list[StorageLocation]] = relationship(
        back_populates="parent", order_by="StorageLocation.name"
    )

    __table_args__ = (
        # Two shelves in one cabinet may not share a code; two cabinets in
        # different rooms may. Uniqueness is per parent, which is how anyone
        # labelling a store actually thinks.
        UniqueConstraint("parent_id", "code", name="uq_storage_locations_sibling_code"),
        CheckConstraint("depth >= 0", name="ck_storage_locations_depth"),
        CheckConstraint("id <> parent_id", name="ck_storage_locations_not_self_parent"),
        Index("ix_storage_locations_path_prefix", "path"),
        Index("ix_storage_locations_parent_kind", "parent_id", "kind"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<StorageLocation {self.path}>"


class StorageMovement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One object moving from one place to another. Append-only.

    Both endpoints are nullable: an accession has no origin, and an object that
    has been consumed by destructive analysis or repatriated has no
    destination. A row with neither would be meaningless and is refused.
    """

    __tablename__ = "storage_movements"

    resource_type: Mapped[ResourceType] = mapped_column(
        Enum(ResourceType, name="resource_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    #: Copied at the time of the move so the history stays readable after the
    #: object is renumbered — or deleted.
    resource_label: Mapped[str | None] = mapped_column(String(300))

    from_location_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("storage_locations.id", ondelete="SET NULL")
    )
    to_location_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("storage_locations.id", ondelete="SET NULL")
    )
    #: The paths as they read at the time. A location can be renamed or removed
    #: later; what the register said on the day must not change with it.
    from_path: Mapped[str | None] = mapped_column(String(1200))
    to_path: Mapped[str | None] = mapped_column(String(1200))

    reason: Mapped[MovementReason] = mapped_column(
        Enum(
            MovementReason, name="movement_reason", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
        default=MovementReason.OTHER,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text)

    #: When the object physically moved, which is not always when it was typed
    #: in. Backdating a move is normal; a registrar catches up on Friday.
    moved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    moved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    #: Denormalised for the same reason as ``resource_label``.
    moved_by_label: Mapped[str | None] = mapped_column(String(200))

    from_location: Mapped[StorageLocation | None] = relationship(foreign_keys=[from_location_id])
    to_location: Mapped[StorageLocation | None] = relationship(foreign_keys=[to_location_id])
    moved_by: Mapped[User | None] = relationship(foreign_keys=[moved_by_id])

    __table_args__ = (
        CheckConstraint(
            "from_location_id IS NOT NULL OR to_location_id IS NOT NULL",
            name="ck_storage_movements_has_an_end",
        ),
        Index("ix_storage_movements_resource", "resource_type", "resource_id", "moved_at"),
        Index("ix_storage_movements_to_location", "to_location_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<StorageMovement {self.resource_type.value} → {self.to_path}>"
