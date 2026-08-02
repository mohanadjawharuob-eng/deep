"""Management: budgets, expenses, tasks and the calendar.

Permissions run through the **management** module, and it is the most closed
of the five by default. A field director needs no sight of what a conservator
is paid, and an excavation's grant correspondence is not something a student
volunteer should stumble into. Nothing here is public unless somebody
deliberately makes it so.

Two decisions shape the money endpoints:

- **A budget's balance is never written.** It is summed from the expenses on
  read. There is no field to set and no way to correct it except by correcting
  the expenses, which is the point.
- **An overspend is reported, not refused.** A grant genuinely does get
  overspent. A platform that will not let somebody record what happened is a
  platform where the real figures live in a spreadsheet nobody else can see —
  which is worse than an overspend everybody can.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, CurrentUserOptional, DbSession, require_module
from app.core.permissions import flat_can_edit, flat_visibility_filter, has_module_access
from app.models.activities import Activity
from app.models.enums import (
    ActivityAction,
    BudgetStatus,
    ExpenseStatus,
    Module,
    ResourceType,
    TaskStatus,
)
from app.models.enums import ModuleLevel as Level
from app.models.management import Budget, CalendarEvent, Expense, Task
from app.models.project import Project
from app.models.user import User
from app.schemas.common import Message, Page
from app.schemas.management import (
    BudgetCreate,
    BudgetDetail,
    BudgetSummary,
    BudgetTotals,
    BudgetUpdate,
    CategoryLine,
    EventCreate,
    EventRead,
    EventUpdate,
    ExpenseCreate,
    ExpenseCreated,
    ExpenseRead,
    ExpenseUpdate,
    TaskBoard,
    TaskCreate,
    TaskRead,
    TaskUpdate,
)
from app.services import activity, finance, records

router = APIRouter(prefix="/management", tags=["Management"])

MODULE = Module.MANAGEMENT
#: Budgets and tasks have no resource type of their own. They are institutional
#: records rather than heritage ones, and the polymorphic tables exist to
#: answer questions about objects — so they log against the project.
RESOURCE = ResourceType.PROJECT

ManagementViewer = Annotated[User, Depends(require_module(MODULE, Level.VIEWER))]
ManagementContributor = Annotated[User, Depends(require_module(MODULE, Level.CONTRIBUTOR))]
ManagementSupervisor = Annotated[User, Depends(require_module(MODULE, Level.SUPERVISOR))]


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


def _project_name(session: DbSession, project_id: uuid.UUID | None) -> str | None:
    if project_id is None:
        return None
    project = session.get(Project, project_id)
    return project.name if project else None


def _humanise(value: str) -> str:
    return value.replace("_", " ").capitalize()


# --------------------------------------------------------------------------
# Budgets
# --------------------------------------------------------------------------
def _apply_position(payload: Any, where: finance.Position) -> None:
    """Copy the summed figures onto a response. Never the other way round."""
    payload.paid = float(where.paid)
    payload.committed = float(where.committed)
    payload.planned = float(where.planned)
    payload.spent = float(where.spent)
    payload.available = float(where.available)
    payload.used_percent = round(where.used_percent, 1)
    payload.overspent = where.overspent


def _budget_detail(session: DbSession, budget: Budget, user: User | None) -> BudgetDetail:
    payload = BudgetDetail.model_validate(budget)
    where = finance.position(session, budget)
    _apply_position(payload, where)

    lines = finance.by_category(session, budget.id)
    total = sum((line.amount for line in lines), Decimal(0))
    payload.by_category = [
        CategoryLine(
            category=line.category,
            label=_humanise(line.category.value),
            amount=float(line.amount),
            count=line.count,
            percent=round(float(line.amount / total * 100), 1) if total else 0.0,
        )
        for line in lines
    ]

    payload.expense_count = (
        session.scalar(
            select(func.count()).select_from(Expense).where(Expense.budget_id == budget.id)
        )
        or 0
    )
    payload.project_name = _project_name(session, budget.project_id)
    # Unspent grant money usually has to be returned, and nobody finds out by
    # accident in time.
    payload.expired_with_funds = bool(
        budget.ends_on and budget.ends_on < date.today() and where.available > 0
    )
    payload.can_edit = _may_edit(user, budget)
    payload.can_delete = has_module_access(user, MODULE, Level.SUPERVISOR)
    return payload


@router.post(
    "/budgets",
    response_model=BudgetDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Add a fund",
)
def create_budget(
    payload: BudgetCreate, session: DbSession, request: Request, user: ManagementContributor
) -> BudgetDetail:
    existing = session.scalar(select(Budget).where(Budget.code == payload.code))
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"{payload.code!r} is already the code for {existing.name!r}",
        )

    budget = Budget(**payload.model_dump(), owner_id=user.id)
    session.add(budget)
    session.flush()

    records.on_created(session, budget, RESOURCE, user=user, request=request, label=budget.code)
    session.flush()
    return _budget_detail(session, budget, user)


@router.get("/budgets", response_model=Page[BudgetSummary], summary="Search the funds")
def list_budgets(
    session: DbSession,
    user: CurrentUserOptional,
    q: Annotated[str | None, Query(description="Match code, name or funder")] = None,
    budget_status: Annotated[BudgetStatus | None, Query(alias="status")] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    overspent: Annotated[bool | None, Query(description="Only funds that are over")] = None,
    sort: Annotated[str, Query(pattern="^-?(code|name|amount|ends_on|created_at)$")] = "code",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[BudgetSummary]:
    statement = select(Budget).where(_visible(user, Budget))

    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Budget.code).like(pattern),
                func.lower(Budget.name).like(pattern),
                func.lower(Budget.funder).like(pattern),
                func.lower(Budget.grant_reference).like(pattern),
            )
        )
    if budget_status is not None:
        statement = statement.where(Budget.status == budget_status)
    if project_id is not None:
        statement = statement.where(Budget.project_id == project_id)

    descending = sort.startswith("-")
    column = getattr(Budget, sort.lstrip("-"))
    statement = statement.order_by(column.desc() if descending else column.asc(), Budget.id)

    rows, total = records.paginate(session, statement, limit, offset)

    items = []
    for row in rows:
        summary = BudgetSummary.model_validate(row)
        _apply_position(summary, finance.position(session, row))
        items.append(summary)

    # Filtering on a figure that is summed rather than stored cannot be done
    # in SQL without a correlated subquery per row. Doing it here costs a page
    # of arithmetic, and the page total is corrected to match so the pager
    # does not promise results that were filtered away.
    if overspent is not None:
        items = [item for item in items if item.overspent is overspent]
        total = len(items)

    return Page[BudgetSummary](items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/budgets/totals",
    response_model=BudgetTotals,
    summary="Every fund at once",
    description=(
        "The module's front page. Available balances are broken down by "
        "currency as well as summed, because adding a dinar to a dollar "
        "produces a number that is wrong in a way nobody notices until a "
        "funder does.\n\n"
        "Declared before `/budgets/{id}`, which would otherwise read "
        "'totals' as an identifier."
    ),
)
def budget_totals(session: DbSession, user: ManagementViewer) -> BudgetTotals:
    visible = list(session.scalars(select(Budget.id).where(_visible(user, Budget))).all())
    summary = finance.summarise(session, visible)
    return BudgetTotals(
        total=float(summary.total),
        spent=float(summary.spent),
        available=float(summary.available),
        budget_count=len(visible),
        by_currency={key: float(value) for key, value in summary.by_currency.items()},
        needing_attention=summary.needing_attention,
    )


@router.get("/budgets/{budget_id}", response_model=BudgetDetail, summary="Read a fund")
def read_budget(
    budget_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> BudgetDetail:
    budget = records.get_or_404(session, Budget, budget_id, "Budget")
    _require_readable(user, budget, "Budget")
    return _budget_detail(session, budget, user)


@router.patch("/budgets/{budget_id}", response_model=BudgetDetail, summary="Edit a fund")
def update_budget(
    budget_id: uuid.UUID,
    payload: BudgetUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> BudgetDetail:
    budget = records.get_or_404(session, Budget, budget_id, "Budget")
    _require_editable(user, budget, "Budget")

    before = records.apply_changes(budget, payload.model_dump(exclude_unset=True))
    records.on_updated(session, budget, RESOURCE, before=before, user=user, request=request)
    session.flush()
    return _budget_detail(session, budget, user)


@router.delete(
    "/budgets/{budget_id}",
    response_model=Message,
    summary="Delete a fund",
    description=(
        "Refused while it has spending against it. A grant with expenses is "
        "a financial record somebody may have to answer for years later; "
        "**close** it instead, which stops further spending and keeps every "
        "line."
    ),
)
def delete_budget(
    budget_id: uuid.UUID, session: DbSession, request: Request, user: ManagementSupervisor
) -> Message:
    budget = records.get_or_404(session, Budget, budget_id, "Budget")

    spending = (
        session.scalar(
            select(func.count()).select_from(Expense).where(Expense.budget_id == budget.id)
        )
        or 0
    )
    if spending:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"{budget.code} has {spending} expense{'' if spending == 1 else 's'} "
                f"against it. Close it instead — that stops further spending and "
                f"keeps the record."
            ),
        )

    label = f"{budget.code} {budget.name}"
    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=user,
        resource_type=RESOURCE,
        resource_id=budget.id,
        resource_label=budget.code,
        summary=f"Deleted fund {label}",
        request=request,
    )
    session.delete(budget)
    session.flush()
    return Message(detail=f"Deleted {label}")


# --------------------------------------------------------------------------
# Expenses
# --------------------------------------------------------------------------
@router.post(
    "/budgets/{budget_id}/expenses",
    response_model=ExpenseCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Record spending",
    description=(
        "Never refused for going over. A grant genuinely does get overspent, "
        "and a platform that will not let somebody write down what happened "
        "is one where the real figures live in a spreadsheet nobody else can "
        "see. The response says by how much, so the screen can say so too."
    ),
)
def add_expense(
    budget_id: uuid.UUID,
    payload: ExpenseCreate,
    session: DbSession,
    request: Request,
    user: ManagementContributor,
) -> ExpenseCreated:
    budget = records.get_or_404(session, Budget, budget_id, "Budget")

    if budget.status in {BudgetStatus.CLOSED, BudgetStatus.CANCELLED}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"{budget.code} is {budget.status.value}. Reopen it before "
                f"charging anything else to it."
            ),
        )

    excess = finance.would_overspend(session, budget, payload.amount)

    data = payload.model_dump()
    # The budget's currency unless the line says otherwise, which is almost
    # always right and saves retyping it on every expense.
    data["currency"] = data.pop("currency", None) or budget.currency
    expense = Expense(**data, budget_id=budget.id, owner_id=user.id)
    session.add(expense)
    session.flush()

    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=budget.id,
        resource_label=budget.code,
        summary=(
            f"{budget.code}: {expense.amount} {expense.currency} — {expense.description}"
            + (f" (over by {excess})" if excess else "")
        ),
        request=request,
    )
    session.flush()

    result = ExpenseCreated.model_validate(expense)
    result.overspent_by = float(excess) if excess else None
    result.budget_available_after = float(finance.position(session, budget).available)
    result.budget_code = budget.code
    result.budget_name = budget.name
    return result


@router.get(
    "/expenses",
    response_model=Page[ExpenseRead],
    summary="Search spending",
    description="Across every fund, or within one. The ledger a bookkeeper reads.",
)
def list_expenses(
    session: DbSession,
    user: ManagementViewer,
    budget_id: Annotated[uuid.UUID | None, Query()] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    expense_status: Annotated[ExpenseStatus | None, Query(alias="status")] = None,
    since: Annotated[date | None, Query(description="Spent on or after")] = None,
    until: Annotated[date | None, Query(description="Spent on or before")] = None,
    q: Annotated[str | None, Query(description="Match description, supplier or reference")] = None,
    sort: Annotated[str, Query(pattern="^-?(spent_on|amount|created_at)$")] = "-spent_on",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ExpenseRead]:
    statement = select(Expense, Budget).join(Budget, Budget.id == Expense.budget_id)

    if budget_id is not None:
        statement = statement.where(Expense.budget_id == budget_id)
    if project_id is not None:
        statement = statement.where(Expense.project_id == project_id)
    if category:
        statement = statement.where(Expense.category == category)
    if expense_status is not None:
        statement = statement.where(Expense.status == expense_status)
    if since is not None:
        statement = statement.where(Expense.spent_on >= since)
    if until is not None:
        statement = statement.where(Expense.spent_on <= until)
    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Expense.description).like(pattern),
                func.lower(Expense.supplier).like(pattern),
                func.lower(Expense.reference).like(pattern),
            )
        )

    descending = sort.startswith("-")
    column = getattr(Expense, sort.lstrip("-"))
    statement = statement.order_by(column.desc() if descending else column.asc(), Expense.id)

    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = session.execute(statement.limit(limit).offset(offset)).all()

    items = []
    for expense, budget in rows:
        entry = ExpenseRead.model_validate(expense)
        entry.budget_code = budget.code
        entry.budget_name = budget.name
        items.append(entry)

    return Page[ExpenseRead](items=items, total=total, limit=limit, offset=offset)


@router.patch("/expenses/{expense_id}", response_model=ExpenseRead, summary="Correct spending")
def update_expense(
    expense_id: uuid.UUID,
    payload: ExpenseUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> ExpenseRead:
    expense = records.get_or_404(session, Expense, expense_id, "Expense")
    _require_editable(user, expense, "Expense")

    changes = payload.model_dump(exclude_unset=True)
    # Marking it paid without saying when is the common case, and a paid line
    # with no date is a line that cannot be reconciled against a statement.
    if changes.get("status") is ExpenseStatus.PAID and not (
        changes.get("paid_on") or expense.paid_on
    ):
        changes["paid_on"] = date.today()

    before = records.apply_changes(expense, changes)
    records.on_updated(session, expense, RESOURCE, before=before, user=user, request=request)
    session.flush()
    return ExpenseRead.model_validate(expense)


@router.delete("/expenses/{expense_id}", response_model=Message, summary="Delete spending")
def delete_expense(
    expense_id: uuid.UUID, session: DbSession, request: Request, user: ManagementSupervisor
) -> Message:
    expense = records.get_or_404(session, Expense, expense_id, "Expense")
    label = expense.description
    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=user,
        resource_type=RESOURCE,
        resource_id=expense.budget_id,
        resource_label=label,
        summary=f"Deleted expense: {label}",
        request=request,
    )
    session.delete(expense)
    session.flush()
    return Message(detail=f"Deleted {label}")


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------
def _task_read(session: DbSession, task: Task) -> TaskRead:
    payload = TaskRead.model_validate(task)
    payload.project_name = _project_name(session, task.project_id)
    if task.due_on and task.status not in {TaskStatus.DONE, TaskStatus.CANCELLED}:
        overdue = (date.today() - task.due_on).days
        payload.days_overdue = overdue if overdue > 0 else None
    return payload


@router.post(
    "/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED, summary="Add a task"
)
def create_task(
    payload: TaskCreate, session: DbSession, request: Request, user: ManagementContributor
) -> TaskRead:
    data = payload.model_dump()

    assignee = session.get(User, data["assignee_id"]) if data.get("assignee_id") else None
    if data.get("assignee_id") and assignee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That person does not exist")
    if assignee is not None and not data.get("assignee_label"):
        data["assignee_label"] = assignee.full_name or assignee.username

    # New tasks go to the top of the list rather than the bottom: a task
    # somebody just typed is the one they are thinking about.
    lowest = session.scalar(select(func.min(Task.position))) or 0
    task = Task(**data, position=float(lowest) - 1, owner_id=user.id)
    session.add(task)
    session.flush()

    records.on_created(session, task, RESOURCE, user=user, request=request, label=task.title)
    session.flush()
    return _task_read(session, task)


@router.get("/tasks", response_model=Page[TaskRead], summary="Search tasks")
def list_tasks(
    session: DbSession,
    user: ManagementViewer,
    task_status: Annotated[TaskStatus | None, Query(alias="status")] = None,
    assignee_id: Annotated[uuid.UUID | None, Query()] = None,
    mine: Annotated[bool, Query(description="Only tasks assigned to you")] = False,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    overdue: Annotated[bool, Query(description="Only unfinished tasks past their date")] = False,
    q: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[TaskRead]:
    statement = select(Task).where(_visible(user, Task))

    if task_status:
        statement = statement.where(Task.status == task_status)
    if mine:
        statement = statement.where(Task.assignee_id == user.id)
    elif assignee_id is not None:
        statement = statement.where(Task.assignee_id == assignee_id)
    if project_id is not None:
        statement = statement.where(Task.project_id == project_id)
    if overdue:
        statement = statement.where(
            Task.due_on.is_not(None),
            Task.due_on < date.today(),
            Task.status.notin_([TaskStatus.DONE, TaskStatus.CANCELLED]),
        )
    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(func.lower(Task.title).like(pattern), func.lower(Task.description).like(pattern))
        )

    statement = statement.order_by(Task.position, Task.created_at)
    rows, total = records.paginate(session, statement, limit, offset)
    return Page[TaskRead](
        items=[_task_read(session, row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/tasks/board",
    response_model=TaskBoard,
    summary="Tasks as a board",
    description=(
        "Grouped by status, in the order somebody has arranged them.\n\n"
        "Declared before `/tasks/{id}`, which would otherwise read 'board' "
        "as an identifier."
    ),
)
def task_board(
    session: DbSession,
    user: ManagementViewer,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    mine: Annotated[bool, Query()] = False,
) -> TaskBoard:
    statement = select(Task).where(_visible(user, Task))
    if project_id is not None:
        statement = statement.where(Task.project_id == project_id)
    if mine:
        statement = statement.where(Task.assignee_id == user.id)
    statement = statement.order_by(Task.position, Task.created_at)

    board = TaskBoard()
    columns = {
        "todo": board.todo,
        "in_progress": board.in_progress,
        "blocked": board.blocked,
        "done": board.done,
    }
    for task in session.scalars(statement).all():
        entry = _task_read(session, task)
        if entry.days_overdue:
            board.overdue_count += 1
        column = columns.get(task.status.value)
        # Cancelled tasks are on no column. They are kept for the record, not
        # for the board — a board that shows them is a board with a growing
        # pile of things nobody is going to do.
        if column is not None:
            column.append(entry)
    return board


@router.get("/tasks/{task_id}", response_model=TaskRead, summary="Read a task")
def read_task(task_id: uuid.UUID, session: DbSession, user: CurrentUserOptional) -> TaskRead:
    task = records.get_or_404(session, Task, task_id, "Task")
    _require_readable(user, task, "Task")
    return _task_read(session, task)


@router.patch("/tasks/{task_id}", response_model=TaskRead, summary="Edit a task")
def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> TaskRead:
    task = records.get_or_404(session, Task, task_id, "Task")
    _require_editable(user, task, "Task")

    changes = payload.model_dump(exclude_unset=True)

    if "assignee_id" in changes and changes["assignee_id"]:
        assignee = session.get(User, changes["assignee_id"])
        if assignee is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That person does not exist")
        if not changes.get("assignee_label"):
            changes["assignee_label"] = assignee.full_name or assignee.username

    # "Finished last week" has to be answerable without reading the log, and
    # reopening a task must not leave it claiming a completion date.
    new_status = changes.get("status")
    if new_status is not None and new_status != task.status:
        if new_status is TaskStatus.DONE:
            changes["completed_at"] = datetime.now(UTC)
            changes["completed_by_id"] = user.id
        elif task.status is TaskStatus.DONE:
            changes["completed_at"] = None
            changes["completed_by_id"] = None

    before = records.apply_changes(task, changes)
    records.on_updated(session, task, RESOURCE, before=before, user=user, request=request)
    session.flush()
    return _task_read(session, task)


@router.delete("/tasks/{task_id}", response_model=Message, summary="Delete a task")
def delete_task(
    task_id: uuid.UUID, session: DbSession, request: Request, user: ManagementSupervisor
) -> Message:
    task = records.get_or_404(session, Task, task_id, "Task")
    label = task.title
    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=user,
        resource_type=RESOURCE,
        resource_id=task.id,
        resource_label=label,
        summary=f"Deleted task: {label}",
        request=request,
    )
    session.delete(task)
    session.flush()
    return Message(detail=f"Deleted {label}")


# --------------------------------------------------------------------------
# Calendar
# --------------------------------------------------------------------------
# The one part of this module that is *not* closed.
#
# Everything else here is deliberately private — a field director needs no
# sight of what a conservator is paid. The calendar is the opposite: it is the
# institution's shared diary, and a diary only half the staff can write in is a
# diary that is wrong within a fortnight. So reading it and adding to it need
# nothing but a signed-in account, and the module level only governs *other
# people's* entries.
#
# Changing an entry still follows the ordinary rule — your own, or a
# supervisor's — because "everybody can add a day" and "anybody can move
# anybody's day" are different propositions, and only the first was asked for.
def _may_edit_event(user: User | None, event: CalendarEvent) -> bool:
    if user is None:
        return False
    if event.owner_id is not None and event.owner_id == user.id:
        return True
    return has_module_access(user, MODULE, Level.SUPERVISOR)


def _event_read(session: DbSession, event: CalendarEvent, user: User | None) -> EventRead:
    result = EventRead.model_validate(event)
    result.project_name = _project_name(session, event.project_id)
    if event.activity_id is not None:
        linked = session.get(Activity, event.activity_id)
        if linked is not None:
            result.activity_title = linked.title
            result.activity_kind = linked.kind.value
    result.can_edit = _may_edit_event(user, event)
    return result


def _fill_from_activity(session: DbSession, data: dict[str, Any]) -> None:
    """Take what the event did not say from the activity it points at.

    This is the whole of the "automatic workflow": pick the season from the
    dropdown and the day names itself, sits in the right place, and carries the
    project across. Only *blank* fields are filled, so anything typed by hand
    always wins.
    """
    activity_id = data.get("activity_id")
    if activity_id is None:
        return

    linked = session.get(Activity, activity_id)
    if linked is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That activity does not exist")

    if not (data.get("title") or "").strip():
        data["title"] = linked.title
    if not data.get("location"):
        data["location"] = linked.location
    if not data.get("kind"):
        data["kind"] = linked.kind.value
    if data.get("project_id") is None:
        data["project_id"] = linked.project_id
    if data.get("budget_id") is None:
        data["budget_id"] = linked.budget_id


@router.post(
    "/events",
    response_model=EventRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add an event",
    description=(
        "Open to anyone signed in. The calendar is the institution's shared "
        "diary and everybody keeps it.\n\n"
        "Give `activity_id` and the event fills itself in from that activity "
        "— its title, where it is, what kind of thing it is, and the project "
        "and fund it belongs to. Anything typed by hand wins over what the "
        "activity would have supplied."
    ),
)
def create_event(
    payload: EventCreate, session: DbSession, request: Request, user: CurrentUser
) -> EventRead:
    data = payload.model_dump()
    _fill_from_activity(session, data)

    event = CalendarEvent(**data, owner_id=user.id)
    session.add(event)
    session.flush()

    records.on_created(session, event, RESOURCE, user=user, request=request, label=event.title)
    session.flush()
    return _event_read(session, event, user)


@router.get(
    "/events",
    response_model=Page[EventRead],
    summary="The calendar",
    description=(
        "Events overlapping the window, not merely starting inside it. A "
        "field season running June to August is happening in July, and a "
        "calendar that hides it when you look at July is a calendar people "
        "stop trusting."
    ),
)
def list_events(
    session: DbSession,
    user: CurrentUser,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    activity_id: Annotated[uuid.UUID | None, Query()] = None,
    kind: Annotated[str | None, Query()] = None,
    mine: Annotated[bool, Query(description="Only entries you added")] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[EventRead]:
    # No visibility filter. The calendar is shared, and an entry only some of
    # the team can see defeats the point of having one.
    statement = select(CalendarEvent)

    if activity_id is not None:
        statement = statement.where(CalendarEvent.activity_id == activity_id)
    if mine:
        statement = statement.where(CalendarEvent.owner_id == user.id)
    if until is not None:
        statement = statement.where(CalendarEvent.starts_at <= until)
    if since is not None:
        # An event with no end is a point in time; one with an end overlaps
        # the window if it finishes at or after the window opens.
        statement = statement.where(
            or_(
                CalendarEvent.ends_at.is_(None) & (CalendarEvent.starts_at >= since),
                CalendarEvent.ends_at >= since,
            )
        )
    if project_id is not None:
        statement = statement.where(CalendarEvent.project_id == project_id)
    if kind:
        statement = statement.where(CalendarEvent.kind == kind)

    statement = statement.order_by(CalendarEvent.starts_at)
    rows, total = records.paginate(session, statement, limit, offset)

    return Page[EventRead](
        items=[_event_read(session, row, user) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch(
    "/events/{event_id}",
    response_model=EventRead,
    summary="Edit an event",
    description=(
        "Your own entries, or anybody's if you supervise the management "
        "module. Everyone may *add* to the shared calendar; moving somebody "
        "else's day is a different thing and needs the seniority."
    ),
)
def update_event(
    event_id: uuid.UUID,
    payload: EventUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> EventRead:
    event = records.get_or_404(session, CalendarEvent, event_id, "Event")
    if not _may_edit_event(user, event):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Somebody else added this. Ask them, or a supervisor, to change it.",
        )

    changes = payload.model_dump(exclude_unset=True)
    if changes.get("activity_id") is not None:
        # Attaching an existing event to an activity fills in whatever the
        # event does not already say, and never overwrites what it does. A day
        # somebody titled "Ahmed's last shift" stays that, and gains the link.
        merged = {
            name: changes.get(name, getattr(event, name))
            for name in ("title", "location", "kind", "project_id", "budget_id")
        }
        merged["activity_id"] = changes["activity_id"]
        _fill_from_activity(session, merged)
        # What the request asked for still wins; the activity only supplied
        # what was blank in both the request and the event.
        changes = merged | changes

    before = records.apply_changes(event, changes)
    if event.ends_at and event.ends_at < event.starts_at:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The event would end before it starts"
        )

    records.on_updated(session, event, RESOURCE, before=before, user=user, request=request)
    session.flush()
    return _event_read(session, event, user)


@router.delete(
    "/events/{event_id}",
    response_model=Message,
    summary="Delete an event",
    description="Your own entries, or anybody's if you supervise the module.",
)
def delete_event(
    event_id: uuid.UUID, session: DbSession, request: Request, user: CurrentUser
) -> Message:
    event = records.get_or_404(session, CalendarEvent, event_id, "Event")
    if not _may_edit_event(user, event):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Somebody else added this. Ask them, or a supervisor, to remove it.",
        )
    label = event.title
    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=user,
        resource_type=RESOURCE,
        resource_id=event.id,
        resource_label=label,
        summary=f"Deleted event: {label}",
        request=request,
    )
    session.delete(event)
    session.flush()
    return Message(detail=f"Deleted {label}")
