"""Schemas for the activity hub.

Two shapes appear here that are worth naming.

``…Read`` models carry a **label** beside every foreign key — ``equipment_name``
next to ``equipment_id``, ``project_name`` next to ``project_id``. The screen
should never have to make a second round trip to render a list, and the label is
also what survives into a printed brief, where an identifier is worthless.

The **cost totals** are per currency and never summed across them, matching
:class:`~app.services.logistics.Totals`. There is no single ``total`` field on
purpose: offering one would mean choosing a currency to express it in, and any
choice is wrong for somebody.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models.enums import ActivityKind, ActivityStatus, ExpenseCategory, PermitStatus
from app.schemas.common import ORMModel

# --------------------------------------------------------------------------
# The activity itself
# --------------------------------------------------------------------------


class ActivityBase(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    summary: str | None = None
    kind: ActivityKind = ActivityKind.OTHER
    starts_on: date | None = None
    ends_on: date | None = None
    location: str | None = Field(default=None, max_length=300)
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    budget_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    lead_label: str | None = Field(default=None, max_length=200)
    team_size: int | None = Field(default=None, ge=0)
    team_notes: str | None = None
    outcome: str | None = None
    lessons: str | None = None
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _it_cannot_end_before_it_starts(self) -> ActivityBase:
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("The end date is before the start date")
        return self


class ActivityCreate(ActivityBase):
    status: ActivityStatus = ActivityStatus.PLANNED
    is_public: bool = False


class ActivityUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    summary: str | None = None
    kind: ActivityKind | None = None
    status: ActivityStatus | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    location: str | None = Field(default=None, max_length=300)
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    budget_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    lead_label: str | None = Field(default=None, max_length=200)
    team_size: int | None = Field(default=None, ge=0)
    team_notes: str | None = None
    outcome: str | None = None
    lessons: str | None = None
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None
    is_public: bool | None = None


class ActivitySummary(ORMModel):
    """One row of the hub's list."""

    id: uuid.UUID
    title: str
    kind: ActivityKind
    status: ActivityStatus
    starts_on: date | None = None
    ends_on: date | None = None
    location: str | None = None
    lead_label: str | None = None
    team_size: int | None = None
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    is_public: bool
    owner_id: uuid.UUID | None = None
    created_at: datetime

    duration_days: int | None = None
    project_name: str | None = None
    site_name: str | None = None
    photo_count: int = 0
    equipment_count: int = 0
    #: Permits and preparations not yet dealt with, so a list can mark the
    #: activities somebody still has work to do on.
    outstanding_count: int = 0
    cover_photo_id: uuid.UUID | None = None


# --------------------------------------------------------------------------
# Equipment
# --------------------------------------------------------------------------
class ActivityEquipmentBase(BaseModel):
    equipment_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "A row in the inventory, when the kit is one this platform holds. "
            "Leave it out and give a label instead for anything borrowed, "
            "hired, or used before the inventory existed."
        ),
    )
    label: str | None = Field(default=None, max_length=250)
    quantity: float = Field(default=1, gt=0)
    unit: str | None = Field(default=None, max_length=60)
    source: str | None = Field(
        default=None, max_length=120, description="Ours, hired, borrowed, bought for this…"
    )
    performance_notes: str | None = None
    was_essential: bool | None = None
    position: int = 0
    notes: str | None = None

    @model_validator(mode="after")
    def _something_has_to_name_it(self) -> ActivityEquipmentBase:
        if self.equipment_id is None and not (self.label or "").strip():
            raise ValueError("Give either a piece of equipment or a name for it")
        return self


class ActivityEquipmentCreate(ActivityEquipmentBase):
    pass


class ActivityEquipmentUpdate(BaseModel):
    equipment_id: uuid.UUID | None = None
    label: str | None = Field(default=None, min_length=1, max_length=250)
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=60)
    source: str | None = Field(default=None, max_length=120)
    performance_notes: str | None = None
    was_essential: bool | None = None
    position: int | None = None
    notes: str | None = None


class ActivityEquipmentRead(ORMModel):
    id: uuid.UUID
    activity_id: uuid.UUID
    equipment_id: uuid.UUID | None = None
    label: str
    quantity: float
    unit: str | None = None
    source: str | None = None
    performance_notes: str | None = None
    was_essential: bool | None = None
    position: int
    notes: str | None = None
    #: What the inventory calls it *now*, which may differ from the label kept
    #: on the line. Both are shown: one is the record, the other is the link.
    equipment_name: str | None = None
    asset_number: str | None = None
    #: False when the linked equipment has since been deleted or retired — a
    #: kit list that silently drops a line is a kit list that misleads.
    equipment_exists: bool = True


# --------------------------------------------------------------------------
# Permits
# --------------------------------------------------------------------------
class ActivityPermitBase(BaseModel):
    name: str = Field(min_length=1, max_length=250)
    issuer: str | None = Field(default=None, max_length=250)
    reference: str | None = Field(default=None, max_length=160)
    status: PermitStatus = PermitStatus.TO_APPLY
    applied_on: date | None = None
    granted_on: date | None = None
    expires_on: date | None = None
    cost: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    lead_time_days: int | None = Field(
        default=None,
        ge=0,
        description="How far ahead to start next time. Learned from the dates when they are known.",
    )
    document_id: uuid.UUID | None = None
    contact: str | None = Field(default=None, max_length=300)
    position: int = 0
    notes: str | None = None

    @model_validator(mode="after")
    def _it_cannot_be_granted_before_it_was_asked_for(self) -> ActivityPermitBase:
        if self.applied_on and self.granted_on and self.granted_on < self.applied_on:
            raise ValueError("It was granted before it was applied for")
        return self


class ActivityPermitCreate(ActivityPermitBase):
    pass


class ActivityPermitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=250)
    issuer: str | None = Field(default=None, max_length=250)
    reference: str | None = Field(default=None, max_length=160)
    status: PermitStatus | None = None
    applied_on: date | None = None
    granted_on: date | None = None
    expires_on: date | None = None
    cost: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    lead_time_days: int | None = Field(default=None, ge=0)
    document_id: uuid.UUID | None = None
    contact: str | None = Field(default=None, max_length=300)
    position: int | None = None
    notes: str | None = None


class ActivityPermitRead(ORMModel):
    id: uuid.UUID
    activity_id: uuid.UUID
    name: str
    issuer: str | None = None
    reference: str | None = None
    status: PermitStatus
    applied_on: date | None = None
    granted_on: date | None = None
    expires_on: date | None = None
    cost: float | None = None
    currency: str | None = None
    lead_time_days: int | None = None
    document_id: uuid.UUID | None = None
    contact: str | None = None
    position: int
    notes: str | None = None
    #: Elapsed days from applying to being granted — the number the whole
    #: module exists to be able to produce.
    days_to_obtain: int | None = None
    #: Days until it expires; negative means it already has.
    days_until_expiry: int | None = None


# --------------------------------------------------------------------------
# Preparations
# --------------------------------------------------------------------------
class ActivityPreparationBase(BaseModel):
    description: str = Field(min_length=1, max_length=400)
    category: str | None = Field(
        default=None, max_length=120, description="Travel, safety, people, site…"
    )
    lead_time_days: int | None = Field(default=None, ge=0)
    due_on: date | None = None
    is_done: bool = False
    done_on: date | None = None
    responsible_label: str | None = Field(default=None, max_length=200)
    position: int = 0
    notes: str | None = None


class ActivityPreparationCreate(ActivityPreparationBase):
    pass


class ActivityPreparationUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=400)
    category: str | None = Field(default=None, max_length=120)
    lead_time_days: int | None = Field(default=None, ge=0)
    due_on: date | None = None
    is_done: bool | None = None
    done_on: date | None = None
    responsible_label: str | None = Field(default=None, max_length=200)
    position: int | None = None
    notes: str | None = None


class ActivityPreparationRead(ORMModel):
    id: uuid.UUID
    activity_id: uuid.UUID
    description: str
    category: str | None = None
    lead_time_days: int | None = None
    due_on: date | None = None
    is_done: bool
    done_on: date | None = None
    responsible_label: str | None = None
    position: int
    notes: str | None = None
    days_until_due: int | None = None


# --------------------------------------------------------------------------
# Costs
# --------------------------------------------------------------------------
class ActivityCostBase(BaseModel):
    description: str = Field(min_length=1, max_length=400)
    category: ExpenseCategory = ExpenseCategory.OTHER
    unit_cost: float = Field(ge=0)
    quantity: float = Field(default=1, gt=0)
    unit: str | None = Field(
        default=None, max_length=60, description="Per day, per person, per litre…"
    )
    currency: str = Field(default="USD", min_length=3, max_length=3)
    supplier: str | None = Field(default=None, max_length=250)
    is_estimate: bool = False
    expense_id: uuid.UUID | None = None
    position: int = 0
    notes: str | None = None


class ActivityCostCreate(ActivityCostBase):
    pass


class ActivityCostUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=400)
    category: ExpenseCategory | None = None
    unit_cost: float | None = Field(default=None, ge=0)
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=60)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    supplier: str | None = Field(default=None, max_length=250)
    is_estimate: bool | None = None
    expense_id: uuid.UUID | None = None
    position: int | None = None
    notes: str | None = None


class ActivityCostRead(ORMModel):
    id: uuid.UUID
    activity_id: uuid.UUID
    description: str
    category: ExpenseCategory
    unit_cost: float
    quantity: float
    unit: str | None = None
    currency: str
    supplier: str | None = None
    is_estimate: bool
    expense_id: uuid.UUID | None = None
    position: int
    notes: str | None = None
    #: Unit cost times quantity, computed rather than stored.
    total: float = 0.0


# --------------------------------------------------------------------------
# Photographs
# --------------------------------------------------------------------------
class ActivityPhotoCreate(BaseModel):
    photograph_id: uuid.UUID
    caption: str | None = None
    is_cover: bool = False
    position: int = 0


class ActivityPhotoUpdate(BaseModel):
    caption: str | None = None
    is_cover: bool | None = None
    position: int | None = None


class ActivityPhotoRead(ORMModel):
    id: uuid.UUID
    activity_id: uuid.UUID
    photograph_id: uuid.UUID
    caption: str | None = None
    is_cover: bool
    position: int
    title: str | None = None
    thumbnail_url: str | None = None
    taken_at: datetime | None = None
    photographer: str | None = None


# --------------------------------------------------------------------------
# Reading one, with everything on it
# --------------------------------------------------------------------------
class CurrencyLine(BaseModel):
    """What one currency's worth of an activity came to."""

    currency: str
    amount: float
    estimated_amount: float = 0.0


class CostSummary(BaseModel):
    """Never a single figure. See the module docstring."""

    by_currency: list[CurrencyLine] = Field(default_factory=list)
    line_count: int = 0
    estimate_count: int = 0
    linked_to_expenses: int = 0
    any_estimates: bool = False


class OutstandingSummary(BaseModel):
    permits: list[str] = Field(default_factory=list)
    preparations: list[str] = Field(default_factory=list)
    #: Items whose usual lead time no longer fits before the start date.
    too_late: list[str] = Field(default_factory=list)
    longest_lead_days: int | None = None
    is_clear: bool = True
    #: False once the activity is over or cancelled. The same unticked box
    #: means two different things either side of this: before, it is a task;
    #: after, it is a record of something that never got done — and a screen
    #: must not tell a finished season it is running out of time.
    is_actionable: bool = True


class ActivityDetail(ActivitySummary):
    summary: str | None = None
    team_notes: str | None = None
    outcome: str | None = None
    lessons: str | None = None
    notes: str | None = None
    budget_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    metadata_json: dict[str, Any] | None = None
    updated_at: datetime | None = None

    equipment: list[ActivityEquipmentRead] = Field(default_factory=list)
    permits: list[ActivityPermitRead] = Field(default_factory=list)
    preparations: list[ActivityPreparationRead] = Field(default_factory=list)
    costs: list[ActivityCostRead] = Field(default_factory=list)
    photos: list[ActivityPhotoRead] = Field(default_factory=list)

    cost_summary: CostSummary = Field(default_factory=CostSummary)
    outstanding: OutstandingSummary = Field(default_factory=OutstandingSummary)

    #: What this was copied from, if it was, and how many have been copied from
    #: it. "We have run this five times" is a fact worth showing.
    repeated_from_id: uuid.UUID | None = None
    repeated_from_title: str | None = None
    repeat_count: int = 0

    can_edit: bool = False
    can_delete: bool = False


# --------------------------------------------------------------------------
# The dropdown, the repeat and the brief
# --------------------------------------------------------------------------
class ActivityOption(BaseModel):
    """One entry in the "pick a previous activity" dropdown.

    Deliberately small. It is fetched by the calendar on every new event, by
    anyone signed in, and it must not carry costs or notes to somebody who is
    only choosing a name from a list.
    """

    id: uuid.UUID
    title: str
    kind: ActivityKind
    status: ActivityStatus
    starts_on: date | None = None
    location: str | None = None
    #: "Excavation · 2019-06-01 · North trench", ready to draw.
    label: str


class RepeatRequest(BaseModel):
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=300,
        description="Defaults to the original's title with '(repeat)' after it",
    )
    starts_on: date | None = None
    ends_on: date | None = Field(
        default=None,
        description=(
            "Left out, it is worked out from the original's length, so a "
            "twelve-day season stays twelve days."
        ),
    )
    copy_costs: bool = Field(
        default=True,
        description=(
            "Costs come across as estimates, because last year's price is an "
            "estimate of this year's."
        ),
    )

    @model_validator(mode="after")
    def _it_cannot_end_before_it_starts(self) -> RepeatRequest:
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("The end date is before the start date")
        return self


class BriefRequest(BaseModel):
    """Sending the logistics out as an e-mail."""

    to: list[EmailStr] = Field(min_length=1, max_length=25)
    subject: str | None = Field(default=None, max_length=300)
    #: Put above the brief. For "here is what the March trip needs — can you
    #: sign off the vehicle hire by Friday".
    message: str | None = None


class BriefResult(BaseModel):
    sent: bool
    detail: str
    recipients: list[str] = Field(default_factory=list)
    #: Returned whether or not the mail went out, so a site machine with no
    #: outbound mail can still show the text to copy by hand.
    brief: str = ""


class HubSummary(BaseModel):
    """The hub's front page."""

    total: int = 0
    by_kind: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    upcoming: list[ActivitySummary] = Field(default_factory=list)
    recent: list[ActivitySummary] = Field(default_factory=list)
    #: Activities with permits or preparations still outstanding, soonest
    #: first. The list somebody should be looking at.
    needing_attention: list[ActivitySummary] = Field(default_factory=list)
    #: Permits granted and now within a month of running out.
    expiring_permits: list[ActivityPermitRead] = Field(default_factory=list)
