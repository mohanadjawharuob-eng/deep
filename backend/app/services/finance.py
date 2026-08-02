"""What a budget has left, and what it went on.

Two questions, and the first one has a wrong answer that looks right.

**"How much is left?"** is not the budget minus what has been paid. Money
promised to a supplier cannot be spent again, even though it has not left the
account — so a figure that counts only cleared invoices tells a project
director they have funds they have already committed. That is how a grant gets
overspent by people being careful with it.

So :func:`position` returns three numbers and the difference between them
matters:

- ``paid`` — invoices that have actually gone out.
- ``committed`` — ordered or contracted, not yet paid.
- ``available`` — the award, less both.

``planned`` is reported separately and deliberately excluded from the
subtraction. It is a forecast, and a forecast that quietly reduces the
available balance turns "we might need a second total station" into "we cannot
afford one".

**"What did it go on?"** is :func:`by_category`, which is the report every
funder asks for. It counts committed and paid together, because a funder
asking what their money went on does not mean "only the invoices that cleared
before the report date".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import ExpenseCategory, ExpenseStatus
from app.models.management import Budget, Expense

#: The statuses that reduce what a budget has available. Cancelled spending
#: does not, and neither does planned — see the module docstring.
SPENDS = (ExpenseStatus.COMMITTED, ExpenseStatus.PAID)


@dataclass(slots=True)
class Position:
    """Where a budget stands."""

    amount: Decimal
    paid: Decimal
    committed: Decimal
    planned: Decimal
    currency: str

    @property
    def spent(self) -> Decimal:
        """Everything that reduces the balance: paid and committed together."""
        return self.paid + self.committed

    @property
    def available(self) -> Decimal:
        return self.amount - self.spent

    @property
    def overspent(self) -> bool:
        return self.available < 0

    @property
    def used_percent(self) -> float:
        """How much of the award is gone, for a progress bar.

        A budget of zero is not 0% used and not 100% used; it is a budget
        nobody has set an amount on yet, and drawing a bar for it invents a
        fact. Callers get 0 and are expected to say "no amount set" instead.
        """
        if self.amount <= 0:
            return 0.0
        return float(self.spent / self.amount * 100)


@dataclass(slots=True)
class CategoryLine:
    """One row of the breakdown a funder asks for."""

    category: ExpenseCategory
    amount: Decimal
    count: int


@dataclass(slots=True)
class Summary:
    """Every budget at once, for the module's front page."""

    total: Decimal = Decimal(0)
    spent: Decimal = Decimal(0)
    available: Decimal = Decimal(0)
    #: Budgets whose end date has passed while they still have money on them,
    #: or which are already overspent. Both are worth a person's attention.
    needing_attention: list[uuid.UUID] = field(default_factory=list)
    #: Keyed by currency, because adding a dinar to a dollar is a lie. A
    #: department running a local grant and a foreign one at once is normal.
    by_currency: dict[str, Decimal] = field(default_factory=dict)


def _totals_by_status(session: Session, budget_id: uuid.UUID) -> dict[ExpenseStatus, Decimal]:
    """One query, grouped, rather than one query per status."""
    rows = session.execute(
        select(Expense.status, func.coalesce(func.sum(Expense.amount), 0))
        .where(Expense.budget_id == budget_id)
        .group_by(Expense.status)
    ).all()
    return {status: Decimal(str(total)) for status, total in rows}


def position(session: Session, budget: Budget) -> Position:
    """Where this budget stands, right now."""
    totals = _totals_by_status(session, budget.id)
    zero = Decimal(0)
    return Position(
        amount=Decimal(str(budget.amount or 0)),
        paid=totals.get(ExpenseStatus.PAID, zero),
        committed=totals.get(ExpenseStatus.COMMITTED, zero),
        planned=totals.get(ExpenseStatus.PLANNED, zero),
        currency=budget.currency,
    )


def by_category(
    session: Session,
    budget_id: uuid.UUID,
    *,
    since: date | None = None,
    until: date | None = None,
) -> list[CategoryLine]:
    """The breakdown a funder asks for, largest first.

    Categories with nothing against them are left out. A report listing nine
    headings of zero to say something about three is a report nobody reads to
    the end.
    """
    statement = (
        select(
            Expense.category,
            func.coalesce(func.sum(Expense.amount), 0),
            func.count(Expense.id),
        )
        .where(Expense.budget_id == budget_id, Expense.status.in_(SPENDS))
        .group_by(Expense.category)
    )
    if since is not None:
        statement = statement.where(Expense.spent_on >= since)
    if until is not None:
        statement = statement.where(Expense.spent_on <= until)

    lines = [
        CategoryLine(category=category, amount=Decimal(str(total)), count=count)
        for category, total, count in session.execute(statement).all()
    ]
    return sorted(lines, key=lambda line: line.amount, reverse=True)


def would_overspend(session: Session, budget: Budget, adding: Decimal | float) -> Decimal | None:
    """By how much a new expense would take the budget over, or ``None``.

    Reported rather than refused. A grant genuinely does get overspent, and a
    platform that will not let somebody record what actually happened is a
    platform they keep the real figures outside of — which is worse than an
    overspend anybody can see.
    """
    remaining = position(session, budget).available
    excess = Decimal(str(adding)) - remaining
    return excess if excess > 0 else None


def summarise(session: Session, budget_ids: list[uuid.UUID] | None = None) -> Summary:
    """Every budget at once.

    Totals are kept per currency. Adding a dinar to a dollar produces a number
    that is wrong in a way nobody notices until a funder does.
    """
    statement = select(Budget)
    if budget_ids is not None:
        statement = statement.where(Budget.id.in_(budget_ids))

    summary = Summary()
    today = date.today()

    for budget in session.scalars(statement).all():
        where = position(session, budget)
        summary.total += where.amount
        summary.spent += where.spent
        summary.available += where.available
        summary.by_currency[budget.currency] = (
            summary.by_currency.get(budget.currency, Decimal(0)) + where.available
        )

        expired_with_money_left = (
            budget.ends_on is not None and budget.ends_on < today and where.available > 0
        )
        if where.overspent or expired_with_money_left:
            summary.needing_attention.append(budget.id)

    return summary
