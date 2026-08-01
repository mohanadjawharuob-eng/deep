"""Floor plans: where the store is, drawn.

The storage hierarchy answers *which* shelf an object is on. A plan answers
*where that shelf is*, which is the question somebody standing in the doorway
of a room they have never been in actually has.

Two models, and the relationship between them is the design:

:class:`FloorPlan`
    A drawing of one place — a building, a floor, a room. Optionally backed by
    an image the institution already has: almost every museum owns a floor plan
    as a PDF or a scan, and asking somebody to redraw it in a browser is asking
    them not to use the feature.

:class:`FloorPlanShape`
    A region on that drawing. Its point is the **link**: a rectangle that *is*
    Cabinet 4 shows what Cabinet 4 holds, and keeps showing the right thing
    when an object moves, because the plan stores no inventory of its own. A
    plan that listed its own objects would be a second copy of the truth,
    wrong within a week.

Coordinates are normalised to 0–1 of the plan's extent rather than stored in
pixels. A plan drawn against a 2000px scan still lines up after the scan is
replaced with a better one at a different size, and the viewer can render at
whatever width the screen gives it without rescaling anything.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ResourceType, ShapeKind

if TYPE_CHECKING:
    from app.models.storage import StorageLocation
    from app.models.user import User


class FloorPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A drawing of one place in the store."""

    __tablename__ = "floor_plans"

    #: The place this is a plan of. Deleting the room deletes its plan: a plan
    #: of somewhere that no longer exists is not worth keeping.
    location_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("storage_locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    #: An existing plan, uploaded. Optional — a small store can be drawn from
    #: nothing — but the common case is that the institution already has one.
    image_path: Mapped[str | None] = mapped_column(String(500))
    image_width: Mapped[int | None] = mapped_column(Integer)
    image_height: Mapped[int | None] = mapped_column(Integer)
    #: Stored rather than guessed from the extension, so the file is served
    #: back as what it actually is.
    image_mime: Mapped[str | None] = mapped_column(String(100))

    #: How wide and deep the drawn area is in real metres, so the viewer can
    #: show a scale bar and so a shape's size means something.
    width_m: Mapped[float | None] = mapped_column(Numeric(8, 2))
    height_m: Mapped[float | None] = mapped_column(Numeric(8, 2))

    #: The plan shown first for this location.
    is_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    location: Mapped[StorageLocation] = relationship("StorageLocation")
    owner: Mapped[User | None] = relationship("User")
    shapes: Mapped[list[FloorPlanShape]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="FloorPlanShape.z_index",
    )

    __table_args__ = (
        CheckConstraint("width_m IS NULL OR width_m > 0", name="ck_floor_plans_width"),
        CheckConstraint("height_m IS NULL OR height_m > 0", name="ck_floor_plans_height"),
    )


class FloorPlanShape(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One region drawn on a plan, usually standing for a place.

    ``location_id`` is what makes a shape more than a picture: the rectangle
    *is* Cabinet 4, so the viewer can ask the store what Cabinet 4 holds. A
    shape without one is scenery — a wall, a doorway, a label — which a usable
    plan also needs.

    ``resource_type``/``resource_id`` cover the other case: an object too big
    to be in a box. A standing statue is at a spot on the gallery floor, not on
    a shelf, and pinning it directly is the honest way to say so.
    """

    __tablename__ = "floor_plan_shapes"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("floor_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[ShapeKind] = mapped_column(
        Enum(ShapeKind, name="shape_kind", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    #: ``[[x, y], …]`` with every value between 0 and 1, as a fraction of the
    #: plan's extent. A rectangle stores two corners, a circle a centre and a
    #: point on its edge, a polygon its vertices, a pin one point.
    points: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    label: Mapped[str | None] = mapped_column(String(200))
    #: A token name from the palette — "accent", "info", "ok" — not a hex, so
    #: a plan drawn today still fits the interface after a redesign.
    colour: Mapped[str | None] = mapped_column(String(30))
    rotation: Mapped[float] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    #: Draw order. Walls sit under cabinets, which sit under labels.
    z_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    location_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("storage_locations.id", ondelete="SET NULL"),
        index=True,
    )
    #: A specific record pinned to a spot, for something not in a container.
    resource_type: Mapped[ResourceType | None] = mapped_column(
        Enum(ResourceType, name="resource_type", values_callable=lambda e: [m.value for m in e])
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)

    notes: Mapped[str | None] = mapped_column(Text)

    plan: Mapped[FloorPlan] = relationship(back_populates="shapes")
    location: Mapped[StorageLocation | None] = relationship("StorageLocation")
