"""Office and field inventory: equipment, consumables, calibration and kits.

Permissions run through the **inventory** module. Like the museum, it is flat:
there are no projects to belong to, so the rule is the module level plus
ownership rather than project membership.

Three things here are actions rather than edits, and are shaped that way on
purpose:

- Checking an item out needs a borrower. A PATCH that could set the status to
  "checked out" would record that the theodolite is gone without recording who
  has it, so the update schema refuses that value outright.
- Changing stock needs a reason. The quantity on a consumable is the sum of a
  ledger; a form that could type over the total would make the ledger
  decorative.
- Building a kit does both at once, for a list of things, and reports what it
  could not supply rather than failing.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, CurrentUserOptional, DbSession, require_module
from app.core.permissions import flat_can_edit, flat_visibility_filter, has_module_access
from app.models.enums import (
    ActivityAction,
    EquipmentStatus,
    Module,
    ResourceType,
    StockReason,
)
from app.models.enums import ModuleLevel as Level
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
from app.models.storage import StorageLocation
from app.models.user import User
from app.schemas.common import Message, Page
from app.schemas.inventory import (
    CalibrationCreate,
    CalibrationRead,
    CheckoutCreate,
    CheckoutRead,
    CheckoutReturn,
    CheckoutWithEquipment,
    ConsumableCreate,
    ConsumableDetail,
    ConsumableSummary,
    ConsumableUpdate,
    EquipmentCreate,
    EquipmentDetail,
    EquipmentSummary,
    EquipmentUpdate,
    KitBuild,
    KitDetail,
    KitReturn,
    KitShortfall,
    KitSummary,
    KitTemplateCreate,
    KitTemplateDetail,
    KitTemplateLineRead,
    KitTemplateSummary,
    KitTemplateUpdate,
    StockMovementCreate,
    StockMovementRead,
    StockTake,
)
from app.services import activity, records
from app.services import inventory as kit_service

router = APIRouter(prefix="/inventory", tags=["Inventory"])

MODULE = Module.INVENTORY
RESOURCE = ResourceType.EQUIPMENT

InventoryViewer = Annotated[User, Depends(require_module(MODULE, Level.VIEWER))]
InventoryContributor = Annotated[User, Depends(require_module(MODULE, Level.CONTRIBUTOR))]
InventorySupervisor = Annotated[User, Depends(require_module(MODULE, Level.SUPERVISOR))]


def _visible(user: User | None, model: Any) -> Any:
    return flat_visibility_filter(user, model, MODULE)


def _may_edit(user: User | None, record: Any) -> bool:
    return flat_can_edit(user, record, MODULE)


def _require_readable(user: User | None, record: Any, name: str) -> None:
    if has_module_access(user, MODULE, Level.VIEWER) or getattr(record, "is_public", False):
        return
    raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{name} not found")


def _require_editable(user: User | None, record: Any, name: str) -> None:
    _require_readable(user, record, name)
    if not _may_edit(user, record):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail=f"You may not edit this {name.lower()}"
        )


def _refuse(error: kit_service.InventoryError) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail=str(error))


def _storage_path(session: DbSession, location_id: uuid.UUID | None) -> str | None:
    if location_id is None:
        return None
    location = session.get(StorageLocation, location_id)
    return location.display_path if location else None


# --------------------------------------------------------------------------
# Equipment
# --------------------------------------------------------------------------
def _equipment_detail(session: DbSession, item: Equipment, user: User | None) -> EquipmentDetail:
    payload = EquipmentDetail.model_validate(item)
    payload.storage_path = _storage_path(session, item.storage_location_id)

    open_loan = kit_service.open_checkout(session, item.id)
    payload.open_checkout = CheckoutRead.model_validate(open_loan) if open_loan else None

    last = session.scalars(
        select(Calibration)
        .where(Calibration.equipment_id == item.id)
        .order_by(Calibration.performed_on.desc())
        .limit(1)
    ).first()
    payload.last_calibration = CalibrationRead.model_validate(last) if last else None
    payload.calibration_overdue = kit_service.is_overdue(item)

    payload.can_edit = _may_edit(user, item)
    payload.can_delete = has_module_access(user, MODULE, Level.SUPERVISOR)
    return payload


@router.post(
    "/equipment",
    response_model=EquipmentDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Add a piece of equipment",
)
def create_equipment(
    payload: EquipmentCreate, session: DbSession, request: Request, user: InventoryContributor
) -> EquipmentDetail:
    existing = session.scalar(
        select(Equipment).where(Equipment.asset_number == payload.asset_number)
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"{payload.asset_number!r} is already the number of {existing.name!r}",
        )

    item = Equipment(**payload.model_dump(), owner_id=user.id)
    session.add(item)
    session.flush()

    # Version 1 as well as the log entry, so an item's history starts at what
    # it was when it arrived rather than at somebody's first correction.
    records.on_created(session, item, RESOURCE, user=user, request=request, label=item.asset_number)
    session.flush()
    return _equipment_detail(session, item, user)


@router.get(
    "/equipment",
    response_model=Page[EquipmentSummary],
    summary="Search the equipment register",
)
def list_equipment(
    session: DbSession,
    user: CurrentUserOptional,
    q: Annotated[
        str | None, Query(description="Match asset number, name, serial number or manufacturer")
    ] = None,
    category: Annotated[str | None, Query()] = None,
    equipment_status: Annotated[EquipmentStatus | None, Query(alias="status")] = None,
    storage_location_id: Annotated[uuid.UUID | None, Query()] = None,
    needs_calibration: Annotated[bool | None, Query()] = None,
    calibration_overdue: Annotated[
        bool | None, Query(description="Only items whose calibration has run out")
    ] = None,
    available: Annotated[
        bool | None, Query(description="Only items that could go out today")
    ] = None,
    sort: Annotated[str, Query(pattern="^-?(asset_number|name|created_at)$")] = "asset_number",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[EquipmentSummary]:
    statement = select(Equipment).where(_visible(user, Equipment))

    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Equipment.asset_number).like(pattern),
                func.lower(Equipment.name).like(pattern),
                func.lower(Equipment.serial_number).like(pattern),
                func.lower(Equipment.manufacturer).like(pattern),
                func.lower(Equipment.model).like(pattern),
            )
        )
    if category:
        statement = statement.where(Equipment.category == category)
    if equipment_status is not None:
        statement = statement.where(Equipment.status == equipment_status)
    if storage_location_id is not None:
        statement = statement.where(Equipment.storage_location_id == storage_location_id)
    if needs_calibration is not None:
        statement = statement.where(Equipment.needs_calibration.is_(needs_calibration))
    if calibration_overdue:
        statement = statement.where(
            Equipment.needs_calibration.is_(True),
            Equipment.calibration_due_on.is_not(None),
            Equipment.calibration_due_on < date.today(),
        )
    if available is not None:
        test = Equipment.status == EquipmentStatus.AVAILABLE
        statement = statement.where(test if available else ~test)

    descending = sort.startswith("-")
    column = getattr(Equipment, sort.lstrip("-"))
    statement = statement.order_by(column.desc() if descending else column.asc(), Equipment.id)

    rows, total = records.paginate(session, statement, limit, offset)
    return Page[EquipmentSummary](
        items=[EquipmentSummary.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/equipment/categories",
    response_model=list[str],
    summary="Categories in use",
    description=(
        "Every category somebody has actually typed, so the next person picks "
        "from the list instead of inventing 'Total Station' beside 'total "
        "station'. Declared before `/equipment/{id}`, which would otherwise "
        "read 'categories' as an identifier."
    ),
)
def list_categories(session: DbSession, user: InventoryViewer) -> list[str]:
    rows = session.scalars(
        select(Equipment.category)
        .where(Equipment.category.is_not(None))
        .distinct()
        .order_by(Equipment.category)
    ).all()
    return [row for row in rows if row]


@router.get(
    "/equipment/out",
    response_model=Page[CheckoutWithEquipment],
    summary="What is out of the building",
    description=(
        "Open loans, oldest first, with the days overdue worked out. This is "
        "the list somebody reads at the end of a season."
    ),
)
def list_open_checkouts(
    session: DbSession,
    user: InventoryViewer,
    overdue_only: Annotated[bool, Query()] = False,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    borrower_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CheckoutWithEquipment]:
    today = date.today()
    statement = (
        select(Checkout, Equipment)
        .join(Equipment, Equipment.id == Checkout.equipment_id)
        .where(Checkout.returned_at.is_(None))
    )
    if overdue_only:
        statement = statement.where(Checkout.due_on.is_not(None), Checkout.due_on < today)
    if project_id is not None:
        statement = statement.where(Checkout.project_id == project_id)
    if borrower_id is not None:
        statement = statement.where(Checkout.borrower_id == borrower_id)
    statement = statement.order_by(Checkout.taken_at)

    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = session.execute(statement.limit(limit).offset(offset)).all()

    items = []
    for checkout, item in rows:
        entry = CheckoutWithEquipment.model_validate(checkout)
        entry.asset_number = item.asset_number
        entry.equipment_name = item.name
        if checkout.due_on and checkout.due_on < today:
            entry.days_overdue = (today - checkout.due_on).days
        items.append(entry)

    return Page[CheckoutWithEquipment](items=items, total=total, limit=limit, offset=offset)


@router.get("/equipment/{equipment_id}", response_model=EquipmentDetail, summary="Read an item")
def read_equipment(
    equipment_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> EquipmentDetail:
    item = records.get_or_404(session, Equipment, equipment_id, "Equipment")
    _require_readable(user, item, "Equipment")
    return _equipment_detail(session, item, user)


@router.patch("/equipment/{equipment_id}", response_model=EquipmentDetail, summary="Edit an item")
def update_equipment(
    equipment_id: uuid.UUID,
    payload: EquipmentUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> EquipmentDetail:
    item = records.get_or_404(session, Equipment, equipment_id, "Equipment")
    _require_editable(user, item, "Equipment")

    changes = payload.model_dump(exclude_unset=True)
    # Lifting an item out of "checked out" by editing it would leave the loan
    # open and the register claiming somebody still has it. The loan has to be
    # closed properly, through the return.
    if "status" in changes and item.status is EquipmentStatus.CHECKED_OUT:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"{item.asset_number} is out on loan. Record it as returned "
                f"before changing its status, or the register will say two "
                f"different things about where it is."
            ),
        )

    before = records.apply_changes(item, changes)
    records.on_updated(session, item, RESOURCE, before=before, user=user, request=request)
    session.flush()
    return _equipment_detail(session, item, user)


@router.delete(
    "/equipment/{equipment_id}",
    response_model=Message,
    summary="Delete an item",
    description=(
        "Rarely the right thing. An item that is broken, sold or handed on "
        "should be **retired** instead: its loan history, its purchase record "
        "and its calibration certificates stay, and the asset number stays "
        "taken so nobody reuses it. Deleting is refused while a loan is open."
    ),
)
def delete_equipment(
    equipment_id: uuid.UUID, session: DbSession, request: Request, user: InventorySupervisor
) -> Message:
    item = records.get_or_404(session, Equipment, equipment_id, "Equipment")
    if kit_service.open_checkout(session, item.id) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"{item.asset_number} is out on loan. Get it back first.",
        )

    label = f"{item.asset_number} {item.name}"
    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=user,
        resource_type=RESOURCE,
        resource_id=item.id,
        resource_label=item.asset_number,
        summary=f"Deleted {label}",
        request=request,
    )
    session.delete(item)
    session.flush()
    return Message(detail=f"Deleted {label}")


# --------------------------------------------------------------------------
# Checking out and back in
# --------------------------------------------------------------------------
@router.post(
    "/equipment/{equipment_id}/checkouts",
    response_model=CheckoutRead,
    status_code=status.HTTP_201_CREATED,
    summary="Take an item out",
)
def check_out(
    equipment_id: uuid.UUID,
    payload: CheckoutCreate,
    session: DbSession,
    request: Request,
    user: InventoryContributor,
) -> CheckoutRead:
    item = records.get_or_404(session, Equipment, equipment_id, "Equipment")

    borrower = session.get(User, payload.borrower_id) if payload.borrower_id else None
    if payload.borrower_id and borrower is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That borrower does not exist")

    label = (payload.borrower_label or "").strip() or (
        borrower.full_name or borrower.username if borrower else ""
    )

    try:
        checkout = kit_service.issue(
            session,
            item,
            borrower_label=label,
            borrower=borrower,
            issued_by=user,
            project_id=payload.project_id,
            destination=payload.destination,
            taken_at=payload.taken_at,
            due_on=payload.due_on,
            condition_out=payload.condition_out,
            notes=payload.notes,
        )
    except kit_service.InventoryError as exc:
        raise _refuse(exc) from exc

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=item.id,
        resource_label=item.asset_number,
        summary=f"{item.asset_number} taken out by {label}",
        request=request,
    )
    session.flush()
    return CheckoutRead.model_validate(checkout)


@router.post(
    "/checkouts/{checkout_id}/return",
    response_model=CheckoutRead,
    summary="Bring an item back",
)
def check_in(
    checkout_id: uuid.UUID,
    payload: CheckoutReturn,
    session: DbSession,
    request: Request,
    user: InventoryContributor,
) -> CheckoutRead:
    checkout = records.get_or_404(session, Checkout, checkout_id, "Checkout")
    item = session.get(Equipment, checkout.equipment_id)

    try:
        kit_service.give_back(
            session,
            checkout,
            received_by=user,
            returned_at=payload.returned_at,
            condition_in=payload.condition_in,
            storage_location_id=payload.storage_location_id,
            notes=payload.notes,
        )
    except kit_service.InventoryError as exc:
        raise _refuse(exc) from exc

    if item is not None:
        activity.log(
            session,
            action=ActivityAction.UPDATE,
            user=user,
            resource_type=RESOURCE,
            resource_id=item.id,
            resource_label=item.asset_number,
            summary=f"{item.asset_number} returned by {checkout.borrower_label}",
            request=request,
        )
    session.flush()
    return CheckoutRead.model_validate(checkout)


@router.get(
    "/equipment/{equipment_id}/checkouts",
    response_model=Page[CheckoutRead],
    summary="Where this item has been",
)
def list_checkouts(
    equipment_id: uuid.UUID,
    session: DbSession,
    user: CurrentUserOptional,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CheckoutRead]:
    item = records.get_or_404(session, Equipment, equipment_id, "Equipment")
    _require_readable(user, item, "Equipment")

    statement = (
        select(Checkout)
        .where(Checkout.equipment_id == equipment_id)
        .order_by(Checkout.taken_at.desc())
    )
    rows, total = records.paginate(session, statement, limit, offset)
    return Page[CheckoutRead](
        items=[CheckoutRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------
@router.post(
    "/equipment/{equipment_id}/calibrations",
    response_model=CalibrationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record a calibration or service",
    description=(
        "The next due date comes from the certificate when it gives one, and "
        "from the item's own interval otherwise.\n\n"
        "Entering an old certificate found in a drawer is normal and will not "
        "move the due date backwards — only a calibration later than every "
        "other one on file changes what the item advertises about itself."
    ),
)
def add_calibration(
    equipment_id: uuid.UUID,
    payload: CalibrationCreate,
    session: DbSession,
    request: Request,
    user: InventoryContributor,
) -> CalibrationRead:
    item = records.get_or_404(session, Equipment, equipment_id, "Equipment")
    _require_editable(user, item, "Equipment")

    if payload.performed_on > date.today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A calibration cannot have been performed in the future",
        )

    calibration = kit_service.record_calibration(
        session,
        item,
        performed_on=payload.performed_on,
        result=payload.result,
        performed_by=payload.performed_by,
        certificate_number=payload.certificate_number,
        next_due_on=payload.next_due_on,
        cost=payload.cost,
        currency=payload.currency,
        notes=payload.notes,
        user=user,
    )
    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=item.id,
        resource_label=item.asset_number,
        summary=f"Calibration recorded for {item.asset_number}: {payload.result.value}",
        request=request,
    )
    session.flush()
    return CalibrationRead.model_validate(calibration)


@router.get(
    "/equipment/{equipment_id}/calibrations",
    response_model=Page[CalibrationRead],
    summary="Calibration history",
)
def list_calibrations(
    equipment_id: uuid.UUID,
    session: DbSession,
    user: CurrentUserOptional,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CalibrationRead]:
    item = records.get_or_404(session, Equipment, equipment_id, "Equipment")
    _require_readable(user, item, "Equipment")

    statement = (
        select(Calibration)
        .where(Calibration.equipment_id == equipment_id)
        .order_by(Calibration.performed_on.desc())
    )
    rows, total = records.paginate(session, statement, limit, offset)
    return Page[CalibrationRead](
        items=[CalibrationRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# --------------------------------------------------------------------------
# Consumables
# --------------------------------------------------------------------------
def _consumable_detail(
    session: DbSession, stock: Consumable, user: User | None
) -> ConsumableDetail:
    payload = ConsumableDetail.model_validate(stock)
    payload.storage_path = _storage_path(session, stock.storage_location_id)
    payload.needs_reorder = stock.reorder_level is not None and float(stock.quantity) <= float(
        stock.reorder_level
    )
    payload.expired = stock.expires_on is not None and stock.expires_on < date.today()
    payload.can_edit = _may_edit(user, stock)
    payload.can_delete = has_module_access(user, MODULE, Level.SUPERVISOR)
    return payload


@router.post(
    "/consumables",
    response_model=ConsumableDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Add a stock line",
)
def create_consumable(
    payload: ConsumableCreate, session: DbSession, request: Request, user: InventoryContributor
) -> ConsumableDetail:
    existing = session.scalar(select(Consumable).where(Consumable.code == payload.code))
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"{payload.code!r} is already the code for {existing.name!r}",
        )

    data = payload.model_dump()
    opening = data.pop("opening_quantity", 0) or 0
    stock = Consumable(**data, owner_id=user.id)
    session.add(stock)
    session.flush()

    # The opening figure goes in as a movement, not as a bare number, so the
    # ledger starts where the stock does and the total always has something
    # behind it.
    if opening:
        kit_service.apply_stock_change(
            session,
            stock,
            change=opening,
            reason=StockReason.STOCKTAKE,
            user=user,
            notes="Opening stock",
        )

    records.on_created(session, stock, RESOURCE, user=user, request=request, label=stock.code)
    session.flush()
    return _consumable_detail(session, stock, user)


@router.get(
    "/consumables",
    response_model=Page[ConsumableSummary],
    summary="Search the stock list",
)
def list_consumables(
    session: DbSession,
    user: CurrentUserOptional,
    q: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    storage_location_id: Annotated[uuid.UUID | None, Query()] = None,
    needs_reorder: Annotated[
        bool | None, Query(description="Only lines at or below their reorder level")
    ] = None,
    expiring_before: Annotated[date | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
    sort: Annotated[str, Query(pattern="^-?(code|name|quantity|created_at)$")] = "code",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ConsumableSummary]:
    statement = select(Consumable).where(_visible(user, Consumable))

    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Consumable.code).like(pattern),
                func.lower(Consumable.name).like(pattern),
                func.lower(Consumable.description).like(pattern),
            )
        )
    if category:
        statement = statement.where(Consumable.category == category)
    if storage_location_id is not None:
        statement = statement.where(Consumable.storage_location_id == storage_location_id)
    if needs_reorder:
        statement = statement.where(
            Consumable.reorder_level.is_not(None),
            Consumable.quantity <= Consumable.reorder_level,
        )
    if expiring_before is not None:
        statement = statement.where(
            Consumable.expires_on.is_not(None), Consumable.expires_on <= expiring_before
        )
    if is_active is not None:
        statement = statement.where(Consumable.is_active.is_(is_active))

    descending = sort.startswith("-")
    column = getattr(Consumable, sort.lstrip("-"))
    statement = statement.order_by(column.desc() if descending else column.asc(), Consumable.id)

    rows, total = records.paginate(session, statement, limit, offset)
    return Page[ConsumableSummary](
        items=[ConsumableSummary.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/consumables/{consumable_id}", response_model=ConsumableDetail, summary="Read a stock line"
)
def read_consumable(
    consumable_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> ConsumableDetail:
    stock = records.get_or_404(session, Consumable, consumable_id, "Stock line")
    _require_readable(user, stock, "Stock line")
    return _consumable_detail(session, stock, user)


@router.patch(
    "/consumables/{consumable_id}", response_model=ConsumableDetail, summary="Edit a stock line"
)
def update_consumable(
    consumable_id: uuid.UUID,
    payload: ConsumableUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> ConsumableDetail:
    stock = records.get_or_404(session, Consumable, consumable_id, "Stock line")
    _require_editable(user, stock, "Stock line")

    before = records.apply_changes(stock, payload.model_dump(exclude_unset=True))
    records.on_updated(session, stock, RESOURCE, before=before, user=user, request=request)
    session.flush()
    return _consumable_detail(session, stock, user)


@router.delete(
    "/consumables/{consumable_id}", response_model=Message, summary="Delete a stock line"
)
def delete_consumable(
    consumable_id: uuid.UUID, session: DbSession, request: Request, user: InventorySupervisor
) -> Message:
    stock = records.get_or_404(session, Consumable, consumable_id, "Stock line")
    label = f"{stock.code} {stock.name}"
    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=user,
        resource_type=RESOURCE,
        resource_id=stock.id,
        resource_label=stock.code,
        summary=f"Deleted stock line {label}",
        request=request,
    )
    session.delete(stock)
    session.flush()
    return Message(detail=f"Deleted {label}")


@router.post(
    "/consumables/{consumable_id}/movements",
    response_model=StockMovementRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record stock in or out",
    description=(
        "`change` is signed: positive for stock arriving, negative for stock "
        "leaving.\n\n"
        "This is the only way the quantity changes. Taking more than is on the "
        "shelf is refused rather than allowed to go negative — if the count is "
        "wrong, say so with a stock-take, which records the discrepancy as its "
        "own event instead of hiding it inside an issue."
    ),
)
def add_stock_movement(
    consumable_id: uuid.UUID,
    payload: StockMovementCreate,
    session: DbSession,
    request: Request,
    user: InventoryContributor,
) -> StockMovementRead:
    stock = records.get_or_404(session, Consumable, consumable_id, "Stock line")

    try:
        movement = kit_service.apply_stock_change(
            session,
            stock,
            change=payload.change,
            reason=payload.reason,
            user=user,
            project_id=payload.project_id,
            issued_to_label=payload.issued_to_label,
            notes=payload.notes,
            occurred_at=payload.occurred_at,
        )
    except kit_service.InventoryError as exc:
        raise _refuse(exc) from exc

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=stock.id,
        resource_label=stock.code,
        summary=(f"{stock.code}: {payload.change:+g} {stock.unit} ({payload.reason.value})"),
        request=request,
    )
    session.flush()
    return StockMovementRead.model_validate(movement)


@router.post(
    "/consumables/{consumable_id}/stock-take",
    response_model=StockMovementRead | Message,
    summary="Record what is actually on the shelf",
    description=(
        "The *difference* between the count and the record is written to the "
        "ledger, so a discrepancy shows up as an event somebody can ask about "
        "rather than being absorbed into a number that quietly changed.\n\n"
        "A count that agrees with the record writes nothing."
    ),
)
def record_stock_take(
    consumable_id: uuid.UUID,
    payload: StockTake,
    session: DbSession,
    request: Request,
    user: InventoryContributor,
) -> Any:
    stock = records.get_or_404(session, Consumable, consumable_id, "Stock line")

    try:
        movement = kit_service.stock_take(
            session,
            stock,
            counted=payload.counted,
            user=user,
            notes=payload.notes,
            occurred_at=payload.occurred_at,
        )
    except kit_service.InventoryError as exc:
        raise _refuse(exc) from exc

    if movement is None:
        return Message(
            detail=f"{stock.code} counted at {kit_service.tidy(payload.counted)} — the record agrees"
        )

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=stock.id,
        resource_label=stock.code,
        summary=f"Stock-take of {stock.code}: {float(movement.change):+g} {stock.unit}",
        request=request,
    )
    session.flush()
    return StockMovementRead.model_validate(movement)


@router.get(
    "/consumables/{consumable_id}/movements",
    response_model=Page[StockMovementRead],
    summary="The ledger behind the total",
)
def list_stock_movements(
    consumable_id: uuid.UUID,
    session: DbSession,
    user: CurrentUserOptional,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[StockMovementRead]:
    stock = records.get_or_404(session, Consumable, consumable_id, "Stock line")
    _require_readable(user, stock, "Stock line")

    statement = (
        select(StockMovement)
        .where(StockMovement.consumable_id == consumable_id)
        .order_by(StockMovement.occurred_at.desc(), StockMovement.created_at.desc())
    )
    rows, total = records.paginate(session, statement, limit, offset)
    return Page[StockMovementRead](
        items=[StockMovementRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# --------------------------------------------------------------------------
# Kit templates
# --------------------------------------------------------------------------
def _template_detail(
    session: DbSession, template: KitTemplate, user: User | None
) -> KitTemplateDetail:
    payload = KitTemplateDetail.model_validate(template)
    payload.line_count = len(template.lines)
    payload.lines = []
    for line in sorted(template.lines, key=lambda item: (item.position, item.id.hex)):
        read = KitTemplateLineRead.model_validate(line)
        read.label = kit_service.describe_line(session, line)
        payload.lines.append(read)
    payload.can_edit = _may_edit(user, template)
    payload.can_delete = has_module_access(user, MODULE, Level.SUPERVISOR)
    return payload


def _replace_lines(session: DbSession, template: KitTemplate, lines: list[Any]) -> None:
    template.lines.clear()
    session.flush()
    for position, line in enumerate(lines):
        data = line.model_dump()
        data["position"] = position
        template.lines.append(KitTemplateLine(**data))
    session.flush()


@router.post(
    "/kit-templates",
    response_model=KitTemplateDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Write a packing list",
    description=(
        "A line names exactly one of: a specific item, a consumable and a "
        "quantity, or a category and a count.\n\n"
        "Prefer the category. 'Two cameras' is what a packing list usually "
        "means, and a template pinned to camera 3 breaks the day camera 3 goes "
        "in for repair."
    ),
)
def create_template(
    payload: KitTemplateCreate, session: DbSession, request: Request, user: InventoryContributor
) -> KitTemplateDetail:
    existing = session.scalar(select(KitTemplate).where(KitTemplate.name == payload.name))
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"A packing list called {payload.name!r} exists"
        )

    template = KitTemplate(
        name=payload.name,
        description=payload.description,
        is_public=payload.is_public,
        owner_id=user.id,
    )
    session.add(template)
    session.flush()
    _replace_lines(session, template, payload.lines)

    records.on_created(session, template, RESOURCE, user=user, request=request, label=template.name)
    session.flush()
    return _template_detail(session, template, user)


@router.get("/kit-templates", response_model=Page[KitTemplateSummary], summary="Packing lists")
def list_templates(
    session: DbSession,
    user: CurrentUserOptional,
    is_active: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[KitTemplateSummary]:
    statement = select(KitTemplate).where(_visible(user, KitTemplate))
    if is_active is not None:
        statement = statement.where(KitTemplate.is_active.is_(is_active))
    statement = statement.order_by(KitTemplate.name)

    rows, total = records.paginate(session, statement, limit, offset)
    items = []
    for row in rows:
        summary = KitTemplateSummary.model_validate(row)
        summary.line_count = len(row.lines)
        items.append(summary)
    return Page[KitTemplateSummary](items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/kit-templates/{template_id}", response_model=KitTemplateDetail, summary="Read a packing list"
)
def read_template(
    template_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> KitTemplateDetail:
    template = records.get_or_404(session, KitTemplate, template_id, "Packing list")
    _require_readable(user, template, "Packing list")
    return _template_detail(session, template, user)


@router.patch(
    "/kit-templates/{template_id}", response_model=KitTemplateDetail, summary="Edit a packing list"
)
def update_template(
    template_id: uuid.UUID,
    payload: KitTemplateUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> KitTemplateDetail:
    template = records.get_or_404(session, KitTemplate, template_id, "Packing list")
    _require_editable(user, template, "Packing list")

    changes = payload.model_dump(exclude_unset=True)
    changes.pop("lines", None)
    before = records.apply_changes(template, changes)
    records.on_updated(session, template, RESOURCE, before=before, user=user, request=request)
    if payload.lines is not None:
        _replace_lines(session, template, payload.lines)

    session.flush()
    return _template_detail(session, template, user)


@router.delete(
    "/kit-templates/{template_id}", response_model=Message, summary="Delete a packing list"
)
def delete_template(
    template_id: uuid.UUID, session: DbSession, request: Request, user: InventorySupervisor
) -> Message:
    template = records.get_or_404(session, KitTemplate, template_id, "Packing list")
    name = template.name
    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=user,
        resource_type=RESOURCE,
        resource_id=template.id,
        resource_label=name,
        summary=f"Deleted packing list {name}",
        request=request,
    )
    session.delete(template)
    session.flush()
    return Message(detail=f"Deleted {name}")


# --------------------------------------------------------------------------
# Kits
# --------------------------------------------------------------------------
def _kit_detail(session: DbSession, kit: Kit, user: User | None) -> KitDetail:
    payload = KitDetail.model_validate(kit)
    payload.shortfalls = [KitShortfall.model_validate(entry) for entry in (kit.shortfalls or [])]

    today = date.today()
    rows = session.execute(
        select(Checkout, Equipment)
        .join(Equipment, Equipment.id == Checkout.equipment_id)
        .where(Checkout.kit_id == kit.id)
        .order_by(Checkout.taken_at)
    ).all()
    entries = []
    for checkout, item in rows:
        entry = CheckoutWithEquipment.model_validate(checkout)
        entry.asset_number = item.asset_number
        entry.equipment_name = item.name
        if checkout.due_on and checkout.due_on < today and checkout.returned_at is None:
            entry.days_overdue = (today - checkout.due_on).days
        entries.append(entry)
    payload.checkouts = entries
    payload.outstanding_items = sum(1 for entry in entries if entry.returned_at is None)

    payload.stock_movements = [
        StockMovementRead.model_validate(row)
        for row in session.scalars(
            select(StockMovement)
            .where(StockMovement.kit_id == kit.id)
            .order_by(StockMovement.occurred_at)
        ).all()
    ]

    payload.can_edit = _may_edit(user, kit)
    payload.can_delete = has_module_access(user, MODULE, Level.SUPERVISOR)
    return payload


@router.post(
    "/kit-templates/{template_id}/build",
    response_model=KitDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Fill a packing list and take it out",
    description=(
        "Checks out the equipment and issues the consumables in one action.\n\n"
        "What could not be supplied is recorded on the kit rather than raised "
        "as an error, because a kit that is nine tenths ready is still the kit "
        "going out this morning — and the shortfall list is what somebody reads "
        "before they drive off. Set `all_or_nothing` when a partial kit is "
        "worse than no kit."
    ),
)
def build(
    template_id: uuid.UUID,
    payload: KitBuild,
    session: DbSession,
    request: Request,
    user: InventoryContributor,
) -> KitDetail:
    template = records.get_or_404(session, KitTemplate, template_id, "Packing list")
    if not template.lines:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{template.name!r} has nothing on it yet",
        )

    issued_to = session.get(User, payload.issued_to_id) if payload.issued_to_id else None
    if payload.issued_to_id and issued_to is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That person does not exist")

    label = (payload.issued_to_label or "").strip() or (
        (issued_to.full_name or issued_to.username)
        if issued_to
        else (user.full_name or user.username)
    )

    try:
        kit, shortfalls = kit_service.build_kit(
            session,
            template,
            name=payload.name,
            issued_to_label=label,
            issued_to=issued_to,
            issued_by=user,
            project_id=payload.project_id,
            destination=payload.destination,
            issued_at=payload.issued_at,
            due_on=payload.due_on,
            notes=payload.notes,
            all_or_nothing=payload.all_or_nothing,
        )
    except kit_service.InventoryError as exc:
        # Nothing is written. The whole build runs inside the one transaction
        # the session dependency opened, and that dependency rolls back on any
        # exception — so a refused all-or-nothing build leaves the shelves
        # exactly as they were, including the lines it had already filled
        # before it reached the one it could not.
        raise _refuse(exc) from exc

    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=kit.id,
        resource_label=kit.name,
        summary=(
            f"Built {kit.name} for {label}"
            + (f" — {len(shortfalls)} shortfall(s)" if shortfalls else "")
        ),
        request=request,
    )
    session.flush()
    return _kit_detail(session, kit, user)


@router.get("/kits", response_model=Page[KitSummary], summary="Kits that have gone out")
def list_kits(
    session: DbSession,
    user: CurrentUserOptional,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    open_only: Annotated[bool, Query(description="Only kits not yet returned")] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[KitSummary]:
    statement = select(Kit).where(_visible(user, Kit))
    if project_id is not None:
        statement = statement.where(Kit.project_id == project_id)
    if open_only:
        statement = statement.where(Kit.returned_at.is_(None))
    statement = statement.order_by(Kit.issued_at.desc())

    rows, total = records.paginate(session, statement, limit, offset)
    return Page[KitSummary](
        items=[KitSummary.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/kits/{kit_id}", response_model=KitDetail, summary="Read a kit")
def read_kit(kit_id: uuid.UUID, session: DbSession, user: CurrentUserOptional) -> KitDetail:
    kit = records.get_or_404(session, Kit, kit_id, "Kit")
    _require_readable(user, kit, "Kit")
    return _kit_detail(session, kit, user)


@router.post(
    "/kits/{kit_id}/return",
    response_model=KitDetail,
    summary="Bring a whole kit back",
    description=(
        "Closes every loan in the kit that is still open. Consumables are not "
        "returned — that is what makes them consumables; anything genuinely "
        "unused goes back through the stock line as a `returned` movement."
    ),
)
def return_kit(
    kit_id: uuid.UUID,
    payload: KitReturn,
    session: DbSession,
    request: Request,
    user: InventoryContributor,
) -> KitDetail:
    kit = records.get_or_404(session, Kit, kit_id, "Kit")
    if kit.returned_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="That kit was already brought back")

    closed = kit_service.close_kit(
        session,
        kit,
        received_by=user,
        returned_at=payload.returned_at,
        condition_in=payload.condition_in,
        notes=payload.notes,
    )
    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=kit.id,
        resource_label=kit.name,
        summary=f"{kit.name} returned — {len(closed)} item(s) back on the shelf",
        request=request,
    )
    session.flush()
    return _kit_detail(session, kit, user)
