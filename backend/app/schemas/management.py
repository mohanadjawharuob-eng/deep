"""Schemas for budgets, expenses, tasks and the calendar.

A budget's ``spent``, ``committed`` and ``available`` appear on reads and
nowhere on writes. They are summed from the expenses charged against it, and a
form that could set them would make the expenses decorative.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.models.enums import (
    BudgetStatus,
    ExpenseCategory,
    ExpenseStatus,
    TaskPriority,
    TaskStatus,
)
from app.schemas.common import ORMModel

# --------------------------------------------------------------------------
# Budgets
# --------------------------------------------------------------------------


class BudgetBase(BaseModel):
    name: str = Field(min_length=1, max_length=250)
    description: str | None = None
    funder: str | None = Field(default=None, max_length=250)
    grant_reference: str | None = Field(default=None, max_length=160)
    amount: float = Field(default=0, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    starts_on: date | None = None
    ends_on: date | None = None
    project_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    manager_label: str | None = Field(default=None, max_length=200)
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _a_fund_cannot_end_before_it_starts(self) -> BudgetBase:
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("The end date is before the start date")
        return self


class BudgetCreate(BudgetBase):
    code: str = Field(
        min_length=1,
        max_length=80,
        description="The reference the funder uses — what they ask you to quote",
    )
    status: BudgetStatus = BudgetStatus.ACTIVE
    is_public: bool = False


class BudgetUpdate(BudgetBase):
    name: str | None = Field(default=None, min_length=1, max_length=250)
    amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    status: BudgetStatus | None = None
    is_public: bool | None = None


class BudgetSummary(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    funder: str | None = None
    amount: float
    currency: str
    status: BudgetStatus
    starts_on: date | None = None
    ends_on: date | None = None
    project_id: uuid.UUID | None = None
    is_public: bool
    created_at: datetime

    # --- Summed from the expenses, never stored ---------------------------
    paid: float = 0
    committed: float = 0
    #: Forecast only. Deliberately *not* subtracted from `available` — a
    #: forecast that reduces the balance turns "we might need a second total
    #: station" into "we cannot afford one".
    planned: float = 0
    spent: float = 0
    available: float = 0
    used_percent: float = 0
    overspent: bool = False


class BudgetRead(BudgetSummary):
    description: str | None = None
    grant_reference: str | None = None
    manager_id: uuid.UUID | None = None
    manager_label: str | None = None
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None
    owner_id: uuid.UUID | None = None
    updated_at: datetime


class CategoryLine(BaseModel):
    """One row of the breakdown a funder asks for."""

    category: ExpenseCategory
    label: str
    amount: float
    count: int
    #: Share of the spending, so a report can be read without arithmetic.
    percent: float = 0


class BudgetDetail(BudgetRead):
    project_name: str | None = None
    by_category: list[CategoryLine] = Field(default_factory=list)
    expense_count: int = 0
    #: True when the end date has passed and there is money left on it. Worth
    #: surfacing: unspent grant money usually has to be returned, and nobody
    #: finds out by accident in time.
    expired_with_funds: bool = False
    can_edit: bool = False
    can_delete: bool = False


class BudgetTotals(BaseModel):
    """Every budget at once, for the module's front page."""

    total: float = 0
    spent: float = 0
    available: float = 0
    budget_count: int = 0
    #: Available balance per currency. Adding a dinar to a dollar produces a
    #: number that is wrong in a way nobody notices until a funder does.
    by_currency: dict[str, float] = Field(default_factory=dict)
    needing_attention: list[uuid.UUID] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Expenses
# --------------------------------------------------------------------------


class ExpenseBase(BaseModel):
    description: str = Field(min_length=1, max_length=400)
    amount: float = Field(gt=0, description="Must be positive; a refund is not a negative expense")
    category: ExpenseCategory = ExpenseCategory.OTHER
    status: ExpenseStatus = ExpenseStatus.COMMITTED
    spent_on: date
    paid_on: date | None = None
    supplier: str | None = Field(default=None, max_length=250)
    reference: str | None = Field(default=None, max_length=160)
    paid_by_label: str | None = Field(default=None, max_length=200)
    project_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _it_cannot_be_paid_before_it_was_incurred(self) -> ExpenseBase:
        if self.paid_on and self.spent_on and self.paid_on < self.spent_on:
            raise ValueError("The payment date is before the date the money was spent")
        return self


class ExpenseCreate(ExpenseBase):
    #: Copied from the budget when omitted, which is almost always right.
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    is_public: bool = False


class ExpenseUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=400)
    amount: float | None = Field(default=None, gt=0)
    category: ExpenseCategory | None = None
    status: ExpenseStatus | None = None
    spent_on: date | None = None
    paid_on: date | None = None
    supplier: str | None = Field(default=None, max_length=250)
    reference: str | None = Field(default=None, max_length=160)
    paid_by_label: str | None = Field(default=None, max_length=200)
    project_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    notes: str | None = None
    is_public: bool | None = None
    metadata_json: dict[str, Any] | None = None


class ExpenseRead(ORMModel):
    id: uuid.UUID
    budget_id: uuid.UUID
    description: str
    amount: float
    currency: str
    category: ExpenseCategory
    status: ExpenseStatus
    spent_on: date
    paid_on: date | None = None
    supplier: str | None = None
    reference: str | None = None
    paid_by_label: str | None = None
    project_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    notes: str | None = None
    owner_id: uuid.UUID | None = None
    is_public: bool
    created_at: datetime
    updated_at: datetime
    #: Filled where the expense is listed away from its own budget.
    budget_code: str | None = None
    budget_name: str | None = None


class ExpenseCreated(ExpenseRead):
    """A created expense, with a warning if it took the budget over.

    Recording it is never refused. A grant genuinely does get overspent, and a
    platform that will not let somebody write down what happened is one they
    keep the real figures outside of.
    """

    overspent_by: float | None = None
    budget_available_after: float = 0


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------


class TaskBase(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.NORMAL
    assignee_id: uuid.UUID | None = None
    assignee_label: str | None = Field(
        default=None,
        max_length=200,
        description="Their name. Work goes to volunteers who will never sign in.",
    )
    project_id: uuid.UUID | None = None
    resource_type: str | None = Field(default=None, max_length=40)
    resource_id: uuid.UUID | None = None
    due_on: date | None = None
    notes: str | None = None


class TaskCreate(TaskBase):
    is_public: bool = False


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    assignee_id: uuid.UUID | None = None
    assignee_label: str | None = Field(default=None, max_length=200)
    project_id: uuid.UUID | None = None
    due_on: date | None = None
    position: float | None = None
    notes: str | None = None
    is_public: bool | None = None


class TaskRead(ORMModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    status: TaskStatus
    priority: TaskPriority
    assignee_id: uuid.UUID | None = None
    assignee_label: str | None = None
    project_id: uuid.UUID | None = None
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    due_on: date | None = None
    completed_at: datetime | None = None
    position: float
    notes: str | None = None
    owner_id: uuid.UUID | None = None
    is_public: bool
    created_at: datetime
    updated_at: datetime
    #: Days past the due date, when there is one and it has passed and the
    #: task is not finished. Computed, because a date that was fine yesterday
    #: is overdue today and nothing runs overnight to notice.
    days_overdue: int | None = None
    project_name: str | None = None


class TaskBoard(BaseModel):
    """Tasks grouped the way a board draws them."""

    todo: list[TaskRead] = Field(default_factory=list)
    in_progress: list[TaskRead] = Field(default_factory=list)
    blocked: list[TaskRead] = Field(default_factory=list)
    done: list[TaskRead] = Field(default_factory=list)
    overdue_count: int = 0


# --------------------------------------------------------------------------
# Calendar
# --------------------------------------------------------------------------


class EventBase(BaseModel):
    #: Optional only because ``activity_id`` can supply it. One of the two has
    #: to be given, which the validator below enforces — an untitled event
    #: attached to nothing is a coloured block nobody can interpret.
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    kind: str | None = Field(
        default=None, max_length=80, description="Field season, deadline, visit, meeting…"
    )
    starts_at: datetime
    ends_at: datetime | None = None
    all_day: bool = False
    location: str | None = Field(default=None, max_length=300)
    project_id: uuid.UUID | None = None
    budget_id: uuid.UUID | None = None
    activity_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Pick one of the hub's activities and this day becomes part of "
            "it. Anything left blank — the title, where it is, what kind of "
            "thing it is — is filled in from the activity, so adding the next "
            "season to the calendar is one choice rather than five fields."
        ),
    )

    @model_validator(mode="after")
    def _it_cannot_end_before_it_begins(self) -> EventBase:
        if self.ends_at and self.ends_at < self.starts_at:
            raise ValueError("The event ends before it starts")
        return self

    @model_validator(mode="after")
    def _it_has_to_say_what_it_is(self) -> EventBase:
        if not (self.title or "").strip() and self.activity_id is None:
            raise ValueError("Give the event a title, or pick an activity to take one from")
        return self


class EventCreate(EventBase):
    is_public: bool = False


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    kind: str | None = Field(default=None, max_length=80)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    all_day: bool | None = None
    location: str | None = Field(default=None, max_length=300)
    project_id: uuid.UUID | None = None
    budget_id: uuid.UUID | None = None
    activity_id: uuid.UUID | None = None
    is_public: bool | None = None


class EventRead(ORMModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    kind: str | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    all_day: bool
    location: str | None = None
    project_id: uuid.UUID | None = None
    budget_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    is_public: bool
    created_at: datetime
    project_name: str | None = None
    activity_id: uuid.UUID | None = None
    #: What the linked activity is called, so the calendar can say "part of the
    #: 2019 north trench season" without a second request per entry.
    activity_title: str | None = None
    activity_kind: str | None = None
    #: Whether the person reading may change this one. The calendar is open to
    #: everybody, so a screen has to be able to tell which blocks are theirs.
    can_edit: bool = False
