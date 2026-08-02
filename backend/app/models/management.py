"""Management: money, and the work that has to happen.

Three things an excavation runs on besides finds — what it can spend, what it
has spent, and what somebody still has to do.

:class:`Budget`
    A fund: a grant, an institutional allocation, a contract. Money in.

:class:`Expense`
    One piece of spending charged against a fund. Money out.

:class:`Task`
    A piece of work with somebody's name on it and a date.

The distinction that shapes the money side is **committed versus paid**. Money
promised to a supplier cannot be spent again, even though it has not left the
account yet — a budget that counts only what has cleared tells a project
director they have funds they have already spent, which is how a grant is
overspent by people being careful.

So a budget has three numbers, not one:

- **spent** — invoices actually paid.
- **committed** — ordered or contracted, not yet paid.
- **available** — the total, less both.

None of them are stored. They are summed from the expenses on read, because a
stored total is a total that can drift from the rows behind it, and money is
the last place to accept that. There are orders of magnitude fewer expense
rows than there are stock movements, so the sum is cheap.
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
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, OwnedRecordMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    BudgetStatus,
    ExpenseCategory,
    ExpenseStatus,
    TaskPriority,
    TaskStatus,
)

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User


class Budget(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """One fund: a grant, an allocation, a contract."""

    __tablename__ = "budgets"

    #: The reference the funder uses. It is what appears on their
    #: correspondence and what they ask you to quote, so it is the identity.
    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)

    #: Who is paying. Free text: a funder list would be out of date within a
    #: season, and the name on the agreement is the name that matters.
    funder: Mapped[str | None] = mapped_column(String(250), index=True)
    #: Their reference for the award, where it differs from ``code``.
    grant_reference: Mapped[str | None] = mapped_column(String(160))

    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    #: Held per budget, not per institution. A department routinely runs a
    #: local grant and a foreign one at the same time, and converting them into
    #: one currency for storage loses the number the funder will audit.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    starts_on: Mapped[date | None] = mapped_column(Date, index=True)
    #: When spending has to stop. Most grants have one, and overrunning it is
    #: the expensive kind of mistake.
    ends_on: Mapped[date | None] = mapped_column(Date, index=True)

    status: Mapped[BudgetStatus] = mapped_column(
        Enum(BudgetStatus, name="budget_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=BudgetStatus.ACTIVE,
        index=True,
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    #: Who signs it off. A name rather than only an account, because the
    #: principal investigator on a grant is often not a platform user.
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    manager_label: Mapped[str | None] = mapped_column(String(200))

    notes: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    project: Mapped[Project | None] = relationship()
    manager: Mapped[User | None] = relationship(foreign_keys=[manager_id])
    expenses: Mapped[list[Expense]] = relationship(
        back_populates="budget",
        cascade="all, delete-orphan",
        order_by="Expense.spent_on.desc()",
    )

    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_budgets_amount_not_negative"),
        CheckConstraint(
            "starts_on IS NULL OR ends_on IS NULL OR ends_on >= starts_on",
            name="ck_budgets_ends_after_starts",
        ),
        Index("ix_budgets_status_project", "status", "project_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Budget {self.code} {self.amount}{self.currency}>"


class Expense(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """One piece of spending, charged against one fund."""

    __tablename__ = "expenses"

    budget_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("budgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    description: Mapped[str] = mapped_column(String(400), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    #: Copied from the budget on creation. Stored rather than inherited so that
    #: a historical line keeps the currency it was actually incurred in even if
    #: the budget is later corrected.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    category: Mapped[ExpenseCategory] = mapped_column(
        Enum(
            ExpenseCategory,
            name="expense_category",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ExpenseCategory.OTHER,
        index=True,
    )
    status: Mapped[ExpenseStatus] = mapped_column(
        Enum(ExpenseStatus, name="expense_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ExpenseStatus.COMMITTED,
        index=True,
    )

    #: When the money was spent or committed — not when it was typed in. A
    #: bookkeeper catching up on Friday must not distort a monthly report.
    spent_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    paid_on: Mapped[date | None] = mapped_column(Date, index=True)

    supplier: Mapped[str | None] = mapped_column(String(250), index=True)
    #: Invoice or receipt number. What an auditor asks for by name.
    reference: Mapped[str | None] = mapped_column(String(160), index=True)
    #: Who paid out of their own pocket and needs reimbursing. Text, because
    #: it is as often a volunteer as a member of staff.
    paid_by_label: Mapped[str | None] = mapped_column(String(200))

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    #: The scanned receipt, filed through the documents module.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )

    notes: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    budget: Mapped[Budget] = relationship(back_populates="expenses")
    project: Mapped[Project | None] = relationship()

    __table_args__ = (
        # Zero is not a piece of spending, and a negative one is a refund
        # pretending to be an expense — which makes a category breakdown lie.
        # Refunds are their own expense with a negative-sounding description
        # and a cancelled status, or a correction to the original line.
        CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),
        CheckConstraint(
            "paid_on IS NULL OR paid_on >= spent_on", name="ck_expenses_paid_after_spent"
        ),
        Index("ix_expenses_budget_status", "budget_id", "status"),
        Index("ix_expenses_reporting", "budget_id", "category", "spent_on"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Expense {self.amount}{self.currency} {self.description[:30]}>"


class Task(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """A piece of work with somebody's name on it."""

    __tablename__ = "tasks"

    title: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)

    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=TaskStatus.TODO,
        index=True,
    )
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority, name="task_priority", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=TaskPriority.NORMAL,
        index=True,
    )

    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    #: Always filled when there is an assignee, account or not. Work is
    #: routinely given to a volunteer or a visiting specialist who will never
    #: log in, and a task list that can only name staff is a list with holes.
    assignee_label: Mapped[str | None] = mapped_column(String(200))

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    #: What the task is about, if it is about one record. Polymorphic in the
    #: same shape as the rest of the platform: "photograph these forty sherds"
    #: hangs off the context they came from.
    resource_type: Mapped[str | None] = mapped_column(String(40))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)

    due_on: Mapped[date | None] = mapped_column(Date, index=True)
    #: Set when the status becomes done, cleared if it is reopened, so
    #: "finished last week" is answerable without reading the log.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    #: Ordering within a list, so a person can put their day in the order they
    #: mean to work it rather than the order things were typed.
    position: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)

    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])
    completed_by: Mapped[User | None] = relationship(foreign_keys=[completed_by_id])
    project: Mapped[Project | None] = relationship()

    __table_args__ = (
        Index("ix_tasks_assignee_status", "assignee_id", "status"),
        Index("ix_tasks_project_status", "project_id", "status"),
        Index("ix_tasks_due", "status", "due_on"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Task {self.title[:40]} {self.status.value}>"


class CalendarEvent(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """Something happening on a date: a season, a deadline, a visit."""

    __tablename__ = "calendar_events"

    title: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    #: Free text against a suggested set — "field season", "deadline",
    #: "visit", "meeting". A closed list here would be guessing at how one
    #: institution runs its year.
    kind: Mapped[str | None] = mapped_column(String(80), index=True)

    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    #: A field season is "June to August", not "09:00 on 1 June". Storing the
    #: distinction means a calendar can draw it as a band rather than pretend
    #: to a precision nobody meant.
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    location: Mapped[str | None] = mapped_column(String(300))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    budget_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("budgets.id", ondelete="SET NULL"), index=True
    )
    #: The undertaking this date belongs to, if any. Set by picking a previous
    #: activity from the dropdown when adding an event, which is what makes the
    #: calendar the front door to the hub rather than a separate list of dates:
    #: from one entry you can reach the kit list, the permits and the costings
    #: of the last time the same thing was done.
    #:
    #: ``SET NULL`` rather than ``CASCADE``: deleting an activity must not
    #: silently take days off everybody's calendar.
    activity_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id", ondelete="SET NULL"), index=True
    )

    project: Mapped[Project | None] = relationship()

    __table_args__ = (
        CheckConstraint(
            "ends_at IS NULL OR ends_at >= starts_at", name="ck_events_ends_after_starts"
        ),
        Index("ix_events_span", "starts_at", "ends_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CalendarEvent {self.title[:40]} {self.starts_at:%Y-%m-%d}>"
