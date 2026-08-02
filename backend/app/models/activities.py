"""The activity hub: what we did, what it took, and what it cost.

Every other module in the platform records a *thing* — a find, an object, a
piece of kit, a fund. This one records an *undertaking*: the 2019 season at the
north trench, the week of geophysics before it, the school visit in March. It
is the module somebody opens when they are about to do the same thing again.

That is the whole design brief, and it is why the child tables look the way
they do. Six weeks before a season, the questions are always the same:

- What did we take? — :class:`ActivityEquipment`
- What did we have to get permission for, from whom, and how long did it
  take? — :class:`ActivityPermit`
- What did we have to arrange beforehand, and how far ahead? —
  :class:`ActivityPreparation`
- What did it cost? — :class:`ActivityCost`
- What did it look like? — :class:`ActivityPhoto`

Two decisions run through all of them.

**Everything links, and nothing requires a link.** A piece of equipment can
point at an :class:`~app.models.inventory.Equipment` row, or it can be the
words "borrowed generator" — because the kit list from 2014 is worth keeping
even though half of it was never in the inventory. The same is true of costs
against expenses and of the lead on an activity. A hub that only accepts
records the platform already holds is a hub nobody can enter the past into.

**Lead time is a first-class field.** ``ActivityPermit.lead_time_days`` and
``ActivityPreparation.lead_time_days`` are what turn a historical record into a
usable plan. "The ministry took 46 days last time" is the single most valuable
thing this module knows, and it is only knowable because the dates were kept.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
from app.models.enums import ActivityKind, ActivityStatus, ExpenseCategory, PermitStatus

if TYPE_CHECKING:
    from app.models.inventory import Equipment
    from app.models.media import Photograph
    from app.models.project import Project
    from app.models.site import Site
    from app.models.user import User


def _enum(python_enum: type, name: str) -> Enum:
    """A native PG enum storing the member *values*, not their Python names."""
    return Enum(python_enum, name=name, values_callable=lambda e: [m.value for m in e])


class Activity(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """One undertaking: a season, a survey, a visit, a week in the lab."""

    __tablename__ = "activities"

    title: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    #: What happened, in whatever detail somebody wanted to write down. The
    #: field that actually holds the institutional memory.
    summary: Mapped[str | None] = mapped_column(Text)

    kind: Mapped[ActivityKind] = mapped_column(
        _enum(ActivityKind, "activity_kind"),
        nullable=False,
        default=ActivityKind.OTHER,
        index=True,
    )
    status: Mapped[ActivityStatus] = mapped_column(
        _enum(ActivityStatus, "activity_status"),
        nullable=False,
        default=ActivityStatus.PLANNED,
        index=True,
    )

    #: Nullable because a planned activity often has no date yet, and refusing
    #: to record it until it does is how planning ends up in a spreadsheet.
    starts_on: Mapped[date | None] = mapped_column(Date, index=True)
    ends_on: Mapped[date | None] = mapped_column(Date, index=True)

    #: Where it happened, in words. Free text on purpose: half of these are
    #: "the store room" or "Amman, then the site", and neither is a Site row.
    location: Mapped[str | None] = mapped_column(String(300))

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sites.id", ondelete="SET NULL"), index=True
    )
    budget_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("budgets.id", ondelete="SET NULL"), index=True
    )

    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    #: Always filled when there is a lead, account or not — the person who ran
    #: the 2011 season may never have had a login here.
    lead_label: Mapped[str | None] = mapped_column(String(200))
    #: How many people, when naming them all is neither possible nor useful.
    team_size: Mapped[int | None] = mapped_column(Integer)
    #: Who was there, as text. Volunteers and visiting specialists outnumber
    #: accounts on most digs.
    team_notes: Mapped[str | None] = mapped_column(Text)

    #: What came of it. Kept apart from ``summary`` because "what we found" and
    #: "what we did" get asked separately, by different people.
    outcome: Mapped[str | None] = mapped_column(Text)
    #: What went wrong, and what to do differently. The field that makes the
    #: hub worth reading before repeating something.
    lessons: Mapped[str | None] = mapped_column(Text)

    #: The activity this one was copied from, if it was. A repeat keeps the
    #: link so "we have run this five times" is answerable, and so the lead
    #: times from the last run can be shown against this one.
    repeated_from_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id", ondelete="SET NULL"), index=True
    )

    notes: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    project: Mapped[Project | None] = relationship()
    site: Mapped[Site | None] = relationship()
    lead: Mapped[User | None] = relationship(foreign_keys=[lead_id])
    repeated_from: Mapped[Activity | None] = relationship(remote_side="Activity.id")

    equipment: Mapped[list[ActivityEquipment]] = relationship(
        back_populates="activity",
        cascade="all, delete-orphan",
        order_by="ActivityEquipment.position",
    )
    permits: Mapped[list[ActivityPermit]] = relationship(
        back_populates="activity",
        cascade="all, delete-orphan",
        order_by="ActivityPermit.position",
    )
    preparations: Mapped[list[ActivityPreparation]] = relationship(
        back_populates="activity",
        cascade="all, delete-orphan",
        order_by="ActivityPreparation.position",
    )
    costs: Mapped[list[ActivityCost]] = relationship(
        back_populates="activity",
        cascade="all, delete-orphan",
        order_by="ActivityCost.position",
    )
    photos: Mapped[list[ActivityPhoto]] = relationship(
        back_populates="activity",
        cascade="all, delete-orphan",
        order_by="ActivityPhoto.position",
    )

    __table_args__ = (
        CheckConstraint(
            "starts_on IS NULL OR ends_on IS NULL OR ends_on >= starts_on",
            name="ck_activities_ends_after_starts",
        ),
        CheckConstraint("team_size IS NULL OR team_size >= 0", name="ck_activities_team_size"),
        Index("ix_activities_when", "starts_on", "ends_on"),
        Index("ix_activities_kind_status", "kind", "status"),
    )

    @property
    def duration_days(self) -> int | None:
        """How long it ran, inclusive. ``None`` if the dates are incomplete."""
        if self.starts_on is None or self.ends_on is None:
            return None
        return (self.ends_on - self.starts_on).days + 1

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Activity {self.title[:40]} {self.kind.value}>"


class ActivityEquipment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One line of the kit list.

    Either a row in the inventory or a piece of text. Both are real: the
    inventory only goes back as far as the inventory does, and the hub has to
    hold seasons that predate it.
    """

    __tablename__ = "activity_equipment"

    activity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("activities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("equipment.id", ondelete="SET NULL"), index=True
    )
    #: What it was called. Copied from the equipment record when there is one,
    #: so the list still reads correctly after the kit is retired and renamed.
    label: Mapped[str] = mapped_column(String(250), nullable=False)

    quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=1)
    unit: Mapped[str | None] = mapped_column(String(60))

    #: Ours, hired, borrowed, bought for this. Determines whether the line has
    #: a cost against it and whether it has to go back.
    source: Mapped[str | None] = mapped_column(String(120))
    #: How it behaved. "The total station's battery would not hold past 14:00"
    #: is the note that saves the next season a day.
    performance_notes: Mapped[str | None] = mapped_column(Text)
    #: Whether it earned its place. Nullable — unrated is not the same as bad.
    was_essential: Mapped[bool | None] = mapped_column(Boolean)

    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)

    activity: Mapped[Activity] = relationship(back_populates="equipment")
    item: Mapped[Equipment | None] = relationship()

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_activity_equipment_quantity_positive"),
        Index("ix_activity_equipment_order", "activity_id", "position"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ActivityEquipment {self.label[:30]} ×{self.quantity}>"


class ActivityPermit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One piece of permission, and how long it took to get.

    The dates are the point. ``applied_on`` to ``granted_on`` is the lead time
    that decides when planning for the next season has to start, and it is a
    number no institution can produce from memory.
    """

    __tablename__ = "activity_permits"

    activity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("activities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(250), nullable=False)
    #: The ministry, the landowner, the university's ethics committee.
    issuer: Mapped[str | None] = mapped_column(String(250), index=True)
    #: Their reference. What you quote when you chase it.
    reference: Mapped[str | None] = mapped_column(String(160))

    status: Mapped[PermitStatus] = mapped_column(
        _enum(PermitStatus, "permit_status"),
        nullable=False,
        default=PermitStatus.TO_APPLY,
        index=True,
    )

    applied_on: Mapped[date | None] = mapped_column(Date)
    granted_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date, index=True)

    cost: Mapped[float | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))

    #: How far ahead to start next time. Filled from the dates when they are
    #: known, and typed in from experience when they are not — a permit copied
    #: onto a repeat carries this even though its own dates are cleared.
    lead_time_days: Mapped[int | None] = mapped_column(Integer)

    #: The scanned permit itself, filed through the documents module.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    #: Who to talk to. A name and a number beats an office.
    contact: Mapped[str | None] = mapped_column(String(300))

    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)

    activity: Mapped[Activity] = relationship(back_populates="permits")

    __table_args__ = (
        CheckConstraint("cost IS NULL OR cost >= 0", name="ck_activity_permits_cost_not_negative"),
        CheckConstraint(
            "lead_time_days IS NULL OR lead_time_days >= 0",
            name="ck_activity_permits_lead_time_not_negative",
        ),
        CheckConstraint(
            "applied_on IS NULL OR granted_on IS NULL OR granted_on >= applied_on",
            name="ck_activity_permits_granted_after_applied",
        ),
        Index("ix_activity_permits_order", "activity_id", "position"),
    )

    @property
    def days_to_obtain(self) -> int | None:
        """Actual elapsed days from applying to being granted."""
        if self.applied_on is None or self.granted_on is None:
            return None
        return (self.granted_on - self.applied_on).days

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ActivityPermit {self.name[:30]} {self.status.value}>"


class ActivityPreparation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One thing that had to be arranged beforehand.

    Vehicle hire, accommodation, insurance, a tetanus booster, telling the
    landowner. Individually trivial and collectively the reason seasons slip.
    """

    __tablename__ = "activity_preparations"

    activity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("activities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    description: Mapped[str] = mapped_column(String(400), nullable=False)
    #: Loose grouping — "travel", "safety", "people", "site". Free text because
    #: every institution's headings are its own.
    category: Mapped[str | None] = mapped_column(String(120), index=True)

    #: How far before the start date this has to be done. The field that turns
    #: a checklist into a countdown.
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    due_on: Mapped[date | None] = mapped_column(Date, index=True)

    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    done_on: Mapped[date | None] = mapped_column(Date)
    #: Whose job it is. Text, for the same reason as everywhere else here.
    responsible_label: Mapped[str | None] = mapped_column(String(200))

    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)

    activity: Mapped[Activity] = relationship(back_populates="preparations")

    __table_args__ = (
        CheckConstraint(
            "lead_time_days IS NULL OR lead_time_days >= 0",
            name="ck_activity_preparations_lead_time_not_negative",
        ),
        Index("ix_activity_preparations_order", "activity_id", "position"),
        Index("ix_activity_preparations_outstanding", "activity_id", "is_done"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ActivityPreparation {self.description[:30]} {'done' if self.is_done else 'open'}>"


class ActivityCost(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """What one part of it cost.

    Deliberately *not* the same table as :class:`~app.models.management.Expense`.
    An expense is money that left an account and has to reconcile against a
    statement; this is what a thing cost, which is a question you ask about
    activities that were paid for by somebody else, or in cash, or in 2013. A
    cost may point at an expense when the two are the same money, and the
    totals say which lines do.
    """

    __tablename__ = "activity_costs"

    activity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("activities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    description: Mapped[str] = mapped_column(String(400), nullable=False)
    category: Mapped[ExpenseCategory] = mapped_column(
        _enum(ExpenseCategory, "expense_category"),
        nullable=False,
        default=ExpenseCategory.OTHER,
        index=True,
    )

    #: Unit cost × quantity. Stored separately so "hire was 40 a day for nine
    #: days" survives, which is the form the next quote has to be checked in.
    unit_cost: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=1)
    unit: Mapped[str | None] = mapped_column(String(60))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    supplier: Mapped[str | None] = mapped_column(String(250), index=True)
    #: Whether the figure is a real invoice or somebody's recollection. A total
    #: built from estimates should not be presented as if it were accounts.
    is_estimate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: The same money, recorded in the finance module. Set when the two exist.
    expense_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("expenses.id", ondelete="SET NULL"), index=True
    )

    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)

    activity: Mapped[Activity] = relationship(back_populates="costs")

    __table_args__ = (
        CheckConstraint("unit_cost >= 0", name="ck_activity_costs_unit_cost_not_negative"),
        CheckConstraint("quantity > 0", name="ck_activity_costs_quantity_positive"),
        Index("ix_activity_costs_order", "activity_id", "position"),
    )

    @property
    def total(self) -> float:
        """Unit cost times quantity, in this line's currency."""
        from decimal import Decimal

        return Decimal(str(self.unit_cost)) * Decimal(str(self.quantity))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ActivityCost {self.description[:30]} {self.total}{self.currency}>"


class ActivityPhoto(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A photograph attached to an activity.

    A join rather than a column on ``photographs``, because one image is
    routinely the record shot of a find *and* the picture of the season that
    ends up in the report — and because the caption wanted here is not the
    caption on the photograph itself.
    """

    __tablename__ = "activity_photos"

    activity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("activities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    photograph_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("photographs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    caption: Mapped[str | None] = mapped_column(Text)
    #: The one that represents the activity in a list. At most one per
    #: activity, enforced by a partial unique index in the migration.
    is_cover: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    activity: Mapped[Activity] = relationship(back_populates="photos")
    photograph: Mapped[Photograph] = relationship()

    __table_args__ = (
        UniqueConstraint("activity_id", "photograph_id", name="uq_activity_photos_once"),
        Index("ix_activity_photos_order", "activity_id", "position"),
        # At most one cover per activity. Partial, so it constrains only the
        # covers: a plain unique index on ``(activity_id, is_cover)`` would
        # permit one cover *and one non-cover*, which is the opposite of the
        # rule. The endpoint clears the previous cover before setting a new
        # one; this is the guarantee underneath it.
        Index(
            "uq_activity_photos_cover",
            "activity_id",
            unique=True,
            postgresql_where=text("is_cover"),
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ActivityPhoto {self.activity_id} {self.photograph_id}>"
