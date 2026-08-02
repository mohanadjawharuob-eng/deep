"""Schemas for the inventory module.

Two rules shape most of what follows.

A consumable's ``quantity`` is readable but never writable. It is the sum of a
ledger, and letting a PATCH set it would make the ledger decorative. Changing
stock goes through :class:`StockMovementCreate`, which says how much and why.

Equipment ``status`` is likewise not something a form sets to ``checked_out``.
Issuing an item is an action with a borrower, a date and a due date attached;
the status is what falls out of it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.models.enums import CalibrationResult, EquipmentStatus, StockReason
from app.schemas.common import ORMModel

# --------------------------------------------------------------------------
# Equipment
# --------------------------------------------------------------------------


class EquipmentBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    category: str | None = Field(default=None, max_length=120)
    manufacturer: str | None = Field(default=None, max_length=160)
    model: str | None = Field(default=None, max_length=160)
    serial_number: str | None = Field(default=None, max_length=160)
    condition_notes: str | None = None

    purchased_on: date | None = None
    purchase_price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    supplier: str | None = Field(default=None, max_length=200)
    warranty_until: date | None = None
    funding_source: str | None = Field(default=None, max_length=200)

    needs_calibration: bool = False
    calibration_interval_days: int | None = Field(default=None, gt=0)
    storage_location_id: uuid.UUID | None = None
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None


class EquipmentCreate(EquipmentBase):
    asset_number: str = Field(
        min_length=1,
        max_length=80,
        description="The number on the item itself — what somebody reads off the case",
    )
    is_public: bool = False
    #: Kit is sometimes catalogued after it has already broken, so "in repair"
    #: and the rest are settable here. "Checked out" is not — an item created
    #: in that state has no loan behind it, and the register would say it is
    #: gone without being able to say who has it. That is precisely the
    #: inconsistency :class:`EquipmentUpdate` refuses; allowing it at creation
    #: would just move the hole one screen earlier.
    status: EquipmentStatus = EquipmentStatus.AVAILABLE
    calibration_due_on: date | None = None

    @model_validator(mode="after")
    def _created_items_are_not_already_on_loan(self) -> EquipmentCreate:
        if self.status is EquipmentStatus.CHECKED_OUT:
            raise ValueError(
                "An item cannot be created as 'checked out', because there "
                "would be no record of who has it. Create it, then issue it."
            )
        return self


class EquipmentUpdate(EquipmentBase):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    needs_calibration: bool | None = None
    is_public: bool | None = None
    #: Repair, retirement and "we cannot find it" are edits. Checking out is
    #: not — that is `/checkouts`, which needs a borrower and a date, and
    #: which is refused for an item somebody else already has.
    status: EquipmentStatus | None = None

    @model_validator(mode="after")
    def _no_borrowing_by_the_back_door(self) -> EquipmentUpdate:
        if self.status is EquipmentStatus.CHECKED_OUT:
            raise ValueError(
                "Setting the status to 'checked out' would record that the item "
                "is gone without recording who has it. Issue it through "
                "/inventory/equipment/{id}/checkouts instead."
            )
        return self


class EquipmentSummary(ORMModel):
    id: uuid.UUID
    asset_number: str
    name: str
    category: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    status: EquipmentStatus
    needs_calibration: bool
    calibration_due_on: date | None = None
    storage_location_id: uuid.UUID | None = None
    is_public: bool
    created_at: datetime


class EquipmentRead(EquipmentSummary):
    description: str | None = None
    condition_notes: str | None = None
    purchased_on: date | None = None
    purchase_price: float | None = None
    currency: str | None = None
    supplier: str | None = None
    warranty_until: date | None = None
    funding_source: str | None = None
    calibration_interval_days: int | None = None
    public_token: str
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None
    owner_id: uuid.UUID | None = None
    updated_at: datetime


class EquipmentDetail(EquipmentRead):
    storage_path: str | None = None
    #: The loan it is out on now, if it is out. The single most useful thing
    #: to know about a piece of kit, so it is not left to a second request.
    open_checkout: CheckoutRead | None = None
    last_calibration: CalibrationRead | None = None
    #: True when the calibration due date has passed. Computed rather than
    #: stored: a date that was fine yesterday is overdue today, and nothing
    #: runs overnight to notice.
    calibration_overdue: bool = False
    can_edit: bool = False
    can_delete: bool = False


# --------------------------------------------------------------------------
# Checkouts
# --------------------------------------------------------------------------


class CheckoutCreate(BaseModel):
    borrower_id: uuid.UUID | None = Field(
        default=None, description="The borrower's account, if they have one"
    )
    borrower_label: str | None = Field(
        default=None,
        max_length=200,
        description="Their name. Filled in from the account when one is given.",
    )
    project_id: uuid.UUID | None = None
    destination: str | None = Field(default=None, max_length=300)
    taken_at: datetime | None = Field(
        default=None, description="Defaults to now. Backdating a loan is normal."
    )
    due_on: date | None = None
    condition_out: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _somebody_has_to_have_it(self) -> CheckoutCreate:
        if self.borrower_id is None and not (self.borrower_label or "").strip():
            raise ValueError("Say who is taking it — an account, a name, or both")
        return self


class CheckoutReturn(BaseModel):
    returned_at: datetime | None = Field(default=None, description="Defaults to now")
    condition_in: str | None = Field(
        default=None,
        description="What state it came back in. Worth a sentence even when nothing is wrong.",
    )
    #: Where it went back to. Defaults to the item's home shelf.
    storage_location_id: uuid.UUID | None = None
    notes: str | None = None


class CheckoutRead(ORMModel):
    id: uuid.UUID
    equipment_id: uuid.UUID
    borrower_id: uuid.UUID | None = None
    borrower_label: str
    project_id: uuid.UUID | None = None
    destination: str | None = None
    taken_at: datetime
    due_on: date | None = None
    returned_at: datetime | None = None
    condition_out: str | None = None
    condition_in: str | None = None
    notes: str | None = None
    kit_id: uuid.UUID | None = None
    created_at: datetime


class CheckoutWithEquipment(CheckoutRead):
    """A loan with enough of the item attached to be listed on its own."""

    asset_number: str | None = None
    equipment_name: str | None = None
    #: Days past the due date, when there is one and it has passed.
    days_overdue: int | None = None


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------


class CalibrationCreate(BaseModel):
    performed_on: date
    performed_by: str | None = Field(
        default=None, max_length=200, description="Usually the laboratory that did it"
    )
    certificate_number: str | None = Field(default=None, max_length=160)
    result: CalibrationResult = CalibrationResult.PASSED
    next_due_on: date | None = Field(
        default=None,
        description="From the certificate. Worked out from the item's interval if omitted.",
    )
    cost: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    notes: str | None = None


class CalibrationRead(ORMModel):
    id: uuid.UUID
    equipment_id: uuid.UUID
    performed_on: date
    performed_by: str | None = None
    certificate_number: str | None = None
    result: CalibrationResult
    next_due_on: date | None = None
    cost: float | None = None
    currency: str | None = None
    notes: str | None = None
    created_at: datetime


# --------------------------------------------------------------------------
# Consumables
# --------------------------------------------------------------------------


class ConsumableBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    category: str | None = Field(default=None, max_length=120)
    unit: str = Field(
        default="each",
        min_length=1,
        max_length=60,
        description="What one of it is — bag, box of 100, roll, metre",
    )
    reorder_level: float | None = Field(
        default=None, ge=0, description="Below this it appears on the reorder list"
    )
    supplier: str | None = Field(default=None, max_length=200)
    supplier_reference: str | None = Field(default=None, max_length=120)
    unit_cost: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    storage_location_id: uuid.UUID | None = None
    expires_on: date | None = None
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None


class ConsumableCreate(ConsumableBase):
    code: str = Field(min_length=1, max_length=80)
    is_active: bool = True
    is_public: bool = False
    #: What is on the shelf when the line is first written down. Recorded as
    #: an opening stock-take movement, not as a bare number, so the ledger
    #: begins where the stock does.
    opening_quantity: float = Field(default=0, ge=0)


class ConsumableUpdate(ConsumableBase):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    unit: str | None = Field(default=None, min_length=1, max_length=60)
    is_active: bool | None = None
    is_public: bool | None = None
    # `quantity` is deliberately absent. Changing stock is a movement, with a
    # reason attached; a form that could set the total directly would make the
    # ledger behind it worthless.


class ConsumableSummary(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    category: str | None = None
    unit: str
    quantity: float
    reorder_level: float | None = None
    storage_location_id: uuid.UUID | None = None
    expires_on: date | None = None
    is_active: bool
    is_public: bool
    created_at: datetime


class ConsumableRead(ConsumableSummary):
    description: str | None = None
    supplier: str | None = None
    supplier_reference: str | None = None
    unit_cost: float | None = None
    currency: str | None = None
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None
    owner_id: uuid.UUID | None = None
    updated_at: datetime


class ConsumableDetail(ConsumableRead):
    storage_path: str | None = None
    #: True when the quantity has fallen to or below the reorder level.
    needs_reorder: bool = False
    #: True when the expiry date has passed. Adhesives and chemicals go off,
    #: and a conservator needs to know before using them, not after.
    expired: bool = False
    can_edit: bool = False
    can_delete: bool = False


class StockMovementCreate(BaseModel):
    change: float = Field(
        description="Signed: positive for stock arriving, negative for stock leaving"
    )
    reason: StockReason = StockReason.OTHER
    project_id: uuid.UUID | None = None
    issued_to_label: str | None = Field(default=None, max_length=200)
    notes: str | None = None
    occurred_at: datetime | None = Field(default=None, description="Defaults to now")

    @model_validator(mode="after")
    def _a_change_of_nothing_is_not_an_event(self) -> StockMovementCreate:
        if self.change == 0:
            raise ValueError(
                "A movement of zero records nothing. Say how much came in or went out."
            )
        return self


class StockTake(BaseModel):
    """What is actually on the shelf, counted.

    The difference from the recorded total is written to the ledger as a
    correction, so the discrepancy is visible rather than absorbed.
    """

    counted: float = Field(ge=0)
    notes: str | None = None
    occurred_at: datetime | None = None


class StockMovementRead(ORMModel):
    id: uuid.UUID
    consumable_id: uuid.UUID
    change: float
    balance_after: float
    reason: StockReason
    project_id: uuid.UUID | None = None
    issued_to_label: str | None = None
    kit_id: uuid.UUID | None = None
    notes: str | None = None
    occurred_at: datetime
    recorded_by_id: uuid.UUID | None = None
    recorded_by_label: str | None = None
    created_at: datetime

    #: Filled where the movement is shown away from its own stock line — on a
    #: kit, "50 issued" says nothing without them. Left empty on a consumable's
    #: own ledger, where the page already names it.
    consumable_code: str | None = None
    consumable_name: str | None = None
    unit: str | None = None


# --------------------------------------------------------------------------
# Kits
# --------------------------------------------------------------------------


class KitTemplateLineCreate(BaseModel):
    equipment_id: uuid.UUID | None = None
    consumable_id: uuid.UUID | None = None
    equipment_category: str | None = Field(
        default=None,
        max_length=120,
        description="Any item of this kind will do — 'two cameras', not 'camera 3'",
    )
    quantity: float = Field(default=1, gt=0)
    is_optional: bool = False
    notes: str | None = None
    position: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _one_thing_per_line(self) -> KitTemplateLineCreate:
        named = [
            self.equipment_id is not None,
            self.consumable_id is not None,
            bool((self.equipment_category or "").strip()),
        ]
        if sum(named) != 1:
            raise ValueError(
                "A line names exactly one of: a specific item, a consumable, "
                "or a category of item"
            )
        return self


class KitTemplateLineRead(ORMModel):
    id: uuid.UUID
    position: int
    equipment_id: uuid.UUID | None = None
    consumable_id: uuid.UUID | None = None
    equipment_category: str | None = None
    quantity: float
    is_optional: bool
    notes: str | None = None
    #: Resolved for display, so a packing list reads as words.
    label: str | None = None


class KitTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    is_public: bool = False
    lines: list[KitTemplateLineCreate] = Field(default_factory=list)


class KitTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    is_active: bool | None = None
    is_public: bool | None = None
    #: Given, this replaces the whole list. A packing list is edited as a
    #: list — reordering and removing lines through per-line calls is more
    #: round trips and more ways to end up half-applied.
    lines: list[KitTemplateLineCreate] | None = None


class KitTemplateSummary(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    is_active: bool
    is_public: bool
    line_count: int = 0
    created_at: datetime


class KitTemplateDetail(KitTemplateSummary):
    lines: list[KitTemplateLineRead] = Field(default_factory=list)
    owner_id: uuid.UUID | None = None
    updated_at: datetime
    can_edit: bool = False
    can_delete: bool = False


class KitBuild(BaseModel):
    """Fill a packing list and take it out of the door."""

    name: str | None = Field(
        default=None, max_length=200, description="Defaults to the template's name and the date"
    )
    project_id: uuid.UUID | None = None
    issued_to_id: uuid.UUID | None = None
    issued_to_label: str | None = Field(default=None, max_length=200)
    destination: str | None = Field(default=None, max_length=300)
    issued_at: datetime | None = None
    due_on: date | None = None
    notes: str | None = None
    #: Refuse the whole build unless every required line can be filled. Off by
    #: default: a kit that is nine tenths ready is still the kit going out this
    #: morning, and the shortfall list is what the note is for.
    all_or_nothing: bool = False


class KitShortfall(BaseModel):
    """One thing the build could not supply."""

    line_id: uuid.UUID | None = None
    what: str
    wanted: float
    supplied: float
    reason: str
    is_optional: bool = False


class KitSummary(ORMModel):
    id: uuid.UUID
    name: str
    template_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    issued_to_label: str
    destination: str | None = None
    issued_at: datetime
    due_on: date | None = None
    returned_at: datetime | None = None
    is_public: bool
    created_at: datetime


class KitDetail(KitSummary):
    issued_to_id: uuid.UUID | None = None
    notes: str | None = None
    shortfalls: list[KitShortfall] = Field(default_factory=list)
    checkouts: list[CheckoutWithEquipment] = Field(default_factory=list)
    stock_movements: list[StockMovementRead] = Field(default_factory=list)
    #: How many of the kit's items are still out. Zero means it can be closed.
    outstanding_items: int = 0
    owner_id: uuid.UUID | None = None
    updated_at: datetime
    can_edit: bool = False
    can_delete: bool = False


class KitReturn(BaseModel):
    """Bring back everything in a kit that is still out."""

    returned_at: datetime | None = None
    condition_in: str | None = None
    notes: str | None = None
