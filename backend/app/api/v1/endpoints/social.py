"""The social media repository: what the institution has said in public.

Outreach is a record, and this keeps it: the text as published, the images
used, which channel, when, and how it did. Kept here rather than fetched from
the platform it went out on, because that platform may not exist in ten years
and its API certainly will not.

Three decisions worth stating:

- **The platform publishes nothing.** It holds no API keys. An institution's
  outreach account is not something a records system should be able to post
  from unattended, so `/publish` records what a person did rather than doing
  it. What is worth archiving is the fact and the address, not the button.
- **Approval is its own action**, not a status somebody can set on a form.
  Outreach about an unpublished excavation has consequences for a permit, for
  a funder's embargo, and for who learns where to dig — so the record has to
  show who said yes.
- **The location check never blocks anything.** It says what a post would give
  away and lets a person decide. Sometimes revealing a location is exactly
  right, and a platform that refuses is one people work around — which loses
  the warning for the cases that matter.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, CurrentUserOptional, DbSession, require_module
from app.core.permissions import flat_can_edit, flat_visibility_filter, has_module_access
from app.models.enums import (
    ActivityAction,
    Module,
    PostStatus,
    ResourceType,
    SocialPlatform,
)
from app.models.enums import ModuleLevel as Level
from app.models.media import Photograph
from app.models.project import Project
from app.models.social import PostAsset, PostMetric, PostNote, SocialAccount, SocialPost
from app.models.user import User
from app.schemas.common import Message, Page
from app.schemas.social import (
    AccountCreate,
    AccountRead,
    AccountUpdate,
    ApprovalRequest,
    AssetAdd,
    AssetRead,
    ComposerRead,
    CoverageEntry,
    Engagement,
    LocationCheckResult,
    LocationFinding,
    MetricCreate,
    MetricRead,
    NoteCreate,
    NoteRead,
    OutreachSummary,
    PostCreate,
    PostDetail,
    PostSummary,
    PostUpdate,
    PublishRequest,
    SendBackRequest,
)
from app.services import activity, mail, outreach, records

router = APIRouter(prefix="/social", tags=["Social media"])

MODULE = Module.SOCIAL_MEDIA
#: Posts have no resource type of their own — they are *about* other records,
#: and the polymorphic tables exist to answer questions about those.
RESOURCE = ResourceType.PROJECT

SocialViewer = Annotated[User, Depends(require_module(MODULE, Level.VIEWER))]
SocialContributor = Annotated[User, Depends(require_module(MODULE, Level.CONTRIBUTOR))]
#: Approving a post is a supervisor's job. It is the point at which somebody
#: takes responsibility for what the institution says in public.
SocialSupervisor = Annotated[User, Depends(require_module(MODULE, Level.SUPERVISOR))]


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


def _as_result(check: outreach.LocationCheck) -> LocationCheckResult:
    return LocationCheckResult(
        clear=check.clear,
        summary=check.summary(),
        findings=[
            LocationFinding(
                kind=finding.kind, detail=finding.detail, photograph_id=finding.photograph_id
            )
            for finding in check.findings
        ],
    )


def _as_engagement(found: outreach.Engagement) -> Engagement:
    return Engagement(
        recorded_at=found.recorded_at,
        impressions=found.impressions,
        likes=found.likes,
        comments=found.comments,
        shares=found.shares,
        interactions=found.interactions,
        change=found.change,
        readings=found.readings,
    )


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------
def _account_read(session: DbSession, account: SocialAccount) -> AccountRead:
    payload = AccountRead.model_validate(account)
    counts = dict(
        session.execute(
            select(SocialPost.status, func.count(SocialPost.id))
            .where(SocialPost.account_id == account.id)
            .group_by(SocialPost.status)
        ).all()
    )
    payload.post_count = sum(counts.values())
    payload.published_count = counts.get(PostStatus.PUBLISHED, 0)
    payload.awaiting_approval = counts.get(PostStatus.NEEDS_APPROVAL, 0)
    return payload


@router.post(
    "/accounts",
    response_model=AccountRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a channel",
)
def create_account(
    payload: AccountCreate, session: DbSession, request: Request, user: SocialContributor
) -> AccountRead:
    handle = payload.handle.lstrip("@").strip()
    existing = session.scalar(
        select(SocialAccount).where(
            SocialAccount.platform == payload.platform, SocialAccount.handle == handle
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"@{handle} on {payload.platform.value} is already here",
        )

    data = payload.model_dump()
    data["handle"] = handle
    account = SocialAccount(**data, owner_id=user.id)
    session.add(account)
    session.flush()

    records.on_created(
        session, account, RESOURCE, user=user, request=request, label=f"@{account.handle}"
    )
    session.flush()
    return _account_read(session, account)


@router.get(
    "/composers",
    response_model=list[ComposerRead],
    summary="How each channel wants a post written",
    description=(
        "Writing for Instagram is not writing for Facebook. A caption goes "
        "under a picture and cannot carry a tappable link; a Facebook post is "
        "text that may have a link and may have no picture at all.\n\n"
        "Served rather than built into the client for the same reason form "
        "layouts are: these are conventions, they change when the platforms "
        "change, and they should change in one place. Every limit here is "
        "advisory - the platform counts and says so, and never refuses. It is "
        "not the one publishing."
    ),
)
def list_composers() -> list[ComposerRead]:
    return [
        ComposerRead.model_validate(asdict(composer))
        for composer in outreach.COMPOSERS.values()
    ]


@router.get("/accounts", response_model=Page[AccountRead], summary="The channels")
def list_accounts(
    session: DbSession,
    user: CurrentUserOptional,
    platform: Annotated[SocialPlatform | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AccountRead]:
    statement = select(SocialAccount).where(_visible(user, SocialAccount))
    if platform is not None:
        statement = statement.where(SocialAccount.platform == platform)
    if is_active is not None:
        statement = statement.where(SocialAccount.is_active.is_(is_active))
    statement = statement.order_by(SocialAccount.platform, SocialAccount.handle)

    rows, total = records.paginate(session, statement, limit, offset)
    return Page[AccountRead](
        items=[_account_read(session, row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/summary",
    response_model=OutreachSummary,
    summary="The module's front page",
    description=(
        "Counts worth opening the screen for. `with_location_warnings` is the "
        "one to act on first: those are posts the platform believes would give "
        "away where a site is."
    ),
)
def summary(session: DbSession, user: SocialViewer) -> OutreachSummary:
    visible_accounts = list(
        session.scalars(select(SocialAccount.id).where(_visible(user, SocialAccount))).all()
    )

    result = OutreachSummary(accounts=len(visible_accounts))
    if not visible_accounts:
        return result

    for state, count in session.execute(
        select(SocialPost.status, func.count(SocialPost.id))
        .where(SocialPost.account_id.in_(visible_accounts))
        .group_by(SocialPost.status)
    ).all():
        if state is PostStatus.PUBLISHED:
            result.published = count
        elif state is PostStatus.SCHEDULED:
            result.scheduled = count
        elif state is PostStatus.NEEDS_APPROVAL:
            result.awaiting_approval = count

    result.with_location_warnings = (
        session.scalar(
            select(func.count())
            .select_from(SocialPost)
            .where(
                SocialPost.account_id.in_(visible_accounts),
                SocialPost.location_warning.is_not(None),
                SocialPost.status.notin_([PostStatus.WITHDRAWN]),
            )
        )
        or 0
    )

    result.by_platform = {
        platform.value: count
        for platform, count in session.execute(
            select(SocialAccount.platform, func.count(SocialPost.id))
            .join(SocialPost, SocialPost.account_id == SocialAccount.id)
            .where(SocialAccount.id.in_(visible_accounts))
            .group_by(SocialAccount.platform)
        ).all()
    }
    return result


@router.patch("/accounts/{account_id}", response_model=AccountRead, summary="Edit a channel")
def update_account(
    account_id: uuid.UUID,
    payload: AccountUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> AccountRead:
    account = records.get_or_404(session, SocialAccount, account_id, "Account")
    _require_editable(user, account, "Account")

    changes = payload.model_dump(exclude_unset=True)
    if "handle" in changes and changes["handle"]:
        changes["handle"] = changes["handle"].lstrip("@").strip()

    before = records.apply_changes(account, changes)
    records.on_updated(session, account, RESOURCE, before=before, user=user, request=request)
    session.flush()
    return _account_read(session, account)


@router.delete(
    "/accounts/{account_id}",
    response_model=Message,
    summary="Delete a channel",
    description=(
        "Refused while it has posts. An account nobody posts to any more is "
        "still where years of outreach lives — mark it inactive instead, which "
        "takes it out of the way and keeps the archive."
    ),
)
def delete_account(
    account_id: uuid.UUID, session: DbSession, request: Request, user: SocialSupervisor
) -> Message:
    account = records.get_or_404(session, SocialAccount, account_id, "Account")

    posts = (
        session.scalar(
            select(func.count()).select_from(SocialPost).where(SocialPost.account_id == account.id)
        )
        or 0
    )
    if posts:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"@{account.handle} has {posts} post{'' if posts == 1 else 's'} on it. "
                f"Mark it inactive instead — that keeps the archive."
            ),
        )

    label = f"@{account.handle}"
    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=user,
        resource_type=RESOURCE,
        resource_id=account.id,
        resource_label=label,
        summary=f"Deleted channel {label}",
        request=request,
    )
    session.delete(account)
    session.flush()
    return Message(detail=f"Deleted {label}")


# --------------------------------------------------------------------------
# Posts
# --------------------------------------------------------------------------
def _tell_the_publishers(
    session: DbSession, post: SocialPost, approver: User, account: SocialAccount | None
) -> None:
    """E-mail whoever will actually put the post up.

    The platform publishes nothing itself - it holds no API keys, deliberately
    - so an approval is a message to a person: this is cleared, it is your turn.
    Without it the approval lands in a database and the post sits there, which
    is exactly what happened to every institution that ran this on paper.

    It goes to everybody with editor access or better to the social media
    module, minus the approver, who does not need telling what they just did.
    Mail never raises here: a mail server being down is not a reason for an
    approval to fail.
    """
    recipients = [
        user
        for user in session.scalars(select(User).where(User.is_active.is_(True))).all()
        if user.id != approver.id
        and user.email
        and has_module_access(user, MODULE, Level.EDITOR)
    ]
    if not recipients:
        return

    where = f"{account.platform.value} (@{account.handle})" if account else "the channel"
    signed_off_by = approver.full_name or approver.username
    body = "\n".join(
        [
            f"{signed_off_by} has approved a post for {where}:",
            "",
            f"    {post.title}",
            "",
            (post.body or "(no text yet)"),
            "",
            "It is cleared to go up. The platform does not post anything itself,",
            "so this is the point at which somebody puts it on the channel and",
            "records where it landed.",
        ]
    )
    if post.location_warning:
        body += (
            "\n\nOne thing to know before it goes out:\n"
            f"    {post.location_warning}"
        )

    mail.send(
        [user.email for user in recipients],
        subject=f"Ready to post: {post.title}",
        body=body,
    )


def _subject_label(session: DbSession, post: SocialPost) -> str | None:
    """What the post is about, in words.

    Deliberately generic. The social module does not import the museum's or
    archaeology's models to find a name — it reads the label off whichever
    record the polymorphic pair points at, the same way the activity log does.
    """
    if post.resource_type is None or post.resource_id is None:
        return None
    return records.label_for_resource(session, post.resource_type, post.resource_id)


def _assets(session: DbSession, post_id: uuid.UUID) -> list[AssetRead]:
    entries = []
    for asset, photograph in session.execute(
        select(PostAsset, Photograph)
        .join(Photograph, Photograph.id == PostAsset.photograph_id)
        .where(PostAsset.post_id == post_id)
        .order_by(PostAsset.position)
    ).all():
        entry = AssetRead.model_validate(asset)
        entry.filename = photograph.original_filename or photograph.title
        entry.thumbnail_url = f"/api/v1/photographs/{photograph.id}/thumbnail?size=600"
        entry.has_gps = photograph.latitude is not None and photograph.longitude is not None
        entries.append(entry)
    return entries


def _post_detail(session: DbSession, post: SocialPost, user: User | None) -> PostDetail:
    payload = PostDetail.model_validate(post)
    account = session.get(SocialAccount, post.account_id)
    if account is not None:
        payload.platform = account.platform
        payload.handle = account.handle

    payload.assets = _assets(session, post.id)
    payload.asset_count = len(payload.assets)
    payload.metrics = [
        MetricRead.model_validate(row)
        for row in session.scalars(
            select(PostMetric)
            .where(PostMetric.post_id == post.id)
            .order_by(PostMetric.recorded_at.desc())
        ).all()
    ]
    payload.engagement = _as_engagement(outreach.engagement(session, post.id))

    if post.project_id:
        project = session.get(Project, post.project_id)
        payload.project_name = project.name if project else None
    payload.subject_label = _subject_label(session, post)

    if post.approved_by_id:
        approver = session.get(User, post.approved_by_id)
        payload.approved_by_label = (approver.full_name or approver.username) if approver else None

    # Run fresh rather than showing the stored line: a photograph added since
    # the last save changes the answer, and a stale all-clear is worse than
    # none at all.
    payload.location_check = _as_result(outreach.check_location_disclosure(session, post))

    payload.notes_thread = _notes(session, post.id)

    payload.can_edit = _may_edit(user, post)
    payload.can_delete = has_module_access(user, MODULE, Level.SUPERVISOR)
    payload.can_approve = has_module_access(user, MODULE, Level.SUPERVISOR)
    return payload


def _notes(session: DbSession, post_id: uuid.UUID) -> list[NoteRead]:
    rows = []
    for note in session.scalars(
        select(PostNote).where(PostNote.post_id == post_id).order_by(PostNote.created_at)
    ).all():
        entry = NoteRead.model_validate(note)
        author = session.get(User, note.author_id) if note.author_id else None
        entry.author_label = (author.full_name or author.username) if author else None
        rows.append(entry)
    return rows


@router.post(
    "/accounts/{account_id}/posts",
    response_model=PostDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Draft a post",
)
def create_post(
    account_id: uuid.UUID,
    payload: PostCreate,
    session: DbSession,
    request: Request,
    user: SocialContributor,
) -> PostDetail:
    account = records.get_or_404(session, SocialAccount, account_id, "Account")
    if not account.is_active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"@{account.handle} is marked inactive. Reactivate it before posting to it.",
        )

    post = SocialPost(**payload.model_dump(), account_id=account.id, owner_id=user.id)
    session.add(post)
    session.flush()

    outreach.record_location_check(session, post)
    records.on_created(session, post, RESOURCE, user=user, request=request, label=post.title)
    session.flush()
    return _post_detail(session, post, user)


@router.get("/posts", response_model=Page[PostSummary], summary="Search the repository")
def list_posts(
    session: DbSession,
    user: CurrentUserOptional,
    q: Annotated[str | None, Query(description="Match the title or the text")] = None,
    account_id: Annotated[uuid.UUID | None, Query()] = None,
    platform: Annotated[SocialPlatform | None, Query()] = None,
    post_status: Annotated[PostStatus | None, Query(alias="status")] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    needs_attention: Annotated[
        bool, Query(description="Only posts awaiting approval or carrying a location warning")
    ] = False,
    since: Annotated[
        datetime | None, Query(description="Published or scheduled on or after")
    ] = None,
    sort: Annotated[
        str, Query(pattern="^-?(created_at|published_at|scheduled_for|title)$")
    ] = "-created_at",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[PostSummary]:
    statement = select(SocialPost, SocialAccount).join(
        SocialAccount, SocialAccount.id == SocialPost.account_id
    )
    statement = statement.where(_visible(user, SocialAccount))

    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(SocialPost.title).like(pattern),
                func.lower(SocialPost.body).like(pattern),
            )
        )
    if account_id is not None:
        statement = statement.where(SocialPost.account_id == account_id)
    if platform is not None:
        statement = statement.where(SocialAccount.platform == platform)
    if post_status is not None:
        statement = statement.where(SocialPost.status == post_status)
    if project_id is not None:
        statement = statement.where(SocialPost.project_id == project_id)
    if needs_attention:
        statement = statement.where(
            or_(
                SocialPost.status == PostStatus.NEEDS_APPROVAL,
                SocialPost.location_warning.is_not(None),
            ),
            SocialPost.status != PostStatus.WITHDRAWN,
        )
    if since is not None:
        statement = statement.where(
            or_(SocialPost.published_at >= since, SocialPost.scheduled_for >= since)
        )

    descending = sort.startswith("-")
    column = getattr(SocialPost, sort.lstrip("-"))
    statement = statement.order_by(column.desc() if descending else column.asc(), SocialPost.id)

    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = session.execute(statement.limit(limit).offset(offset)).all()

    items = []
    for post, account in rows:
        entry = PostSummary.model_validate(post)
        entry.platform = account.platform
        entry.handle = account.handle
        entry.asset_count = (
            session.scalar(
                select(func.count()).select_from(PostAsset).where(PostAsset.post_id == post.id)
            )
            or 0
        )
        entry.engagement = _as_engagement(outreach.engagement(session, post.id))
        items.append(entry)

    return Page[PostSummary](items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/coverage",
    response_model=list[CoverageEntry],
    summary="What has been said about one record",
    description=(
        "For a find's or a site's own card: every post that featured it. "
        "Answers the question asked before every press enquiry — have we "
        "already published this?"
    ),
)
def coverage(
    session: DbSession,
    user: SocialViewer,
    resource_type: Annotated[ResourceType, Query()],
    resource_id: Annotated[uuid.UUID, Query()],
) -> list[CoverageEntry]:
    rows = session.execute(
        select(SocialPost, SocialAccount)
        .join(SocialAccount, SocialAccount.id == SocialPost.account_id)
        .where(
            SocialPost.resource_type == resource_type,
            SocialPost.resource_id == resource_id,
            _visible(user, SocialAccount),
        )
        .order_by(SocialPost.published_at.desc().nullslast(), SocialPost.created_at.desc())
    ).all()

    return [
        CoverageEntry(
            id=post.id,
            title=post.title,
            platform=account.platform,
            handle=account.handle,
            status=post.status,
            published_at=post.published_at,
            external_url=post.external_url,
        )
        for post, account in rows
    ]


@router.get("/posts/{post_id}", response_model=PostDetail, summary="Read a post")
def read_post(post_id: uuid.UUID, session: DbSession, user: CurrentUserOptional) -> PostDetail:
    post = records.get_or_404(session, SocialPost, post_id, "Post")
    account = session.get(SocialAccount, post.account_id)
    _require_readable(user, account or post, "Post")
    return _post_detail(session, post, user)


@router.patch("/posts/{post_id}", response_model=PostDetail, summary="Edit a post")
def update_post(
    post_id: uuid.UUID,
    payload: PostUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> PostDetail:
    post = records.get_or_404(session, SocialPost, post_id, "Post")
    _require_editable(user, post, "Post")

    changes = payload.model_dump(exclude_unset=True)

    # Any substantive edit un-approves it. Approval is of a particular text
    # and a particular set of images; letting an approved post be rewritten
    # afterwards makes the approval meaningless, and does so silently.
    substantive = {"title", "body", "hashtags", "kind", "reveals_location"}
    if post.status is PostStatus.APPROVED and substantive & changes.keys():
        changes["status"] = PostStatus.NEEDS_APPROVAL
        changes["approved_by_id"] = None
        changes["approved_at"] = None
        changes["approval_note"] = "Withdrawn automatically: the post was edited after approval."

    before = records.apply_changes(post, changes)
    records.on_updated(session, post, RESOURCE, before=before, user=user, request=request)
    outreach.record_location_check(session, post)
    session.flush()
    return _post_detail(session, post, user)


@router.post(
    "/posts/{post_id}/approve",
    response_model=PostDetail,
    summary="Say yes to a post",
    description=(
        "Its own action rather than a status on a form, because the record has "
        "to show who took responsibility.\n\n"
        "The location check runs first and its result comes back with the "
        "response, so an approval is never given without the approver having "
        "been shown what the post would give away."
    ),
)
def approve_post(
    post_id: uuid.UUID,
    payload: ApprovalRequest,
    session: DbSession,
    request: Request,
    user: SocialSupervisor,
) -> PostDetail:
    post = records.get_or_404(session, SocialPost, post_id, "Post")

    if post.status is PostStatus.PUBLISHED:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="That post has already gone out.")
    if post.status is PostStatus.WITHDRAWN:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="That post was withdrawn. Copy it into a new one rather than reviving it.",
        )

    check = outreach.record_location_check(session, post)

    post.status = PostStatus.APPROVED
    post.approved_by_id = user.id
    post.approved_at = datetime.now(UTC)
    post.approval_note = payload.note
    if payload.note:
        session.add(
            PostNote(
                post_id=post.id, author_id=user.id, body=payload.note, decision="approved"
            )
        )

    _tell_the_publishers(session, post, user, session.get(SocialAccount, post.account_id))

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=post.id,
        resource_label=post.title,
        summary=(
            f"Approved post {post.title!r}"
            + ("" if check.clear else " — with an outstanding location warning")
        ),
        request=request,
    )
    session.flush()
    return _post_detail(session, post, user)


@router.post(
    "/posts/{post_id}/send-back",
    response_model=PostDetail,
    summary="Send a post back to be changed",
    description=(
        "The other half of approving. Approving is one bit and almost no real "
        "review is one bit - 'the find number is wrong', 'wait for the "
        "permit', 'crop the trowel out' are the substance of getting a post "
        "right.\n\n"
        "A reason is required: 'not yet' with nothing attached is a dead end "
        "for whoever wrote it."
    ),
)
def send_post_back(
    post_id: uuid.UUID,
    payload: SendBackRequest,
    session: DbSession,
    request: Request,
    user: SocialSupervisor,
) -> PostDetail:
    post = records.get_or_404(session, SocialPost, post_id, "Post")
    if post.status is PostStatus.PUBLISHED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="That post has already gone out. Withdraw it rather than sending it back.",
        )

    post.status = PostStatus.DRAFT
    post.approved_by_id = None
    post.approved_at = None
    post.approval_note = payload.note
    session.add(
        PostNote(post_id=post.id, author_id=user.id, body=payload.note, decision="sent_back")
    )

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=post.id,
        resource_label=post.title,
        summary=f"Sent post {post.title!r} back to be changed",
        request=request,
    )
    session.flush()
    return _post_detail(session, post, user)


@router.get(
    "/posts/{post_id}/notes",
    response_model=list[NoteRead],
    summary="What colleagues have said about a post",
)
def list_notes(post_id: uuid.UUID, session: DbSession, user: SocialViewer) -> list[NoteRead]:
    records.get_or_404(session, SocialPost, post_id, "Post")
    return _notes(session, post_id)


@router.post(
    "/posts/{post_id}/notes",
    response_model=NoteRead,
    status_code=status.HTTP_201_CREATED,
    summary="Say something about a post",
    description=(
        "Anybody who can see the module can leave a note - reviewing a post is "
        "not the same job as approving it, and the person who knows the find "
        "number is wrong is usually not the person who signs it off."
    ),
)
def add_note(
    post_id: uuid.UUID,
    payload: NoteCreate,
    session: DbSession,
    request: Request,
    user: SocialViewer,
) -> NoteRead:
    post = records.get_or_404(session, SocialPost, post_id, "Post")
    note = PostNote(post_id=post.id, author_id=user.id, body=payload.body.strip())
    session.add(note)
    session.flush()

    entry = NoteRead.model_validate(note)
    entry.author_label = user.full_name or user.username
    return entry


@router.post(
    "/posts/{post_id}/publish",
    response_model=PostDetail,
    summary="Record that it went out",
    description=(
        "The platform posts nothing itself. It holds no API keys, and an "
        "institution's outreach account is not something a records system "
        "should be able to publish from unattended — so this records what a "
        "person did, which is the part worth archiving."
    ),
)
def publish_post(
    post_id: uuid.UUID,
    payload: PublishRequest,
    session: DbSession,
    request: Request,
    user: SocialContributor,
) -> PostDetail:
    post = records.get_or_404(session, SocialPost, post_id, "Post")
    _require_editable(user, post, "Post")

    try:
        outreach.mark_published(
            session,
            post,
            url=payload.external_url,
            external_id=payload.external_id,
            when=payload.published_at,
        )
    except outreach.OutreachError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=post.id,
        resource_label=post.title,
        summary=f"Published {post.title!r}",
        request=request,
    )
    session.flush()
    return _post_detail(session, post, user)


@router.get(
    "/posts/{post_id}/location-check",
    response_model=LocationCheckResult,
    summary="What this post would give away",
    description=(
        "Publishing a findspot is how looting starts, and the usual way it "
        "happens is not somebody typing coordinates — it is a photograph going "
        "out with the GPS tag the camera wrote into it.\n\n"
        "Advisory throughout. It never blocks a post: sometimes revealing a "
        "location is exactly right, and a platform that refuses is one people "
        "work around."
    ),
)
def location_check(
    post_id: uuid.UUID, session: DbSession, user: SocialViewer
) -> LocationCheckResult:
    post = records.get_or_404(session, SocialPost, post_id, "Post")
    return _as_result(outreach.record_location_check(session, post))


@router.delete("/posts/{post_id}", response_model=Message, summary="Delete a post")
def delete_post(
    post_id: uuid.UUID, session: DbSession, request: Request, user: SocialSupervisor
) -> Message:
    post = records.get_or_404(session, SocialPost, post_id, "Post")

    if post.status is PostStatus.PUBLISHED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                "That post has been published. Withdraw it instead — "
                "'why was that taken down' is a question that gets asked, and "
                "a deleted row cannot answer it."
            ),
        )

    label = post.title
    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=user,
        resource_type=RESOURCE,
        resource_id=post.id,
        resource_label=label,
        summary=f"Deleted post {label!r}",
        request=request,
    )
    session.delete(post)
    session.flush()
    return Message(detail=f"Deleted {label}")


# --------------------------------------------------------------------------
# Images used
# --------------------------------------------------------------------------
@router.post(
    "/posts/{post_id}/assets",
    response_model=AssetRead,
    status_code=status.HTTP_201_CREATED,
    summary="Use a photograph in a post",
)
def add_asset(
    post_id: uuid.UUID,
    payload: AssetAdd,
    session: DbSession,
    user: SocialContributor,
) -> AssetRead:
    post = records.get_or_404(session, SocialPost, post_id, "Post")
    _require_editable(user, post, "Post")

    photograph = records.get_or_404(session, Photograph, payload.photograph_id, "Photograph")

    existing = session.scalar(
        select(PostAsset).where(
            PostAsset.post_id == post.id, PostAsset.photograph_id == photograph.id
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="That image is already on this post")

    position = payload.position
    if position is None:
        highest = session.scalar(
            select(func.max(PostAsset.position)).where(PostAsset.post_id == post.id)
        )
        position = 0 if highest is None else highest + 1

    asset = PostAsset(
        post_id=post.id,
        photograph_id=photograph.id,
        position=position,
        alt_text=payload.alt_text,
        credit=payload.credit,
    )
    session.add(asset)
    session.flush()

    # An added image can change the answer, so the stored warning is refreshed
    # here rather than waiting for somebody to open the post again.
    outreach.record_location_check(session, post)
    session.flush()

    entry = AssetRead.model_validate(asset)
    entry.filename = photograph.original_filename or photograph.title
    entry.thumbnail_url = f"/api/v1/photographs/{photograph.id}/thumbnail?size=600"
    entry.has_gps = photograph.latitude is not None and photograph.longitude is not None
    return entry


@router.delete(
    "/posts/{post_id}/assets/{asset_id}", response_model=Message, summary="Take an image off"
)
def remove_asset(
    post_id: uuid.UUID, asset_id: uuid.UUID, session: DbSession, user: SocialContributor
) -> Message:
    post = records.get_or_404(session, SocialPost, post_id, "Post")
    _require_editable(user, post, "Post")

    asset = session.get(PostAsset, asset_id)
    if asset is None or asset.post_id != post.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That image is not on this post")

    session.delete(asset)
    session.flush()
    outreach.record_location_check(session, post)
    session.flush()
    return Message(detail="Taken off the post")


# --------------------------------------------------------------------------
# Engagement
# --------------------------------------------------------------------------
@router.post(
    "/posts/{post_id}/metrics",
    response_model=MetricRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record how it did",
    description=(
        "A reading at a moment, not a running total. Typed in from the "
        "platform's own dashboard.\n\n"
        "Every figure is optional and a missing one stays missing: platforms "
        "report different things, and a zero meaning 'this platform does not "
        "tell us' is a zero that ruins an average."
    ),
)
def add_metric(
    post_id: uuid.UUID,
    payload: MetricCreate,
    session: DbSession,
    user: SocialContributor,
) -> MetricRead:
    post = records.get_or_404(session, SocialPost, post_id, "Post")
    _require_editable(user, post, "Post")

    when = payload.recorded_at or datetime.now(UTC)
    clash = session.scalar(
        select(PostMetric).where(PostMetric.post_id == post.id, PostMetric.recorded_at == when)
    )
    if clash is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                "There is already a reading for that moment. Two rows for one "
                "instant make every chart wrong in a way that looks like real "
                "growth."
            ),
        )

    data = payload.model_dump()
    data["recorded_at"] = when
    metric = PostMetric(**data, post_id=post.id)
    session.add(metric)
    session.flush()
    return MetricRead.model_validate(metric)


@router.get(
    "/posts/{post_id}/metrics", response_model=list[MetricRead], summary="How it has done over time"
)
def list_metrics(
    post_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> list[MetricRead]:
    post = records.get_or_404(session, SocialPost, post_id, "Post")
    account = session.get(SocialAccount, post.account_id)
    _require_readable(user, account or post, "Post")

    return [
        MetricRead.model_validate(row)
        for row in session.scalars(
            select(PostMetric).where(PostMetric.post_id == post_id).order_by(PostMetric.recorded_at)
        ).all()
    ]
