"""The rules of the inventory module, kept out of the endpoints.

Four things live here because more than one endpoint needs them and because
getting any of them subtly wrong is the kind of mistake an inventory takes a
season to notice:

- :func:`apply_stock_change` is the only way a consumable's quantity changes.
  It locks the row, appends to the ledger, and writes the new total — in that
  order, so two people issuing bags at once cannot both read 500 and both
  write 400.
- :func:`issue` and :func:`give_back` move a piece of equipment out and in,
  keeping the item's status in step with whether a loan is open.
- :func:`next_due` works out when a calibration falls due next.
- :func:`build_kit` fills a packing list, and reports what it could not fill.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import CalibrationResult, EquipmentStatus, StockReason
from app.models.inventory import (
    Calibration,
    Checkout,
    Consumable,
    Equipment,
    Kit,
    KitTemplate,
    KitTemplateLine,
    StockMovement,
)
from app.models.user import User


class InventoryError(Exception):
    """Something the register refuses to record."""


def _now() -> datetime:
    return datetime.now(UTC)


def tidy(amount: Decimal | float | None) -> str:
    """A quantity as somebody would write it: 1, not 1.000; 12.5, not 12.500.

    The column is ``Numeric(12, 3)`` so that measured stock survives, and
    PostgreSQL hands back every one of those places. Formatting a Decimal with
    ``:g`` does *not* strip them — it prints "1.000" — so a packing list reads
    like a lab report unless the value goes through float first.
    """
    return f"{float(amount or 0):g}"


# --------------------------------------------------------------------------
# Stock
# --------------------------------------------------------------------------
def apply_stock_change(
    session: Session,
    consumable: Consumable,
    *,
    change: Decimal | float,
    reason: StockReason,
    user: User | None = None,
    project_id: uuid.UUID | None = None,
    issued_to_label: str | None = None,
    kit_id: uuid.UUID | None = None,
    notes: str | None = None,
    occurred_at: datetime | None = None,
) -> StockMovement:
    """Move stock, and record why.

    The row is locked for the duration. Without that, two people issuing finds
    bags at the same moment both read the same starting figure and both write
    a total that ignores the other — and the shelf is short by exactly the
    amount nobody can account for.
    """
    amount = Decimal(str(change))
    if amount == 0:
        raise InventoryError("A movement of zero records nothing")

    # Re-read under a row lock. `with_for_update` on the primary key is the
    # cheapest correct thing here; the alternative, an atomic UPDATE … SET
    # quantity = quantity + :change, cannot also write the resulting balance
    # onto the ledger row without a second read anyway.
    locked = session.scalars(
        select(Consumable).where(Consumable.id == consumable.id).with_for_update()
    ).one()

    current = Decimal(str(locked.quantity or 0))
    balance = current + amount
    if balance < 0:
        raise InventoryError(
            f"There are only {tidy(current)} {locked.unit} of {locked.code} on the shelf, "
            f"so {tidy(abs(amount))} cannot be taken. Record what is actually there "
            f"with a stock-take first if the count is wrong."
        )

    movement = StockMovement(
        consumable_id=locked.id,
        change=amount,
        balance_after=balance,
        reason=reason,
        project_id=project_id,
        issued_to_label=issued_to_label,
        kit_id=kit_id,
        notes=notes,
        occurred_at=occurred_at or _now(),
        recorded_by_id=user.id if user else None,
        recorded_by_label=user.username if user else None,
    )
    locked.quantity = balance
    session.add(movement)
    session.flush()
    return movement


def stock_take(
    session: Session,
    consumable: Consumable,
    *,
    counted: Decimal | float,
    user: User | None = None,
    notes: str | None = None,
    occurred_at: datetime | None = None,
) -> StockMovement | None:
    """Record what is actually on the shelf.

    The *difference* goes in the ledger, not the count, so a discrepancy is
    visible as an event rather than absorbed into a number that quietly
    changed. A count that agrees with the record writes nothing: an inventory
    full of zero-change rows is an inventory nobody reads.
    """
    target = Decimal(str(counted))
    current = Decimal(str(consumable.quantity or 0))
    if target == current:
        return None

    return apply_stock_change(
        session,
        consumable,
        change=target - current,
        reason=StockReason.STOCKTAKE,
        user=user,
        notes=notes or f"Stock-take: counted {tidy(target)}, record said {tidy(current)}",
        occurred_at=occurred_at,
    )


# --------------------------------------------------------------------------
# Equipment in and out
# --------------------------------------------------------------------------
def open_checkout(session: Session, equipment_id: uuid.UUID) -> Checkout | None:
    """The loan this item is out on, if any."""
    return session.scalars(
        select(Checkout)
        .where(Checkout.equipment_id == equipment_id, Checkout.returned_at.is_(None))
        .limit(1)
    ).first()


def issue(
    session: Session,
    equipment: Equipment,
    *,
    borrower_label: str,
    borrower: User | None = None,
    issued_by: User | None = None,
    project_id: uuid.UUID | None = None,
    destination: str | None = None,
    taken_at: datetime | None = None,
    due_on: date | None = None,
    condition_out: str | None = None,
    notes: str | None = None,
    kit_id: uuid.UUID | None = None,
) -> Checkout:
    """Take an item out of the building."""
    if equipment.status is EquipmentStatus.RETIRED:
        raise InventoryError(
            f"{equipment.asset_number} has been retired. Bring it back into service first."
        )
    existing = open_checkout(session, equipment.id)
    if existing is not None:
        raise InventoryError(
            f"{equipment.asset_number} is already out with {existing.borrower_label}"
            + (f", due back {existing.due_on:%d %b %Y}" if existing.due_on else "")
        )

    checkout = Checkout(
        equipment_id=equipment.id,
        borrower_id=borrower.id if borrower else None,
        borrower_label=borrower_label,
        project_id=project_id,
        destination=destination,
        taken_at=taken_at or _now(),
        due_on=due_on,
        condition_out=condition_out,
        notes=notes,
        issued_by_id=issued_by.id if issued_by else None,
        kit_id=kit_id,
    )
    equipment.status = EquipmentStatus.CHECKED_OUT
    session.add(checkout)
    session.flush()
    return checkout


def give_back(
    session: Session,
    checkout: Checkout,
    *,
    received_by: User | None = None,
    returned_at: datetime | None = None,
    condition_in: str | None = None,
    storage_location_id: uuid.UUID | None = None,
    notes: str | None = None,
) -> Checkout:
    """Bring an item back."""
    if checkout.returned_at is not None:
        raise InventoryError("That loan was already closed")

    when = returned_at or _now()
    if when < checkout.taken_at:
        raise InventoryError("It cannot have come back before it went out")

    checkout.returned_at = when
    checkout.condition_in = condition_in
    checkout.received_by_id = received_by.id if received_by else None
    if notes:
        checkout.notes = f"{checkout.notes}\n{notes}" if checkout.notes else notes

    equipment = session.get(Equipment, checkout.equipment_id)
    if equipment is not None:
        # Only lift the status if it is still "out". An item marked missing or
        # sent for repair while it was away keeps that status: the more
        # specific fact is the one worth keeping.
        if equipment.status is EquipmentStatus.CHECKED_OUT:
            equipment.status = EquipmentStatus.AVAILABLE
        if storage_location_id is not None:
            equipment.storage_location_id = storage_location_id
    session.flush()
    return checkout


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------
def next_due(equipment: Equipment, performed_on: date, given: date | None) -> date | None:
    """When the next calibration falls due.

    The certificate wins when it says something. Otherwise the item's own
    interval decides, and an item with no interval simply has no due date —
    inventing one would put a false deadline in front of somebody.
    """
    if given is not None:
        return given
    if equipment.calibration_interval_days:
        return performed_on + timedelta(days=equipment.calibration_interval_days)
    return None


def record_calibration(
    session: Session,
    equipment: Equipment,
    *,
    performed_on: date,
    result: CalibrationResult,
    performed_by: str | None = None,
    certificate_number: str | None = None,
    next_due_on: date | None = None,
    cost: float | None = None,
    currency: str | None = None,
    notes: str | None = None,
    user: User | None = None,
) -> Calibration:
    """Record a service, and update what the item advertises about itself."""
    due = next_due(equipment, performed_on, next_due_on)
    calibration = Calibration(
        equipment_id=equipment.id,
        performed_on=performed_on,
        performed_by=performed_by,
        certificate_number=certificate_number,
        result=result,
        next_due_on=due,
        cost=cost,
        currency=currency,
        notes=notes,
        recorded_by_id=user.id if user else None,
    )
    session.add(calibration)

    # Only a later certificate moves the due date. Entering an old one you
    # found in a drawer is a normal thing to do, and it must not make an item
    # that is currently in date look overdue.
    latest = session.scalars(
        select(Calibration)
        .where(Calibration.equipment_id == equipment.id)
        .order_by(Calibration.performed_on.desc())
        .limit(1)
    ).first()
    if latest is None or performed_on >= latest.performed_on:
        equipment.calibration_due_on = due
        equipment.needs_calibration = True
        if result is CalibrationResult.FAILED:
            # A failed calibration means the item should not be used on the
            # strength of it. Saying so in the status is more use than a row
            # nobody opens.
            equipment.status = EquipmentStatus.IN_REPAIR
        elif equipment.status is EquipmentStatus.OUT_FOR_CALIBRATION:
            equipment.status = EquipmentStatus.AVAILABLE

    session.flush()
    return calibration


def is_overdue(equipment: Equipment, today: date | None = None) -> bool:
    """Whether this item's calibration has run out."""
    if not equipment.needs_calibration or equipment.calibration_due_on is None:
        return False
    return equipment.calibration_due_on < (today or date.today())


# --------------------------------------------------------------------------
# Kits
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Shortfall:
    """One line the build could not fill."""

    line_id: uuid.UUID | None
    what: str
    wanted: float
    supplied: float
    reason: str
    is_optional: bool = False

    def as_dict(self) -> dict:
        return {
            "line_id": str(self.line_id) if self.line_id else None,
            "what": self.what,
            "wanted": self.wanted,
            "supplied": self.supplied,
            "reason": self.reason,
            "is_optional": self.is_optional,
        }


def _available_of_category(
    session: Session, category: str, wanted: int, exclude: set[uuid.UUID]
) -> list[Equipment]:
    """Items of a kind that could go out today, oldest asset number first.

    Ordering by asset number rather than at random means the same kit built
    twice tends to contain the same items, which is what makes "the camera
    with the sticky zoom" a thing anybody can report.
    """
    statement = (
        select(Equipment)
        .where(
            Equipment.category == category,
            Equipment.status == EquipmentStatus.AVAILABLE,
            Equipment.id.notin_(exclude) if exclude else Equipment.id.is_not(None),
        )
        .order_by(Equipment.asset_number)
        .limit(wanted)
    )
    return list(session.scalars(statement).all())


def build_kit(
    session: Session,
    template: KitTemplate,
    *,
    issued_to_label: str,
    issued_to: User | None = None,
    issued_by: User | None = None,
    name: str | None = None,
    project_id: uuid.UUID | None = None,
    destination: str | None = None,
    issued_at: datetime | None = None,
    due_on: date | None = None,
    notes: str | None = None,
    all_or_nothing: bool = False,
) -> tuple[Kit, list[Shortfall]]:
    """Fill a packing list: check out the equipment, issue the consumables.

    Returns the kit and everything it could not supply. A shortfall is not an
    error by default — a kit that is nine tenths ready is still the kit going
    out this morning, and the list is what somebody reads before they drive
    off. ``all_or_nothing`` is for the case where a partial kit is worse than
    no kit, and refuses the whole build instead.
    """
    when = issued_at or _now()
    kit = Kit(
        name=name or f"{template.name} — {when:%d %b %Y}",
        template_id=template.id,
        project_id=project_id,
        issued_to_id=issued_to.id if issued_to else None,
        issued_to_label=issued_to_label,
        destination=destination,
        issued_at=when,
        due_on=due_on,
        notes=notes,
        owner_id=issued_by.id if issued_by else None,
    )
    session.add(kit)
    session.flush()

    shortfalls: list[Shortfall] = []
    # Items already promised to *this* build. Two lines asking for a camera
    # must not both be handed the same camera.
    #
    # Issuing an item flips its status, and the availability query filters on
    # that, so this set is a second line of defence rather than the mechanism.
    # It is worth keeping: the two are independent, and the failure they guard
    # against — a kit that is silently short one camera — is invisible until
    # somebody is standing in a trench without it.
    taken: set[uuid.UUID] = set()

    for line in sorted(template.lines, key=lambda item: (item.position, item.id.hex)):
        wanted = Decimal(str(line.quantity))

        if line.equipment_id is not None:
            item = session.get(Equipment, line.equipment_id)
            if item is None:
                shortfalls.append(
                    Shortfall(
                        line.id, "An item that no longer exists", 1, 0, "deleted", line.is_optional
                    )
                )
                continue
            try:
                issue(
                    session,
                    item,
                    borrower_label=issued_to_label,
                    borrower=issued_to,
                    issued_by=issued_by,
                    project_id=project_id,
                    destination=destination,
                    taken_at=when,
                    due_on=due_on,
                    kit_id=kit.id,
                )
                taken.add(item.id)
            except InventoryError as exc:
                shortfalls.append(
                    Shortfall(
                        line.id,
                        f"{item.asset_number} {item.name}",
                        1,
                        0,
                        str(exc),
                        line.is_optional,
                    )
                )

        elif line.equipment_category is not None:
            count = int(wanted)
            found = _available_of_category(session, line.equipment_category, count, taken)
            for item in found:
                issue(
                    session,
                    item,
                    borrower_label=issued_to_label,
                    borrower=issued_to,
                    issued_by=issued_by,
                    project_id=project_id,
                    destination=destination,
                    taken_at=when,
                    due_on=due_on,
                    kit_id=kit.id,
                )
                taken.add(item.id)
            if len(found) < count:
                shortfalls.append(
                    Shortfall(
                        line.id,
                        line.equipment_category,
                        count,
                        len(found),
                        f"only {len(found)} of {count} available",
                        line.is_optional,
                    )
                )

        elif line.consumable_id is not None:
            stock = session.get(Consumable, line.consumable_id)
            if stock is None:
                shortfalls.append(
                    Shortfall(
                        line.id,
                        "A stock line that no longer exists",
                        float(wanted),
                        0,
                        "deleted",
                        line.is_optional,
                    )
                )
                continue
            have = Decimal(str(stock.quantity or 0))
            # Part of what was asked for is better than none: five bags short
            # is a note, not a reason to send somebody out with no bags.
            supplied = min(have, wanted)
            if supplied > 0:
                apply_stock_change(
                    session,
                    stock,
                    change=-supplied,
                    reason=StockReason.ISSUED,
                    user=issued_by,
                    project_id=project_id,
                    issued_to_label=issued_to_label,
                    kit_id=kit.id,
                    occurred_at=when,
                )
            if supplied < wanted:
                shortfalls.append(
                    Shortfall(
                        line.id,
                        f"{stock.code} {stock.name}",
                        float(wanted),
                        float(supplied),
                        f"only {tidy(have)} {stock.unit} on the shelf",
                        line.is_optional,
                    )
                )

    required_missing = [entry for entry in shortfalls if not entry.is_optional]
    if all_or_nothing and required_missing:
        raise InventoryError(
            "The kit could not be filled completely: "
            + "; ".join(f"{entry.what} ({entry.reason})" for entry in required_missing)
        )

    kit.shortfalls = [entry.as_dict() for entry in shortfalls]
    session.flush()
    return kit, shortfalls


def close_kit(
    session: Session,
    kit: Kit,
    *,
    received_by: User | None = None,
    returned_at: datetime | None = None,
    condition_in: str | None = None,
    notes: str | None = None,
) -> list[Checkout]:
    """Bring back everything in a kit that is still out."""
    when = returned_at or _now()
    still_out = list(
        session.scalars(
            select(Checkout).where(Checkout.kit_id == kit.id, Checkout.returned_at.is_(None))
        ).all()
    )
    for checkout in still_out:
        give_back(
            session,
            checkout,
            received_by=received_by,
            returned_at=when,
            condition_in=condition_in,
            notes=notes,
        )
    kit.returned_at = when
    session.flush()
    return still_out


def describe_line(session: Session, line: KitTemplateLine) -> str:
    """A packing-list line as words, for a screen or a printed sheet."""
    if line.equipment_id is not None:
        item = session.get(Equipment, line.equipment_id)
        return f"{item.asset_number} {item.name}" if item else "(deleted item)"
    if line.consumable_id is not None:
        stock = session.get(Consumable, line.consumable_id)
        if stock is None:
            return "(deleted stock line)"
        return f"{tidy(line.quantity)} {stock.unit} — {stock.name}"
    return f"{tidy(line.quantity)} × {line.equipment_category}"
