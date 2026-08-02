"""Turning an activity into something you can act on.

Three jobs, and they are the reason the hub exists rather than being a folder
of notes:

:func:`brief`
    The whole activity as plain text — kit, permissions, preparations, costs —
    in a form that can be pasted into an e-mail, printed and taken to a
    meeting, or sent to somebody who has no account here. Plain text on
    purpose. Every mail client, every phone and every printer renders it the
    same, and a logistics brief that only opens in one program is a brief that
    arrives at the wrong moment.

:func:`totals`
    What it cost, per currency. Never summed across currencies: adding a dinar
    to a dollar produces a number that is wrong in a way nobody notices until a
    funder does. Estimates are counted and reported separately so a figure
    built from recollection is never presented as accounts.

:func:`repeat`
    Copy a past activity into a new one, dates shifted, permits reset to
    needing re-application and preparations unticked. This is the automatic
    workflow: doing the same thing again should start from what it took last
    time, not from an empty form.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activities import (
    Activity,
    ActivityCost,
    ActivityEquipment,
    ActivityPermit,
    ActivityPreparation,
)
from app.models.enums import ActivityStatus, PermitStatus
from app.models.user import User


def tidy(value: Decimal | float | int | None) -> str:
    """Format a quantity without the trailing zeros a Decimal drags along.

    ``Decimal("1.000")`` formatted with ``:g`` is still ``1.000`` — the format
    spec respects the stored precision. Left alone, a kit list reads
    "1.000 × total station", which looks like a machine wrote it because one
    did.
    """
    if value is None:
        return ""
    number = Decimal(str(value))
    if number == number.to_integral_value():
        return str(number.to_integral_value())
    return str(number.normalize())


def money(value: Decimal | float | int) -> str:
    """Two decimal places, always. Money with one is money somebody mistyped."""
    return f"{Decimal(str(value)):.2f}"


# --------------------------------------------------------------------------
# What it cost
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Totals:
    """Costs added up the only way that is safe: per currency."""

    #: ``{"USD": Decimal("1240.00"), "JOD": Decimal("300.00")}``
    by_currency: dict[str, Decimal] = field(default_factory=dict)
    #: The estimated part of each currency's total, so a screen can say how
    #: much of the figure is somebody's memory.
    estimated_by_currency: dict[str, Decimal] = field(default_factory=dict)
    line_count: int = 0
    estimate_count: int = 0
    #: Lines that also exist as an :class:`~app.models.management.Expense`.
    #: The rest were paid by somebody else, in cash, or before this platform.
    linked_to_expenses: int = 0

    @property
    def any_estimates(self) -> bool:
        return self.estimate_count > 0

    def as_text(self) -> str:
        """One line per currency, for the brief."""
        if not self.by_currency:
            return "No costs recorded."
        parts = [f"{money(amount)} {code}" for code, amount in sorted(self.by_currency.items())]
        return ", ".join(parts)


def totals(session: Session, activity: Activity) -> Totals:
    """Add up an activity's costs, including any permit fees.

    Permit fees live on the permit rather than as a cost line, because that is
    where somebody looking at the paperwork expects to type them. They are real
    money and are counted here — a costing that quietly omits the permit fee is
    the costing that comes up short.
    """
    result = Totals()

    lines = session.scalars(
        select(ActivityCost).where(ActivityCost.activity_id == activity.id)
    ).all()
    for line in lines:
        amount = Decimal(str(line.unit_cost)) * Decimal(str(line.quantity))
        code = (line.currency or "USD").upper()
        result.by_currency[code] = result.by_currency.get(code, Decimal(0)) + amount
        result.line_count += 1
        if line.is_estimate:
            result.estimate_count += 1
            result.estimated_by_currency[code] = (
                result.estimated_by_currency.get(code, Decimal(0)) + amount
            )
        if line.expense_id is not None:
            result.linked_to_expenses += 1

    permits = session.scalars(
        select(ActivityPermit).where(
            ActivityPermit.activity_id == activity.id, ActivityPermit.cost.is_not(None)
        )
    ).all()
    for permit in permits:
        amount = Decimal(str(permit.cost))
        if amount == 0:
            continue
        code = (permit.currency or "USD").upper()
        result.by_currency[code] = result.by_currency.get(code, Decimal(0)) + amount
        result.line_count += 1

    return result


# --------------------------------------------------------------------------
# What is still outstanding
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Outstanding:
    """What has not been done yet, and how late it is getting.

    Computed rather than stored, because a stored "days remaining" is wrong
    from the moment it is written.
    """

    permits_outstanding: list[str] = field(default_factory=list)
    preparations_outstanding: list[str] = field(default_factory=list)
    #: Items whose lead time no longer fits before the start date. The list a
    #: screen should draw in the colour that means look at this.
    too_late: list[str] = field(default_factory=list)
    #: The longest lead time still outstanding — how far ahead of the start
    #: date work should already have begun.
    longest_lead_days: int | None = None
    #: False once the activity is over or cancelled. The same unticked box means
    #: two different things either side of this: before, it is a task; after, it
    #: is a record of something that never got done.
    is_actionable: bool = True

    @property
    def is_clear(self) -> bool:
        return not self.permits_outstanding and not self.preparations_outstanding


#: Statuses after which nothing can be late, because it has already happened.
_FINISHED = frozenset({ActivityStatus.COMPLETED, ActivityStatus.CANCELLED})


def outstanding(session: Session, activity: Activity, *, today: date | None = None) -> Outstanding:
    """Everything still to do before this activity can run.

    For an activity that is over, the unfinished items are still listed — "the
    insurance was never renewed" is a fact about that season somebody may need
    — but nothing is marked as running out of time. Telling a 2019 excavation
    it has ten days to get its licence is the kind of warning that teaches
    people to ignore warnings.
    """
    now = today or date.today()
    result = Outstanding()
    result.is_actionable = activity.status not in _FINISHED
    leads: list[int] = []

    permits = session.scalars(
        select(ActivityPermit)
        .where(ActivityPermit.activity_id == activity.id)
        .order_by(ActivityPermit.position, ActivityPermit.id)
    ).all()
    for permit in permits:
        if permit.status in {PermitStatus.GRANTED, PermitStatus.NOT_REQUIRED}:
            continue
        # A refusal is not outstanding work; it is a decision. Listing it as a
        # to-do would have somebody re-apply into the same no.
        if permit.status is PermitStatus.REFUSED:
            continue
        where = f" ({permit.issuer})" if permit.issuer else ""
        label = f"{permit.name}{where} — {permit.status.value.replace('_', ' ')}"
        result.permits_outstanding.append(label)
        if permit.lead_time_days is not None:
            leads.append(permit.lead_time_days)
            if (
                result.is_actionable
                and activity.starts_on is not None
                and activity.starts_on - now < timedelta(days=permit.lead_time_days)
            ):
                result.too_late.append(
                    f"{permit.name} — normally takes {permit.lead_time_days} days"
                )

    preparations = session.scalars(
        select(ActivityPreparation)
        .where(
            ActivityPreparation.activity_id == activity.id,
            ActivityPreparation.is_done.is_(False),
        )
        .order_by(ActivityPreparation.position, ActivityPreparation.id)
    ).all()
    for step in preparations:
        result.preparations_outstanding.append(step.description)
        if step.lead_time_days is not None:
            leads.append(step.lead_time_days)
            if (
                result.is_actionable
                and activity.starts_on is not None
                and activity.starts_on - now < timedelta(days=step.lead_time_days)
            ):
                result.too_late.append(
                    f"{step.description} — normally needs {step.lead_time_days} days"
                )

    result.longest_lead_days = max(leads) if leads else None
    return result


# --------------------------------------------------------------------------
# The brief
# --------------------------------------------------------------------------
def _rule(title: str) -> list[str]:
    return ["", title.upper(), "-" * len(title)]


def _when(activity: Activity) -> str:
    if activity.starts_on and activity.ends_on:
        if activity.starts_on == activity.ends_on:
            return activity.starts_on.isoformat()
        days = activity.duration_days
        return f"{activity.starts_on.isoformat()} to {activity.ends_on.isoformat()} ({days} days)"
    if activity.starts_on:
        return f"from {activity.starts_on.isoformat()}"
    if activity.ends_on:
        return f"until {activity.ends_on.isoformat()}"
    return "no dates set"


def brief(session: Session, activity: Activity, *, today: date | None = None) -> str:
    """The whole activity as plain text.

    Written to be read by a person who was not there and has no account here.
    Sections that would be empty are left out entirely rather than printed with
    "none" under them: a brief padded with empty headings is one people stop
    reading to the bottom of, and the bottom is where the costs are.
    """
    lines: list[str] = [
        activity.title,
        "=" * len(activity.title),
        f"Kind:     {activity.kind.value.replace('_', ' ')}",
        f"Status:   {activity.status.value.replace('_', ' ')}",
        f"When:     {_when(activity)}",
    ]
    if activity.location:
        lines.append(f"Where:    {activity.location}")
    if activity.lead_label:
        lines.append(f"Led by:   {activity.lead_label}")
    if activity.team_size is not None:
        lines.append(f"Team:     {activity.team_size} people")

    if activity.summary:
        lines += _rule("What it was")
        lines.append(activity.summary.strip())

    equipment = session.scalars(
        select(ActivityEquipment)
        .where(ActivityEquipment.activity_id == activity.id)
        .order_by(ActivityEquipment.position, ActivityEquipment.id)
    ).all()
    if equipment:
        lines += _rule("Equipment")
        for item in equipment:
            unit = f" {item.unit}" if item.unit else ""
            row = f"  {tidy(item.quantity)}{unit} x {item.label}"
            if item.source:
                row += f" ({item.source})"
            lines.append(row)
            if item.performance_notes:
                lines.append(f"      note: {item.performance_notes.strip()}")

    permits = session.scalars(
        select(ActivityPermit)
        .where(ActivityPermit.activity_id == activity.id)
        .order_by(ActivityPermit.position, ActivityPermit.id)
    ).all()
    if permits:
        lines += _rule("Permissions and paperwork")
        for permit in permits:
            row = f"  {permit.name} — {permit.status.value.replace('_', ' ')}"
            if permit.issuer:
                row += f", from {permit.issuer}"
            if permit.reference:
                row += f" [{permit.reference}]"
            lines.append(row)
            took = permit.days_to_obtain
            if took is not None:
                lines.append(f"      took {took} days ({permit.applied_on} to {permit.granted_on})")
            elif permit.lead_time_days is not None:
                lines.append(f"      allow {permit.lead_time_days} days")
            if permit.expires_on:
                lines.append(f"      expires {permit.expires_on.isoformat()}")
            if permit.cost:
                lines.append(f"      fee {money(permit.cost)} {permit.currency or ''}".rstrip())
            if permit.contact:
                lines.append(f"      contact: {permit.contact}")

    preparations = session.scalars(
        select(ActivityPreparation)
        .where(ActivityPreparation.activity_id == activity.id)
        .order_by(ActivityPreparation.position, ActivityPreparation.id)
    ).all()
    if preparations:
        lines += _rule("Preparations")
        for step in preparations:
            # A tick and a space, so the two states line up in a proportional
            # font as well as a monospaced one.
            mark = "[x]" if step.is_done else "[ ]"
            row = f"  {mark} {step.description}"
            if step.lead_time_days is not None:
                row += f" — {step.lead_time_days} days ahead"
            if step.due_on:
                row += f", by {step.due_on.isoformat()}"
            lines.append(row)
            if step.responsible_label:
                lines.append(f"      who: {step.responsible_label}")

    money_lines = session.scalars(
        select(ActivityCost)
        .where(ActivityCost.activity_id == activity.id)
        .order_by(ActivityCost.position, ActivityCost.id)
    ).all()
    figures = totals(session, activity)
    if money_lines or figures.by_currency:
        lines += _rule("Costs")
        for line in money_lines:
            unit = f"/{line.unit}" if line.unit else ""
            each = f"{money(line.unit_cost)}{unit} x {tidy(line.quantity)}"
            total = money(Decimal(str(line.unit_cost)) * Decimal(str(line.quantity)))
            row = f"  {line.description}: {each} = {total} {line.currency}"
            if line.is_estimate:
                row += "  (estimate)"
            lines.append(row)
            if line.supplier:
                lines.append(f"      supplier: {line.supplier}")
        for permit in permits:
            if permit.cost:
                lines.append(
                    f"  Permit fee — {permit.name}: "
                    f"{money(permit.cost)} {permit.currency or ''}".rstrip()
                )
        lines.append("")
        lines.append(f"  TOTAL: {figures.as_text()}")
        if figures.any_estimates:
            estimated = ", ".join(
                f"{money(amount)} {code}"
                for code, amount in sorted(figures.estimated_by_currency.items())
            )
            lines.append(
                f"  Of which estimated: {estimated} "
                f"({figures.estimate_count} of {figures.line_count} lines)"
            )

    still = outstanding(session, activity, today=today)
    if not still.is_clear:
        # Different heading either side of the activity happening. Before, this
        # is a to-do list; after, it is a note of what never got done.
        lines += _rule("Still outstanding" if still.is_actionable else "Never done")
        for entry in still.permits_outstanding:
            lines.append(f"  ! {entry}")
        for entry in still.preparations_outstanding:
            lines.append(f"  - {entry}")
        if still.too_late:
            lines.append("")
            lines.append("  Not enough time left, going by how long these took before:")
            for entry in still.too_late:
                lines.append(f"    ** {entry}")

    if activity.outcome:
        lines += _rule("Outcome")
        lines.append(activity.outcome.strip())

    if activity.lessons:
        lines += _rule("What to do differently")
        lines.append(activity.lessons.strip())

    if activity.notes:
        lines += _rule("Notes")
        lines.append(activity.notes.strip())

    return "\n".join(lines) + "\n"


def brief_subject(activity: Activity) -> str:
    """The subject line for the e-mailed brief."""
    when = ""
    if activity.starts_on:
        when = f" — {activity.starts_on.isoformat()}"
    return f"{activity.title}{when}"


# --------------------------------------------------------------------------
# Doing it again
# --------------------------------------------------------------------------
def repeat(
    session: Session,
    source: Activity,
    *,
    title: str | None = None,
    starts_on: date | None = None,
    ends_on: date | None = None,
    user: User | None = None,
    copy_costs: bool = True,
) -> Activity:
    """Start a new activity from a past one.

    What carries over and what does not is the whole design:

    - **Equipment** carries over as it was, performance notes included. Knowing
      the generator was underpowered last time is the reason to look.
    - **Permits** carry over with their dates cleared and their status reset to
      needing application — but they keep their ``lead_time_days``, filled in
      from how long they actually took before if it was not set by hand. That
      one number is what the repeat is for.
    - **Preparations** carry over unticked, keeping their lead times.
    - **Costs** carry over as *estimates*, because last year's price is an
      estimate of this year's and calling it anything else is how a budget goes
      wrong. Any link to an expense is dropped: that money was paid once.
    - **Photographs and the outcome do not carry over.** They belong to what
      happened, and nothing has happened yet.

    The new activity's dates default to the same length as the original,
    starting on ``starts_on``. Nothing is committed; the caller owns the
    transaction.
    """
    length = source.duration_days
    if ends_on is None and starts_on is not None and length is not None:
        ends_on = starts_on + timedelta(days=length - 1)

    fresh = Activity(
        title=title or f"{source.title} (repeat)",
        summary=source.summary,
        kind=source.kind,
        status=ActivityStatus.PLANNED,
        starts_on=starts_on,
        ends_on=ends_on,
        location=source.location,
        project_id=source.project_id,
        site_id=source.site_id,
        budget_id=source.budget_id,
        lead_id=source.lead_id,
        lead_label=source.lead_label,
        team_size=source.team_size,
        team_notes=source.team_notes,
        # Deliberately not copied: outcome and lessons describe the last run.
        # The lessons are still one click away through ``repeated_from``.
        repeated_from_id=source.id,
        owner_id=user.id if user is not None else source.owner_id,
    )
    session.add(fresh)
    session.flush()

    for item in session.scalars(
        select(ActivityEquipment)
        .where(ActivityEquipment.activity_id == source.id)
        .order_by(ActivityEquipment.position, ActivityEquipment.id)
    ).all():
        session.add(
            ActivityEquipment(
                activity_id=fresh.id,
                equipment_id=item.equipment_id,
                label=item.label,
                quantity=item.quantity,
                unit=item.unit,
                source=item.source,
                performance_notes=item.performance_notes,
                was_essential=item.was_essential,
                position=item.position,
                notes=item.notes,
            )
        )

    for permit in session.scalars(
        select(ActivityPermit)
        .where(ActivityPermit.activity_id == source.id)
        .order_by(ActivityPermit.position, ActivityPermit.id)
    ).all():
        # Learn the lead time from what actually happened, unless somebody
        # already wrote one down — a typed-in figure beats a single sample.
        learned = permit.lead_time_days
        if learned is None:
            learned = permit.days_to_obtain
        # "Not required" stays not required. Everything else has to be got
        # again, whatever state it reached last time.
        carried_status = (
            PermitStatus.NOT_REQUIRED
            if permit.status is PermitStatus.NOT_REQUIRED
            else PermitStatus.TO_APPLY
        )
        session.add(
            ActivityPermit(
                activity_id=fresh.id,
                name=permit.name,
                issuer=permit.issuer,
                # The reference belonged to last time's permit, not this one.
                reference=None,
                status=carried_status,
                applied_on=None,
                granted_on=None,
                expires_on=None,
                cost=permit.cost,
                currency=permit.currency,
                lead_time_days=learned,
                contact=permit.contact,
                position=permit.position,
                notes=permit.notes,
            )
        )

    for step in session.scalars(
        select(ActivityPreparation)
        .where(ActivityPreparation.activity_id == source.id)
        .order_by(ActivityPreparation.position, ActivityPreparation.id)
    ).all():
        due = None
        if starts_on is not None and step.lead_time_days is not None:
            due = starts_on - timedelta(days=step.lead_time_days)
        session.add(
            ActivityPreparation(
                activity_id=fresh.id,
                description=step.description,
                category=step.category,
                lead_time_days=step.lead_time_days,
                due_on=due,
                is_done=False,
                done_on=None,
                responsible_label=step.responsible_label,
                position=step.position,
                notes=step.notes,
            )
        )

    if copy_costs:
        for line in session.scalars(
            select(ActivityCost)
            .where(ActivityCost.activity_id == source.id)
            .order_by(ActivityCost.position, ActivityCost.id)
        ).all():
            session.add(
                ActivityCost(
                    activity_id=fresh.id,
                    description=line.description,
                    category=line.category,
                    unit_cost=line.unit_cost,
                    quantity=line.quantity,
                    unit=line.unit,
                    currency=line.currency,
                    supplier=line.supplier,
                    # Last year's price is this year's estimate, whatever it
                    # was last year.
                    is_estimate=True,
                    expense_id=None,
                    position=line.position,
                    notes=line.notes,
                )
            )

    session.flush()
    return fresh
