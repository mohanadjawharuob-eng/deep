"""The activity hub: what we did, what it took, and what it cost.

Permissions run through the **activities** module, which every account is given
on creation. That is the opposite decision from management, and it is
deliberate: this is the institution's shared memory, and a record of what a
season needed is only worth keeping if the people who will run the next one can
open it. Editing still follows the usual rule — a contributor changes what they
wrote, an editor changes anything.

Three endpoints here are the point of the module rather than plumbing:

``GET /activities/{id}/brief.txt``
    The whole activity as plain text, for pasting into an e-mail, printing, or
    taking to a meeting.
``POST /activities/{id}/email``
    The same text, sent. It returns the brief either way, so a machine with no
    outbound mail still gives somebody something to copy.
``POST /activities/{id}/repeat``
    Start the next one from the last one. Permits reset to needing
    re-application but keep how long they took; preparations come across
    unticked; costs come across as estimates.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, CurrentUserOptional, DbSession, require_module
from app.core.permissions import flat_can_edit, flat_visibility_filter, has_module_access
from app.models.activities import (
    Activity,
    ActivityCost,
    ActivityEquipment,
    ActivityPermit,
    ActivityPhoto,
    ActivityPreparation,
)
from app.models.enums import (
    ActivityAction,
    ActivityKind,
    ActivityStatus,
    Module,
    PermitStatus,
    ResourceType,
)
from app.models.enums import ModuleLevel as Level
from app.models.inventory import Equipment
from app.models.media import Photograph
from app.models.project import Project
from app.models.site import Site
from app.models.user import User
from app.schemas.activities import (
    ActivityCostCreate,
    ActivityCostRead,
    ActivityCostUpdate,
    ActivityCreate,
    ActivityDetail,
    ActivityEquipmentCreate,
    ActivityEquipmentRead,
    ActivityEquipmentUpdate,
    ActivityOption,
    ActivityPermitCreate,
    ActivityPermitRead,
    ActivityPermitUpdate,
    ActivityPhotoCreate,
    ActivityPhotoRead,
    ActivityPhotoUpdate,
    ActivityPreparationCreate,
    ActivityPreparationRead,
    ActivityPreparationUpdate,
    ActivitySummary,
    ActivityUpdate,
    BriefRequest,
    BriefResult,
    CostSummary,
    CurrencyLine,
    HubSummary,
    OutstandingSummary,
    RepeatRequest,
)
from app.schemas.common import Message, Page
from app.services import activity as activity_log
from app.services import logistics, mail, records

router = APIRouter(prefix="/activities", tags=["Activities"])

MODULE = Module.ACTIVITIES
RESOURCE = ResourceType.ACTIVITY

ActivityViewer = Annotated[User, Depends(require_module(MODULE, Level.VIEWER))]
ActivityContributor = Annotated[User, Depends(require_module(MODULE, Level.CONTRIBUTOR))]
ActivitySupervisor = Annotated[User, Depends(require_module(MODULE, Level.SUPERVISOR))]

#: Query parameter types. Declared at module level rather than subscripted
#: inline, because ``from __future__ import annotations`` turns an inline
#: ``Annotated[…]`` in a default into a string the linter reads as an
#: undefined name.
QSearch = Annotated[str | None, Query(description="Match title, summary, location or outcome")]
QKind = Annotated[ActivityKind | None, Query()]
QStatus = Annotated[ActivityStatus | None, Query(alias="status")]
QProject = Annotated[uuid.UUID | None, Query()]
QSite = Annotated[uuid.UUID | None, Query()]
QSince = Annotated[date | None, Query(description="Started on or after")]
QUntil = Annotated[date | None, Query(description="Started on or before")]
QOutstanding = Annotated[bool, Query(description="Only ones with work still to do")]
QSort = Annotated[str, Query(pattern="^-?(starts_on|title|kind|created_at)$")]


def _visible(user: User | None) -> Any:
    return flat_visibility_filter(user, Activity, MODULE)


def _may_edit(user: User | None, record: Any) -> bool:
    return flat_can_edit(user, record, MODULE)


def _require_readable(user: User | None, record: Activity) -> None:
    if has_module_access(user, MODULE, Level.VIEWER) or record.is_public:
        return
    raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Activity not found")


def _load(session: DbSession, activity_id: uuid.UUID, user: User | None) -> Activity:
    record = records.get_or_404(session, Activity, activity_id, "Activity")
    _require_readable(user, record)
    return record


def _load_for_edit(session: DbSession, activity_id: uuid.UUID, user: User | None) -> Activity:
    record = _load(session, activity_id, user)
    if not _may_edit(user, record):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You may not edit this activity")
    return record


def _name_of(session: DbSession, model: type[Any], record_id: uuid.UUID | None) -> str | None:
    if record_id is None:
        return None
    record = session.get(model, record_id)
    return records.label_for(record) if record is not None else None


def _days_between(later: date | None, earlier: date | None) -> int | None:
    if later is None or earlier is None:
        return None
    return (later - earlier).days


# --------------------------------------------------------------------------
# Child rows, in the shape a screen wants them
# --------------------------------------------------------------------------
def _equipment_read(session: DbSession, row: ActivityEquipment) -> ActivityEquipmentRead:
    payload = ActivityEquipmentRead.model_validate(row)
    if row.equipment_id is not None:
        item = session.get(Equipment, row.equipment_id)
        # A line pointing at kit that has since been deleted keeps its label
        # and says so, rather than quietly looking like free text.
        payload.equipment_exists = item is not None
        if item is not None:
            payload.equipment_name = item.name
            payload.asset_number = item.asset_number
    return payload


def _permit_read(row: ActivityPermit, *, today: date | None = None) -> ActivityPermitRead:
    payload = ActivityPermitRead.model_validate(row)
    payload.days_to_obtain = row.days_to_obtain
    payload.days_until_expiry = _days_between(row.expires_on, today or date.today())
    return payload


def _preparation_read(
    row: ActivityPreparation, *, today: date | None = None
) -> ActivityPreparationRead:
    payload = ActivityPreparationRead.model_validate(row)
    payload.days_until_due = _days_between(row.due_on, today or date.today())
    return payload


def _cost_read(row: ActivityCost) -> ActivityCostRead:
    payload = ActivityCostRead.model_validate(row)
    payload.total = float(Decimal(str(row.unit_cost)) * Decimal(str(row.quantity)))
    return payload


def _photo_read(session: DbSession, row: ActivityPhoto) -> ActivityPhotoRead:
    payload = ActivityPhotoRead.model_validate(row)
    photograph = session.get(Photograph, row.photograph_id)
    if photograph is not None:
        payload.title = photograph.title
        payload.taken_at = photograph.taken_at
        payload.photographer = photograph.photographer
        payload.thumbnail_url = f"/api/v1/photographs/{photograph.id}/thumbnail?size=600"
    return payload


def _counts(session: DbSession, activity_id: uuid.UUID) -> tuple[int, int, uuid.UUID | None]:
    photos = (
        session.scalar(
            select(func.count())
            .select_from(ActivityPhoto)
            .where(ActivityPhoto.activity_id == activity_id)
        )
        or 0
    )
    equipment = (
        session.scalar(
            select(func.count())
            .select_from(ActivityEquipment)
            .where(ActivityEquipment.activity_id == activity_id)
        )
        or 0
    )
    cover = session.scalar(
        select(ActivityPhoto.photograph_id)
        .where(ActivityPhoto.activity_id == activity_id, ActivityPhoto.is_cover.is_(True))
        .limit(1)
    )
    return photos, equipment, cover


def _summary(session: DbSession, record: Activity, *, today: date | None = None) -> ActivitySummary:
    payload = ActivitySummary.model_validate(record)
    payload.duration_days = record.duration_days
    payload.project_name = _name_of(session, Project, record.project_id)
    payload.site_name = _name_of(session, Site, record.site_id)
    payload.photo_count, payload.equipment_count, payload.cover_photo_id = _counts(
        session, record.id
    )
    still = logistics.outstanding(session, record, today=today)
    payload.outstanding_count = len(still.permits_outstanding) + len(still.preparations_outstanding)
    return payload


def _cost_summary(session: DbSession, record: Activity) -> CostSummary:
    figures = logistics.totals(session, record)
    return CostSummary(
        by_currency=[
            CurrencyLine(
                currency=code,
                amount=float(amount),
                estimated_amount=float(figures.estimated_by_currency.get(code, Decimal(0))),
            )
            for code, amount in sorted(figures.by_currency.items())
        ],
        line_count=figures.line_count,
        estimate_count=figures.estimate_count,
        linked_to_expenses=figures.linked_to_expenses,
        any_estimates=figures.any_estimates,
    )


def _detail(
    session: DbSession, record: Activity, user: User | None, *, today: date | None = None
) -> ActivityDetail:
    payload = ActivityDetail.model_validate(record)
    base = _summary(session, record, today=today)
    for name in (
        "duration_days",
        "project_name",
        "site_name",
        "photo_count",
        "equipment_count",
        "cover_photo_id",
        "outstanding_count",
    ):
        setattr(payload, name, getattr(base, name))

    payload.equipment = [
        _equipment_read(session, row)
        for row in session.scalars(
            select(ActivityEquipment)
            .where(ActivityEquipment.activity_id == record.id)
            .order_by(ActivityEquipment.position, ActivityEquipment.id)
        ).all()
    ]
    payload.permits = [
        _permit_read(row, today=today)
        for row in session.scalars(
            select(ActivityPermit)
            .where(ActivityPermit.activity_id == record.id)
            .order_by(ActivityPermit.position, ActivityPermit.id)
        ).all()
    ]
    payload.preparations = [
        _preparation_read(row, today=today)
        for row in session.scalars(
            select(ActivityPreparation)
            .where(ActivityPreparation.activity_id == record.id)
            .order_by(ActivityPreparation.position, ActivityPreparation.id)
        ).all()
    ]
    payload.costs = [
        _cost_read(row)
        for row in session.scalars(
            select(ActivityCost)
            .where(ActivityCost.activity_id == record.id)
            .order_by(ActivityCost.position, ActivityCost.id)
        ).all()
    ]
    payload.photos = [
        _photo_read(session, row)
        for row in session.scalars(
            select(ActivityPhoto)
            .where(ActivityPhoto.activity_id == record.id)
            .order_by(ActivityPhoto.position, ActivityPhoto.id)
        ).all()
    ]

    payload.cost_summary = _cost_summary(session, record)

    still = logistics.outstanding(session, record, today=today)
    payload.outstanding = OutstandingSummary(
        permits=still.permits_outstanding,
        preparations=still.preparations_outstanding,
        too_late=still.too_late,
        longest_lead_days=still.longest_lead_days,
        is_clear=still.is_clear,
        is_actionable=still.is_actionable,
    )

    payload.repeated_from_title = _name_of(session, Activity, record.repeated_from_id)
    payload.repeat_count = (
        session.scalar(
            select(func.count()).select_from(Activity).where(Activity.repeated_from_id == record.id)
        )
        or 0
    )

    payload.can_edit = _may_edit(user, record)
    payload.can_delete = has_module_access(user, MODULE, Level.SUPERVISOR)
    return payload


# --------------------------------------------------------------------------
# Activities
# --------------------------------------------------------------------------
@router.post(
    "",
    response_model=ActivityDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Record an activity",
)
def create_activity(
    payload: ActivityCreate, session: DbSession, request: Request, user: ActivityContributor
) -> ActivityDetail:
    record = Activity(**payload.model_dump(), owner_id=user.id)
    if record.lead_id is not None and not record.lead_label:
        lead = session.get(User, record.lead_id)
        if lead is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That person does not exist")
        record.lead_label = lead.full_name or lead.username

    session.add(record)
    session.flush()
    records.on_created(session, record, RESOURCE, user=user, request=request, label=record.title)
    session.flush()
    return _detail(session, record, user)


@router.get("", response_model=Page[ActivitySummary], summary="Search the hub")
def list_activities(
    session: DbSession,
    user: CurrentUserOptional,
    q: QSearch = None,
    kind: QKind = None,
    activity_status: QStatus = None,
    project_id: QProject = None,
    site_id: QSite = None,
    since: QSince = None,
    until: QUntil = None,
    outstanding_only: QOutstanding = False,
    sort: QSort = "-starts_on",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ActivitySummary]:
    statement = select(Activity).where(_visible(user))

    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Activity.title).like(pattern),
                func.lower(Activity.summary).like(pattern),
                func.lower(Activity.location).like(pattern),
                func.lower(Activity.outcome).like(pattern),
            )
        )
    if kind is not None:
        statement = statement.where(Activity.kind == kind)
    if activity_status is not None:
        statement = statement.where(Activity.status == activity_status)
    if project_id is not None:
        statement = statement.where(Activity.project_id == project_id)
    if site_id is not None:
        statement = statement.where(Activity.site_id == site_id)
    if since is not None:
        statement = statement.where(Activity.starts_on >= since)
    if until is not None:
        statement = statement.where(Activity.starts_on <= until)

    descending = sort.startswith("-")
    column = getattr(Activity, sort.lstrip("-"))
    # Undated activities sort last either way. A planning record with no date
    # yet is not the most recent thing that happened.
    ordering = column.desc().nullslast() if descending else column.asc().nullslast()
    statement = statement.order_by(ordering, Activity.id)

    rows, total = records.paginate(session, statement, limit, offset)
    items = [_summary(session, row) for row in rows]

    # Outstanding work is counted per row rather than stored, so it cannot be
    # filtered in SQL without a correlated subquery per activity. Filtering the
    # page costs a little arithmetic; the total is corrected to match so the
    # pager does not promise results that were filtered away.
    if outstanding_only:
        items = [item for item in items if item.outstanding_count > 0]
        total = len(items)

    return Page[ActivitySummary](items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/summary",
    response_model=HubSummary,
    summary="The hub's front page",
    description=(
        "What is coming up, what happened recently, and what still needs "
        "doing.\n\nDeclared before `/{id}`, which would otherwise read "
        "'summary' as an identifier."
    ),
)
def hub_summary(session: DbSession, user: ActivityViewer) -> HubSummary:
    today = date.today()
    visible = _visible(user)

    result = HubSummary()
    result.total = session.scalar(select(func.count()).select_from(Activity).where(visible)) or 0

    for value, count in session.execute(
        select(Activity.kind, func.count()).where(visible).group_by(Activity.kind)
    ).all():
        result.by_kind[value.value] = count
    for value, count in session.execute(
        select(Activity.status, func.count()).where(visible).group_by(Activity.status)
    ).all():
        result.by_status[value.value] = count

    upcoming = session.scalars(
        select(Activity)
        .where(visible, Activity.starts_on >= today)
        .order_by(Activity.starts_on)
        .limit(8)
    ).all()
    result.upcoming = [_summary(session, row, today=today) for row in upcoming]

    recent = session.scalars(
        select(Activity)
        .where(visible, Activity.starts_on < today)
        .order_by(Activity.starts_on.desc())
        .limit(8)
    ).all()
    result.recent = [_summary(session, row, today=today) for row in recent]

    # Only things that have not happened yet can still be prepared for. An
    # unfinished checklist on a season three years past is history, not a task.
    ahead = session.scalars(
        select(Activity)
        .where(
            visible,
            Activity.status.in_(
                [ActivityStatus.PLANNED, ActivityStatus.APPROVED, ActivityStatus.IN_PROGRESS]
            ),
        )
        .order_by(Activity.starts_on.asc().nullslast())
        .limit(50)
    ).all()
    result.needing_attention = [
        summary
        for summary in (_summary(session, row, today=today) for row in ahead)
        if summary.outstanding_count > 0
    ][:8]

    expiring = session.scalars(
        select(ActivityPermit)
        .join(Activity, Activity.id == ActivityPermit.activity_id)
        .where(
            visible,
            ActivityPermit.status == PermitStatus.GRANTED,
            ActivityPermit.expires_on.is_not(None),
            ActivityPermit.expires_on <= today + timedelta(days=30),
        )
        .order_by(ActivityPermit.expires_on)
        .limit(10)
    ).all()
    result.expiring_permits = [_permit_read(row, today=today) for row in expiring]

    return result


@router.get(
    "/options",
    response_model=list[ActivityOption],
    summary="Previous activities, for a dropdown",
    description=(
        "The list the calendar offers when somebody adds an event: pick what "
        "this day is part of, and the event fills itself in from it.\n\n"
        "Open to anyone signed in, and deliberately thin — it carries a name, "
        "a kind, a date and a place, and nothing else. Choosing a season from "
        "a list must not hand over its costings, its permits or its lessons; "
        "those stay behind the module, on `/activities/{id}`.\n\n"
        "Declared before `/{id}`."
    ),
)
def activity_options(
    session: DbSession,
    user: CurrentUser,
    q: QSearch = None,
    kind: QKind = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActivityOption]:
    # No visibility filter, unlike every other listing here. The calendar is
    # open to the whole institution and this is what its "part of…" dropdown
    # reads; filtering it by module level would leave somebody staring at an
    # empty list with no way to know why. Every account is seeded with the
    # activities module anyway (see SEEDED_MODULES), so in practice this widens
    # nothing — it only stops the dropdown breaking for an account whose access
    # was later narrowed.
    statement = select(Activity)
    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Activity.title).like(pattern),
                func.lower(Activity.location).like(pattern),
            )
        )
    if kind is not None:
        statement = statement.where(Activity.kind == kind)

    rows = session.scalars(
        statement.order_by(Activity.starts_on.desc().nullslast(), Activity.title).limit(limit)
    ).all()

    options = []
    for row in rows:
        parts = [row.kind.value.replace("_", " ").capitalize()]
        if row.starts_on:
            parts.append(row.starts_on.isoformat())
        if row.location:
            parts.append(row.location)
        options.append(
            ActivityOption(
                id=row.id,
                title=row.title,
                kind=row.kind,
                status=row.status,
                starts_on=row.starts_on,
                location=row.location,
                label=f"{row.title} — {' · '.join(parts)}",
            )
        )
    return options


@router.get("/{activity_id}", response_model=ActivityDetail, summary="Read an activity")
def read_activity(
    activity_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> ActivityDetail:
    return _detail(session, _load(session, activity_id, user), user)


@router.patch("/{activity_id}", response_model=ActivityDetail, summary="Edit an activity")
def update_activity(
    activity_id: uuid.UUID,
    payload: ActivityUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> ActivityDetail:
    record = _load_for_edit(session, activity_id, user)

    changes = payload.model_dump(exclude_unset=True)
    if changes.get("lead_id") and not changes.get("lead_label"):
        lead = session.get(User, changes["lead_id"])
        if lead is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That person does not exist")
        changes["lead_label"] = lead.full_name or lead.username

    before = records.apply_changes(record, changes)
    if record.starts_on and record.ends_on and record.ends_on < record.starts_on:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The activity would end before it starts",
        )
    records.on_updated(session, record, RESOURCE, before=before, user=user, request=request)
    session.flush()
    return _detail(session, record, user)


@router.delete("/{activity_id}", response_model=Message, summary="Delete an activity")
def delete_activity(
    activity_id: uuid.UUID, session: DbSession, request: Request, user: ActivitySupervisor
) -> Message:
    record = records.get_or_404(session, Activity, activity_id, "Activity")
    label = record.title
    records.on_deleted(session, record, RESOURCE, user=user, request=request, label=label)
    session.delete(record)
    session.flush()
    return Message(detail=f"Deleted {label}")


# --------------------------------------------------------------------------
# The brief
# --------------------------------------------------------------------------
@router.get(
    "/{activity_id}/brief.txt",
    response_class=Response,
    summary="The logistics as plain text",
    description=(
        "Kit, permissions, preparations and costs, in a form that survives "
        "e-mail, printing and being read on a phone in a field."
    ),
    responses={200: {"content": {"text/plain": {}}, "description": "The brief"}},
)
def activity_brief(
    activity_id: uuid.UUID, session: DbSession, request: Request, user: CurrentUserOptional
) -> Response:
    record = _load(session, activity_id, user)
    text = logistics.brief(session, record)

    activity_log.log(
        session,
        action=ActivityAction.EXPORT,
        user=user,
        resource_type=RESOURCE,
        resource_id=record.id,
        resource_label=record.title,
        summary=f"Exported the brief for {record.title}",
        request=request,
    )
    session.flush()

    # A filename with spaces or a slash in it breaks the header, and an
    # activity called "Survey 2019 / north" is entirely normal.
    stem = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in record.title).strip("-")
    return Response(
        content=text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem or "activity"}-brief.txt"'},
    )


@router.post(
    "/{activity_id}/email",
    response_model=BriefResult,
    summary="E-mail the logistics",
    description=(
        "Sends the same text the brief endpoint returns.\n\n"
        "**Never fails the request because mail did not go out.** This "
        "platform is built to run on a laptop in a dig house with no outbound "
        "mail, so the response carries the brief itself either way and says "
        "plainly whether it was sent — leaving somebody with something to "
        "copy rather than an error."
    ),
)
def email_brief(
    activity_id: uuid.UUID,
    payload: BriefRequest,
    session: DbSession,
    request: Request,
    user: ActivityContributor,
) -> BriefResult:
    record = _load(session, activity_id, user)
    text = logistics.brief(session, record)

    body = text
    if payload.message:
        body = f"{payload.message.strip()}\n\n{'-' * 60}\n\n{text}"

    recipients = [str(address) for address in payload.to]
    result = mail.send(
        recipients,
        payload.subject or logistics.brief_subject(record),
        body,
        reply_to=user.email,
    )

    activity_log.log(
        session,
        action=ActivityAction.EXPORT,
        user=user,
        resource_type=RESOURCE,
        resource_id=record.id,
        resource_label=record.title,
        summary=(
            f"{'E-mailed' if result.ok else 'Tried to e-mail'} the brief for "
            f"{record.title} to {', '.join(recipients)}"
        ),
        request=request,
    )
    session.flush()

    return BriefResult(
        sent=result.ok,
        detail=result.detail,
        recipients=recipients if result.ok else [],
        brief=text,
    )


@router.post(
    "/{activity_id}/repeat",
    response_model=ActivityDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Do it again",
    description=(
        "Starts a new activity from this one. Equipment carries over as it "
        "was; permits come across needing re-application but keeping how long "
        "they took last time; preparations come across unticked; costs come "
        "across marked as estimates. Photographs, the outcome and the lessons "
        "stay with the activity they describe — the new one links back, so "
        "they are one click away."
    ),
)
def repeat_activity(
    activity_id: uuid.UUID,
    payload: RepeatRequest,
    session: DbSession,
    request: Request,
    user: ActivityContributor,
) -> ActivityDetail:
    source = _load(session, activity_id, user)

    fresh = logistics.repeat(
        session,
        source,
        title=payload.title,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
        user=user,
        copy_costs=payload.copy_costs,
    )
    records.on_created(session, fresh, RESOURCE, user=user, request=request, label=fresh.title)
    session.flush()
    return _detail(session, fresh, user)


# --------------------------------------------------------------------------
# Equipment
# --------------------------------------------------------------------------
@router.post(
    "/{activity_id}/equipment",
    response_model=ActivityEquipmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add to the kit list",
)
def add_equipment(
    activity_id: uuid.UUID,
    payload: ActivityEquipmentCreate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> ActivityEquipmentRead:
    record = _load_for_edit(session, activity_id, user)

    data = payload.model_dump()
    label = (data.pop("label", None) or "").strip()
    if data.get("equipment_id") is not None:
        item = session.get(Equipment, data["equipment_id"])
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That equipment does not exist")
        # Copied, not looked up on read, so the kit list still reads correctly
        # after the item is retired, renamed or deleted.
        label = label or item.name

    row = ActivityEquipment(**data, label=label, activity_id=record.id)
    session.add(row)
    session.flush()

    activity_log.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=record.id,
        resource_label=record.title,
        summary=f"{record.title}: added {logistics.tidy(row.quantity)} × {row.label} to the kit",
        request=request,
    )
    session.flush()
    return _equipment_read(session, row)


@router.patch(
    "/{activity_id}/equipment/{line_id}",
    response_model=ActivityEquipmentRead,
    summary="Edit a kit line",
)
def update_equipment(
    activity_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: ActivityEquipmentUpdate,
    session: DbSession,
    user: CurrentUser,
) -> ActivityEquipmentRead:
    _load_for_edit(session, activity_id, user)
    row = _child_or_404(session, ActivityEquipment, line_id, activity_id, "Kit line")
    records.apply_changes(row, payload.model_dump(exclude_unset=True))
    session.flush()
    return _equipment_read(session, row)


@router.delete(
    "/{activity_id}/equipment/{line_id}", response_model=Message, summary="Remove a kit line"
)
def delete_equipment(
    activity_id: uuid.UUID, line_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> Message:
    _load_for_edit(session, activity_id, user)
    row = _child_or_404(session, ActivityEquipment, line_id, activity_id, "Kit line")
    label = row.label
    session.delete(row)
    session.flush()
    return Message(detail=f"Removed {label}")


# --------------------------------------------------------------------------
# Permits
# --------------------------------------------------------------------------
@router.post(
    "/{activity_id}/permits",
    response_model=ActivityPermitRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record a permission",
)
def add_permit(
    activity_id: uuid.UUID,
    payload: ActivityPermitCreate,
    session: DbSession,
    user: CurrentUser,
) -> ActivityPermitRead:
    record = _load_for_edit(session, activity_id, user)
    row = ActivityPermit(**payload.model_dump(), activity_id=record.id)
    _learn_lead_time(row)
    session.add(row)
    session.flush()
    return _permit_read(row)


@router.patch(
    "/{activity_id}/permits/{permit_id}",
    response_model=ActivityPermitRead,
    summary="Edit a permission",
)
def update_permit(
    activity_id: uuid.UUID,
    permit_id: uuid.UUID,
    payload: ActivityPermitUpdate,
    session: DbSession,
    user: CurrentUser,
) -> ActivityPermitRead:
    _load_for_edit(session, activity_id, user)
    row = _child_or_404(session, ActivityPermit, permit_id, activity_id, "Permit")

    changes = payload.model_dump(exclude_unset=True)
    # Marking it granted without saying when leaves the lead time unknowable,
    # and the lead time is the reason this table exists.
    if changes.get("status") is PermitStatus.GRANTED and not (
        changes.get("granted_on") or row.granted_on
    ):
        changes["granted_on"] = date.today()
    if changes.get("status") is PermitStatus.APPLIED and not (
        changes.get("applied_on") or row.applied_on
    ):
        changes["applied_on"] = date.today()

    records.apply_changes(row, changes)
    _learn_lead_time(row)
    session.flush()
    return _permit_read(row)


def _learn_lead_time(row: ActivityPermit) -> None:
    """Fill in the lead time from the dates, when nobody has typed one.

    A figure somebody wrote down beats a single observation — they may know the
    ministry is slower in summer — so a hand-entered value is never overwritten.
    """
    if row.lead_time_days is None:
        row.lead_time_days = row.days_to_obtain


@router.delete(
    "/{activity_id}/permits/{permit_id}", response_model=Message, summary="Delete a permission"
)
def delete_permit(
    activity_id: uuid.UUID, permit_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> Message:
    _load_for_edit(session, activity_id, user)
    row = _child_or_404(session, ActivityPermit, permit_id, activity_id, "Permit")
    label = row.name
    session.delete(row)
    session.flush()
    return Message(detail=f"Deleted {label}")


# --------------------------------------------------------------------------
# Preparations
# --------------------------------------------------------------------------
@router.post(
    "/{activity_id}/preparations",
    response_model=ActivityPreparationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a preparation",
)
def add_preparation(
    activity_id: uuid.UUID,
    payload: ActivityPreparationCreate,
    session: DbSession,
    user: CurrentUser,
) -> ActivityPreparationRead:
    record = _load_for_edit(session, activity_id, user)

    data = payload.model_dump()
    # A lead time and a start date together already say when it is due; making
    # somebody work that out and type it in is how checklists go stale.
    if data.get("due_on") is None and data.get("lead_time_days") is not None and record.starts_on:
        data["due_on"] = record.starts_on - timedelta(days=data["lead_time_days"])

    row = ActivityPreparation(**data, activity_id=record.id)
    session.add(row)
    session.flush()
    return _preparation_read(row)


@router.patch(
    "/{activity_id}/preparations/{step_id}",
    response_model=ActivityPreparationRead,
    summary="Edit a preparation",
)
def update_preparation(
    activity_id: uuid.UUID,
    step_id: uuid.UUID,
    payload: ActivityPreparationUpdate,
    session: DbSession,
    user: CurrentUser,
) -> ActivityPreparationRead:
    _load_for_edit(session, activity_id, user)
    row = _child_or_404(session, ActivityPreparation, step_id, activity_id, "Preparation")

    changes = payload.model_dump(exclude_unset=True)
    # Ticking it off records the day, and un-ticking it clears the day, so a
    # reopened step does not still claim to have been finished.
    if "is_done" in changes and changes["is_done"] != row.is_done:
        changes["done_on"] = date.today() if changes["is_done"] else None

    records.apply_changes(row, changes)
    session.flush()
    return _preparation_read(row)


@router.delete(
    "/{activity_id}/preparations/{step_id}",
    response_model=Message,
    summary="Delete a preparation",
)
def delete_preparation(
    activity_id: uuid.UUID, step_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> Message:
    _load_for_edit(session, activity_id, user)
    row = _child_or_404(session, ActivityPreparation, step_id, activity_id, "Preparation")
    label = row.description
    session.delete(row)
    session.flush()
    return Message(detail=f"Deleted {label}")


# --------------------------------------------------------------------------
# Costs
# --------------------------------------------------------------------------
@router.post(
    "/{activity_id}/costs",
    response_model=ActivityCostRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record what something cost",
)
def add_cost(
    activity_id: uuid.UUID,
    payload: ActivityCostCreate,
    session: DbSession,
    user: CurrentUser,
) -> ActivityCostRead:
    record = _load_for_edit(session, activity_id, user)
    row = ActivityCost(**payload.model_dump(), activity_id=record.id)
    session.add(row)
    session.flush()
    return _cost_read(row)


@router.patch(
    "/{activity_id}/costs/{cost_id}", response_model=ActivityCostRead, summary="Correct a cost"
)
def update_cost(
    activity_id: uuid.UUID,
    cost_id: uuid.UUID,
    payload: ActivityCostUpdate,
    session: DbSession,
    user: CurrentUser,
) -> ActivityCostRead:
    _load_for_edit(session, activity_id, user)
    row = _child_or_404(session, ActivityCost, cost_id, activity_id, "Cost")
    records.apply_changes(row, payload.model_dump(exclude_unset=True))
    session.flush()
    return _cost_read(row)


@router.delete("/{activity_id}/costs/{cost_id}", response_model=Message, summary="Delete a cost")
def delete_cost(
    activity_id: uuid.UUID, cost_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> Message:
    _load_for_edit(session, activity_id, user)
    row = _child_or_404(session, ActivityCost, cost_id, activity_id, "Cost")
    label = row.description
    session.delete(row)
    session.flush()
    return Message(detail=f"Deleted {label}")


# --------------------------------------------------------------------------
# Photographs
# --------------------------------------------------------------------------
@router.post(
    "/{activity_id}/photos",
    response_model=ActivityPhotoRead,
    status_code=status.HTTP_201_CREATED,
    summary="Attach a photograph",
)
def add_photo(
    activity_id: uuid.UUID,
    payload: ActivityPhotoCreate,
    session: DbSession,
    user: CurrentUser,
) -> ActivityPhotoRead:
    record = _load_for_edit(session, activity_id, user)

    if session.get(Photograph, payload.photograph_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That photograph does not exist")

    existing = session.scalar(
        select(ActivityPhoto).where(
            ActivityPhoto.activity_id == record.id,
            ActivityPhoto.photograph_id == payload.photograph_id,
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="That photograph is already on this activity"
        )

    if payload.is_cover:
        _clear_cover(session, record.id)

    row = ActivityPhoto(**payload.model_dump(), activity_id=record.id)
    session.add(row)
    session.flush()
    return _photo_read(session, row)


@router.patch(
    "/{activity_id}/photos/{photo_id}",
    response_model=ActivityPhotoRead,
    summary="Edit an attached photograph",
)
def update_photo(
    activity_id: uuid.UUID,
    photo_id: uuid.UUID,
    payload: ActivityPhotoUpdate,
    session: DbSession,
    user: CurrentUser,
) -> ActivityPhotoRead:
    _load_for_edit(session, activity_id, user)
    row = _child_or_404(session, ActivityPhoto, photo_id, activity_id, "Photograph")

    changes = payload.model_dump(exclude_unset=True)
    if changes.get("is_cover"):
        _clear_cover(session, activity_id, except_id=row.id)

    records.apply_changes(row, changes)
    session.flush()
    return _photo_read(session, row)


@router.delete(
    "/{activity_id}/photos/{photo_id}",
    response_model=Message,
    summary="Detach a photograph",
    description=(
        "Removes it from this activity. The photograph itself is untouched — "
        "it belongs to the project it was taken for."
    ),
)
def delete_photo(
    activity_id: uuid.UUID, photo_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> Message:
    _load_for_edit(session, activity_id, user)
    row = _child_or_404(session, ActivityPhoto, photo_id, activity_id, "Photograph")
    session.delete(row)
    session.flush()
    return Message(detail="Detached the photograph")


def _clear_cover(
    session: DbSession, activity_id: uuid.UUID, *, except_id: uuid.UUID | None = None
) -> None:
    """At most one cover per activity, so a list never has two of them."""
    statement = select(ActivityPhoto).where(
        ActivityPhoto.activity_id == activity_id, ActivityPhoto.is_cover.is_(True)
    )
    if except_id is not None:
        statement = statement.where(ActivityPhoto.id != except_id)
    for row in session.scalars(statement).all():
        row.is_cover = False


def _child_or_404(
    session: DbSession,
    model: type[Any],
    row_id: uuid.UUID,
    activity_id: uuid.UUID,
    name: str,
) -> Any:
    """Fetch a child row, refusing one that belongs to a different activity.

    Checking the parent matters: without it, knowing any row's id would let
    somebody edit it through an activity they *can* edit, which is a hole the
    permission check above would not see.
    """
    row = session.get(model, row_id)
    if row is None or row.activity_id != activity_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{name} not found")
    return row
