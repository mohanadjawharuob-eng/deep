"""Office and field inventory: the kit, and where it has gone.

Two kinds of thing, because they are counted differently and losing sight of
the difference is how inventories rot:

:class:`Equipment`
    A durable item tracked *individually*. A total station has a serial
    number, a calibration certificate, and a history of who took it where.
    Asking "how many total stations do we have" is a count of rows; asking
    "where is the Leica" is a question about one row.

:class:`Consumable`
    A stock line counted in *quantity*. Nobody tracks finds bag number 4,812.
    What matters is how many are left, and whether that is fewer than the
    number at which somebody should reorder.

The quantity on a consumable is never edited directly. It is the sum of a
ledger of :class:`StockMovement` rows, because a stock figure that anybody can
type over is a stock figure nobody can defend. "We are two hundred short" and
"somebody corrected the total last March" are different facts, and only the
ledger tells them apart.

Equipment leaves the building through :class:`Checkout` — one open loan per
item, enforced in the database rather than hoped for in the application, since
two people each believing they have the theodolite is exactly the failure the
register exists to prevent.

:class:`Calibration` records servicing. It is separate from the equipment row
because a certificate history is a list, and because the question a field
director asks — "is this due?" — is answered from the last row, not from a
field somebody remembered to update.

Kits sit on top of all of it. A :class:`KitTemplate` is the packing list for a
kind of day's work; building one issues the consumables and checks out the
equipment in a single action, and says plainly what it could not fill.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, OwnedRecordMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import CalibrationResult, EquipmentStatus, StockReason

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.storage import StorageLocation
    from app.models.user import User


class Equipment(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """One durable item, tracked as itself."""

    __tablename__ = "equipment"

    #: The number painted, engraved or stuck on the thing. Unique across the
    #: institution, because that is what somebody reads off the case when they
    #: ring up to ask where it should go back.
    asset_number: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)

    #: Free text against a suggested vocabulary rather than an enum: every
    #: institution's kit list is different, and a closed list would send people
    #: back to their spreadsheet within a week.
    category: Mapped[str | None] = mapped_column(String(120), index=True)
    manufacturer: Mapped[str | None] = mapped_column(String(160), index=True)
    model: Mapped[str | None] = mapped_column(String(160))
    serial_number: Mapped[str | None] = mapped_column(String(160), index=True)

    status: Mapped[EquipmentStatus] = mapped_column(
        Enum(
            EquipmentStatus,
            name="equipment_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=EquipmentStatus.AVAILABLE,
        index=True,
    )
    #: Free text, because "scratched lens, still usable" is the useful answer
    #: and no enum contains it.
    condition_notes: Mapped[str | None] = mapped_column(Text)

    # --- Purchase --------------------------------------------------------
    purchased_on: Mapped[date | None] = mapped_column(Date)
    purchase_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    supplier: Mapped[str | None] = mapped_column(String(200))
    warranty_until: Mapped[date | None] = mapped_column(Date)
    funding_source: Mapped[str | None] = mapped_column(String(200))

    # --- Calibration -----------------------------------------------------
    #: Only some kit needs it. A trowel does not; a total station, a dumpy
    #: level, a pH meter and a set of scales all do, and using one that is out
    #: of date can invalidate a season's readings.
    needs_calibration: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: How long a certificate lasts. Used to work out the next due date when a
    #: calibration is recorded without one being given.
    calibration_interval_days: Mapped[int | None] = mapped_column(Integer)
    #: Denormalised from the last calibration row so that "what is due next
    #: month" is one indexed scan rather than a correlated subquery per item.
    calibration_due_on: Mapped[date | None] = mapped_column(Date, index=True)

    # --- Where it lives --------------------------------------------------
    #: Its home shelf — where it belongs when nobody has it. Not where it is:
    #: that is the open checkout, if there is one.
    storage_location_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("storage_locations.id", ondelete="SET NULL"), index=True
    )

    #: Stable token for a printed label, matching the other labelled records.
    public_token: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True, default=lambda: uuid.uuid4().hex
    )
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    storage_location: Mapped[StorageLocation | None] = relationship()
    checkouts: Mapped[list[Checkout]] = relationship(
        back_populates="equipment",
        cascade="all, delete-orphan",
        order_by="Checkout.taken_at.desc()",
    )
    calibrations: Mapped[list[Calibration]] = relationship(
        back_populates="equipment",
        cascade="all, delete-orphan",
        order_by="Calibration.performed_on.desc()",
    )

    __table_args__ = (
        CheckConstraint(
            "calibration_interval_days IS NULL OR calibration_interval_days > 0",
            name="ck_equipment_calibration_interval_positive",
        ),
        CheckConstraint(
            "purchase_price IS NULL OR purchase_price >= 0",
            name="ck_equipment_price_not_negative",
        ),
        Index("ix_equipment_status_category", "status", "category"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Equipment {self.asset_number} {self.name}>"


class Checkout(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One item leaving the building, and coming back.

    Who has it is recorded twice over: a user id where the borrower has an
    account, and a name in any case. Field kit routinely goes out with a
    volunteer or a visiting specialist who will never log in, and a register
    that can only describe staff is a register with holes in it.
    """

    __tablename__ = "equipment_checkouts"

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("equipment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    borrower_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    #: Always filled in, even when ``borrower_id`` is set: a name typed on the
    #: day survives the account being deleted or the person being renamed.
    borrower_label: Mapped[str] = mapped_column(String(200), nullable=False)

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    #: Where it is going, in words. "Trench 4", "the conservation lab in Amman".
    destination: Mapped[str | None] = mapped_column(String(300))

    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    #: When it is expected back. Nullable, because indefinite loans within an
    #: institution are normal; an overdue list simply skips those.
    due_on: Mapped[date | None] = mapped_column(Date, index=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    condition_out: Mapped[str | None] = mapped_column(Text)
    #: What state it came back in. The pair is the point: an item that left
    #: fine and returned with a cracked screen has that written down against
    #: the person and the season it happened on.
    condition_in: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    issued_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    received_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    kit_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("kits.id", ondelete="SET NULL"), index=True
    )

    equipment: Mapped[Equipment] = relationship(back_populates="checkouts")
    borrower: Mapped[User | None] = relationship(foreign_keys=[borrower_id])
    issued_by: Mapped[User | None] = relationship(foreign_keys=[issued_by_id])
    received_by: Mapped[User | None] = relationship(foreign_keys=[received_by_id])
    project: Mapped[Project | None] = relationship()

    __table_args__ = (
        CheckConstraint(
            "returned_at IS NULL OR returned_at >= taken_at",
            name="ck_checkouts_returned_after_taken",
        ),
        # One open loan per item, enforced here rather than in the application.
        # Two people each believing they have the theodolite is precisely the
        # failure this register exists to prevent, and a check that lives in
        # Python is a check that a second request racing the first walks past.
        # Partial, so the constraint applies to open loans only — an item may
        # have been out a hundred times before.
        Index(
            "uq_equipment_one_open_checkout",
            "equipment_id",
            unique=True,
            postgresql_where=text("returned_at IS NULL"),
        ),
        Index("ix_checkouts_history", "equipment_id", "taken_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Checkout {self.equipment_id} → {self.borrower_label}>"


class Consumable(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """A stock line: finds bags, permatrace, batteries, labels."""

    __tablename__ = "consumables"

    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(120), index=True)

    #: What one of it is — "bag", "box of 100", "roll", "metre". Free text,
    #: because a unit that does not match how the store actually buys the thing
    #: makes every count a translation exercise.
    unit: Mapped[str] = mapped_column(String(60), nullable=False, default="each")

    #: Derived from the ledger, never typed. Numeric rather than integer
    #: because some stock is measured — 12.5 metres of permatrace.
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=0)
    #: Below this, the item shows up on the reorder list. Advisory.
    reorder_level: Mapped[float | None] = mapped_column(Numeric(12, 3))

    supplier: Mapped[str | None] = mapped_column(String(200))
    supplier_reference: Mapped[str | None] = mapped_column(String(120))
    unit_cost: Mapped[float | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))

    storage_location_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("storage_locations.id", ondelete="SET NULL"), index=True
    )
    #: Chemicals and adhesives go off, and a conservator needs to know before
    #: they use them, not after.
    expires_on: Mapped[date | None] = mapped_column(Date, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    storage_location: Mapped[StorageLocation | None] = relationship()
    movements: Mapped[list[StockMovement]] = relationship(
        back_populates="consumable",
        cascade="all, delete-orphan",
        order_by="StockMovement.occurred_at.desc()",
    )

    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_consumables_quantity_not_negative"),
        CheckConstraint(
            "reorder_level IS NULL OR reorder_level >= 0",
            name="ck_consumables_reorder_not_negative",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Consumable {self.code} {self.quantity}{self.unit}>"


class StockMovement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One change to the amount on the shelf. Append-only.

    ``change`` is signed: positive for stock arriving, negative for stock
    leaving. The running total is stored on the consumable for speed, but this
    table is the truth, and the two are reconciled by replaying it.
    """

    __tablename__ = "stock_movements"

    consumable_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("consumables.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    change: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    #: What the total became. Recorded on the row so that the ledger can be
    #: read as a bank statement, and so a later disagreement between the total
    #: and the sum of changes can be located rather than merely detected.
    balance_after: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)

    reason: Mapped[StockReason] = mapped_column(
        Enum(StockReason, name="stock_reason", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=StockReason.OTHER,
        index=True,
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    #: Who took it, as text. Same reasoning as a checkout's borrower label.
    issued_to_label: Mapped[str | None] = mapped_column(String(200))
    kit_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("kits.id", ondelete="SET NULL"), index=True
    )

    notes: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    recorded_by_label: Mapped[str | None] = mapped_column(String(200))

    consumable: Mapped[Consumable] = relationship(back_populates="movements")
    project: Mapped[Project | None] = relationship()
    recorded_by: Mapped[User | None] = relationship(foreign_keys=[recorded_by_id])

    __table_args__ = (
        CheckConstraint("change <> 0", name="ck_stock_movements_change_not_zero"),
        CheckConstraint("balance_after >= 0", name="ck_stock_movements_balance_not_negative"),
        Index("ix_stock_movements_consumable_time", "consumable_id", "occurred_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<StockMovement {self.consumable_id} {self.change:+}>"


class Calibration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One service or calibration of one item."""

    __tablename__ = "equipment_calibrations"

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("equipment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    performed_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    #: Usually an external laboratory, so text rather than a user reference.
    performed_by: Mapped[str | None] = mapped_column(String(200))
    certificate_number: Mapped[str | None] = mapped_column(String(160), index=True)

    result: Mapped[CalibrationResult] = mapped_column(
        Enum(
            CalibrationResult,
            name="calibration_result",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=CalibrationResult.PASSED,
        index=True,
    )
    #: When the next one falls due. Given explicitly if the certificate says
    #: so; otherwise worked out from the item's interval.
    next_due_on: Mapped[date | None] = mapped_column(Date, index=True)

    cost: Mapped[float | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    notes: Mapped[str | None] = mapped_column(Text)

    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    equipment: Mapped[Equipment] = relationship(back_populates="calibrations")

    __table_args__ = (
        UniqueConstraint(
            "equipment_id",
            "performed_on",
            "certificate_number",
            name="uq_calibration_certificate",
        ),
        Index("ix_calibrations_equipment_date", "equipment_id", "performed_on"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Calibration {self.equipment_id} {self.performed_on}>"


# --------------------------------------------------------------------------
# Kits
# --------------------------------------------------------------------------
class KitTemplate(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """A packing list for a kind of day's work.

    "Standard trench kit", "survey day", "wet sieving". Written once by
    somebody who knows what gets forgotten, then used by whoever is loading the
    van at six in the morning.
    """

    __tablename__ = "kit_templates"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    #: Retired templates stay, because kits built from them still refer here.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    lines: Mapped[list[KitTemplateLine]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="KitTemplateLine.position",
    )

    __table_args__ = (UniqueConstraint("name", name="uq_kit_templates_name"),)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<KitTemplate {self.name}>"


class KitTemplateLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One line on a packing list.

    A line names *one* of three things, never more:

    - a specific piece of equipment, when it has to be that one — the total
      station the whole survey grid was set up on;
    - a consumable and a quantity, which is most of a kit;
    - a category and a count, when any item of that kind will do. "Two
      cameras" is what a packing list usually means, and pinning a template to
      one camera means the template breaks the day that camera is in for
      repair.
    """

    __tablename__ = "kit_template_lines"

    template_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("kit_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("equipment.id", ondelete="CASCADE"), index=True
    )
    consumable_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("consumables.id", ondelete="CASCADE"), index=True
    )
    equipment_category: Mapped[str | None] = mapped_column(String(120), index=True)

    quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=1)
    #: A line that can be skipped without holding up the van. The build reports
    #: an unfilled optional line as a note rather than a shortfall.
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    template: Mapped[KitTemplate] = relationship(back_populates="lines")
    equipment: Mapped[Equipment | None] = relationship()
    consumable: Mapped[Consumable | None] = relationship()

    __table_args__ = (
        # Exactly one of the three. A line that names both a specific item and
        # a category cannot be filled without guessing which the author meant,
        # and a line that names none of them cannot be filled at all.
        CheckConstraint(
            "(CASE WHEN equipment_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN consumable_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN equipment_category IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_kit_template_lines_names_one_thing",
        ),
        CheckConstraint("quantity > 0", name="ck_kit_template_lines_quantity_positive"),
        Index("ix_kit_template_lines_order", "template_id", "position"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<KitTemplateLine {self.template_id} #{self.position}>"


class Kit(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """A packing list actually filled, for a project and a date.

    Building a kit checks out the equipment and issues the consumables in one
    action. What it could not fill is recorded on the kit rather than raised as
    an error, because a kit that is nine tenths ready is still the kit going
    out this morning — and the missing tenth is what the note is for.
    """

    __tablename__ = "kits"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("kit_templates.id", ondelete="SET NULL"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )

    issued_to_label: Mapped[str] = mapped_column(String(200), nullable=False)
    issued_to_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    destination: Mapped[str | None] = mapped_column(String(300))

    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    due_on: Mapped[date | None] = mapped_column(Date, index=True)
    #: Set when every piece of equipment in it has come back. Consumables do
    #: not come back, which is what makes them consumables.
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    #: What the build could not supply, line by line, as it stood on the day.
    #: Kept as data rather than prose so the screen can list it and a later
    #: build can be compared against it.
    shortfalls: Mapped[list | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)

    template: Mapped[KitTemplate | None] = relationship()
    project: Mapped[Project | None] = relationship()
    issued_to: Mapped[User | None] = relationship(foreign_keys=[issued_to_id])
    # Read-only: a checkout is created by issuing an item, never by appending
    # to this list. Both sides pointing at the same rows and both able to write
    # them is how a kit ends up disagreeing with the equipment register.
    checkouts: Mapped[list[Checkout]] = relationship(
        foreign_keys="Checkout.kit_id", viewonly=True, order_by="Checkout.taken_at"
    )
    stock_movements: Mapped[list[StockMovement]] = relationship(
        foreign_keys="StockMovement.kit_id", viewonly=True, order_by="StockMovement.occurred_at"
    )

    __table_args__ = (
        CheckConstraint(
            "returned_at IS NULL OR returned_at >= issued_at",
            name="ck_kits_returned_after_issued",
        ),
        Index("ix_kits_project_issued", "project_id", "issued_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Kit {self.name} {self.issued_at:%Y-%m-%d}>"
