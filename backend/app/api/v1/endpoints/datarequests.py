"""Asking somebody outside the platform for a file, and letting them send it.

Two halves, and the seam between them is the point.

**Behind the sign-in**: making a request, seeing what is outstanding, chasing
it, withdrawing it. Ordinary endpoints with ordinary permissions — you may ask
for files for a record you could contribute to, and no other.

**In front of it**: two routes that take no session at all, only the token from
the invitation. They are the reason the feature is useful — the photographer
with the site pictures does not have an account and is not going to make one —
and the reason it needs care. What a token buys is bounded on every axis:

* one record, named when the request was made and not changeable afterwards;
* a fixed number of files, then the link closes itself;
* an expiry, chosen when the request was made;
* write only. There is no route here that reads a record, lists anything, or
  says who else was asked.

Files that arrive go through exactly the validation an uploaded file goes
through — decoded if an image, size-capped, checksummed, deduplicated. A file
arriving by invitation is no more trustworthy than one arriving from a signed-in
user, and it is treated as no less either: it lands in the archive attached to
the record it was asked for, which is the entire point of asking.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.models import (
    ActivityAction,
    DataRequest,
    DataRequestStatus,
    Document,
    Photograph,
    ResourceType,
    ReviewStatus,
    UserRole,
)
from app.schemas.common import Message, Page
from app.schemas.datarequest import (
    DataRequestCreate,
    DataRequestCreated,
    DataRequestRead,
    InviteRead,
    InviteUploadResult,
)
from app.services import (
    activity,
    attachments,
    branding,
    datarequests,
    documents,
    images,
    mail,
    records,
)
from app.services.storage import (
    CATEGORY_DOCUMENTS,
    CATEGORY_PHOTOGRAPHS,
    CATEGORY_THUMBNAILS,
    storage,
)

router = APIRouter(prefix="/data-requests", tags=["Data requests"])

RESOURCE = ResourceType.PHOTOGRAPH

#: Names that promise a picture. Used only to choose which error to report when
#: a file will not decode — never to decide what a file *is*, which is always
#: settled by reading the bytes.
_PICTURE_NAMES = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".bmp", ".heic")


# --------------------------------------------------------------------------
# Naming the record, once
# --------------------------------------------------------------------------
def _label(session: DbSession, links: dict[str, uuid.UUID | None]) -> str:
    """What the recipient will be told they are sending files for.

    Resolved now and stored, rather than joined at read time: the recipient was
    told "the photographs of A-102", and that sentence should still make sense
    in the request list after somebody renumbers A-102.
    """
    # Imported here rather than at module scope: these four are the record
    # types a request can be about, and the endpoint module has no other use
    # for them.
    from app.models import Artifact, ExcavationContext, MuseumObject, Project, Site

    for key, model, fields in (
        ("museum_object_id", MuseumObject, ("accession_number", "title")),
        ("artifact_id", Artifact, ("inventory_number", "name")),
        ("context_id", ExcavationContext, ("context_number", "description")),
        ("site_id", Site, ("code", "name")),
        ("project_id", Project, ("code", "name")),
    ):
        identifier = links.get(key)
        if identifier is None:
            continue
        record = session.get(model, identifier)
        if record is None:
            continue
        parts = [str(getattr(record, name)) for name in fields if getattr(record, name, None)]
        return " — ".join(parts)[:300] or str(identifier)
    return "a record"


# --------------------------------------------------------------------------
# Asking
# --------------------------------------------------------------------------
@router.post(
    "",
    response_model=DataRequestCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Ask somebody for files",
    description=(
        "Creates an invitation and e-mails it. The recipient needs no account: "
        "the link lets them send files for this one record and does nothing "
        "else — it grants no read access, to this record or any other.\n\n"
        "**The link is shown once, in this response.** Only its hash is "
        "stored, the same way a password is, so the platform cannot show it "
        "again — it can only issue a new one. Copy it if you intend to pass it "
        "on by hand.\n\n"
        "If e-mail is not configured the request is still created and the link "
        "still works; the response says the invitation was not delivered."
    ),
    responses={
        422: {"description": "Attached to nothing, or to a record you cannot contribute to"}
    },
)
def create_request(
    payload: DataRequestCreate, session: DbSession, request: Request, user: CurrentUser
) -> DataRequestCreated:
    # The same check an upload makes: every id must exist, be visible, and be
    # somewhere this person may contribute. Asking a stranger for files for a
    # record you cannot touch yourself is not a hole worth leaving.
    links = attachments.resolve_attachment(
        session,
        user,
        project_id=payload.project_id,
        site_id=payload.site_id,
        artifact_id=payload.artifact_id,
        context_id=payload.context_id,
        museum_object_id=payload.museum_object_id,
    )

    token, digest = datarequests.new_token()
    record = DataRequest(
        record_label=_label(session, links),
        kind=payload.kind,
        message=payload.message,
        recipient_email=str(payload.recipient_email),
        recipient_name=payload.recipient_name,
        token_hash=digest,
        expires_at=datarequests.expiry(payload.expires_in_days),
        max_uploads=payload.max_uploads,
        requested_by_id=user.id,
        **links,
    )
    session.add(record)
    session.flush()
    # The e-mail names the requester, and a freshly flushed row has not loaded
    # the relationship yet.
    session.refresh(record)

    _deliver(session, record, token)

    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=record.id,
        resource_label=record.record_label,
        summary=(
            f"Asked {record.recipient_email} for the "
            f"{datarequests.asked_for(record.kind)} for {record.record_label}"
        ),
        request=request,
    )
    session.flush()

    return DataRequestCreated(
        **DataRequestRead.model_validate(record).model_dump(),
        invite_url=datarequests.invite_url(token),
    )


def _deliver(session: DbSession, record: DataRequest, token: str) -> None:
    """Send the invitation, and record honestly whether it went.

    Mail never raises here — see :func:`app.services.mail.send`. A request whose
    e-mail failed is still a usable request; what must not happen is the
    requester believing somebody was asked when nobody was.
    """
    organisation = branding.read(session).display_name
    subject, body, html = datarequests.compose(record, token, organisation=organisation)
    result = mail.send(
        record.recipient_email,
        subject,
        body,
        html=html,
        reply_to=record.requested_by.email if record.requested_by else None,
    )
    if result.ok:
        record.status = DataRequestStatus.SENT
        record.sent_at = datetime.now(UTC)
        record.delivery_note = None
    else:
        record.status = DataRequestStatus.OPEN
        record.delivery_note = result.detail
    session.flush()


@router.post(
    "/{request_id}/resend",
    response_model=DataRequestCreated,
    summary="Send a fresh invitation",
    description=(
        "Issues a **new** link and e-mails it, because the old one cannot be "
        "recovered — only its hash was kept. The old link stops working "
        "immediately, so this is also how you replace an invitation that went "
        "to the wrong address."
    ),
    responses={409: {"description": "This request is closed or withdrawn"}},
)
def resend_request(
    request_id: uuid.UUID, session: DbSession, request: Request, user: CurrentUser
) -> DataRequestCreated:
    record = _own(session, request_id, user)
    if record.status in (DataRequestStatus.CLOSED, DataRequestStatus.CANCELLED):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                "This request is finished. Make a new one rather than "
                "reopening it, so the record of what was asked and when stays "
                "straight."
            ),
        )

    token, digest = datarequests.new_token()
    record.token_hash = digest
    record.expires_at = datarequests.expiry(None)
    _deliver(session, record, token)

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=record.id,
        resource_label=record.record_label,
        summary=f"Sent {record.recipient_email} a fresh link for {record.record_label}",
        request=request,
    )
    session.flush()
    return DataRequestCreated(
        **DataRequestRead.model_validate(record).model_dump(),
        invite_url=datarequests.invite_url(token),
    )


# --------------------------------------------------------------------------
# Watching
# --------------------------------------------------------------------------
def _own(session: DbSession, request_id: uuid.UUID, user: CurrentUser) -> DataRequest:
    """A request this person is entitled to see.

    Yours, or — for an administrator — anybody's. A request names an outside
    e-mail address and a sentence somebody wrote to a colleague; it is not
    something the whole institution needs to read.
    """
    record = session.get(DataRequest, request_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such request")
    if record.requested_by_id != user.id and user.role is not UserRole.ADMIN:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such request")
    return record


@router.get(
    "",
    response_model=Page[DataRequestRead],
    summary="What has been asked for",
    description=(
        "Yours by default. An administrator may pass `mine=false` to see every "
        "request the institution has sent.\n\n"
        "`outstanding=true` is the question this screen exists to answer: what "
        "am I still waiting for."
    ),
)
def list_requests(
    session: DbSession,
    user: CurrentUser,
    mine: Annotated[bool, Query(description="Only requests you made")] = True,
    outstanding: Annotated[
        bool, Query(description="Only live requests that have had no files yet")
    ] = False,
    record_id: Annotated[
        uuid.UUID | None, Query(description="Requests about one record, whichever kind it is")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[DataRequestRead]:
    statement = select(DataRequest).order_by(DataRequest.created_at.desc())

    if mine or user.role is not UserRole.ADMIN:
        statement = statement.where(DataRequest.requested_by_id == user.id)
    if outstanding:
        statement = statement.where(
            DataRequest.status.in_([DataRequestStatus.OPEN, DataRequestStatus.SENT]),
            DataRequest.expires_at > datetime.now(UTC),
        )
    if record_id is not None:
        statement = statement.where(
            or_(
                DataRequest.project_id == record_id,
                DataRequest.site_id == record_id,
                DataRequest.artifact_id == record_id,
                DataRequest.context_id == record_id,
                DataRequest.museum_object_id == record_id,
            )
        )

    rows, total = records.paginate(session, statement, limit, offset)
    return Page[DataRequestRead](
        items=[DataRequestRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{request_id}", response_model=DataRequestRead, summary="Read one request")
def read_request(request_id: uuid.UUID, session: DbSession, user: CurrentUser) -> DataRequestRead:
    return DataRequestRead.model_validate(_own(session, request_id, user))


@router.delete(
    "/{request_id}",
    response_model=Message,
    summary="Withdraw a request",
    description=(
        "The link stops working immediately. The request itself is kept — that "
        "somebody was asked and the files never came is often the thing "
        "somebody needs to know later."
    ),
)
def cancel_request(
    request_id: uuid.UUID, session: DbSession, request: Request, user: CurrentUser
) -> Message:
    record = _own(session, request_id, user)
    record.status = DataRequestStatus.CANCELLED
    record.closed_at = datetime.now(UTC)
    # Not strictly needed — a cancelled request fails the status check — but a
    # withdrawn invitation should not leave a usable digest behind at all.
    record.token_hash = f"cancelled:{uuid.uuid4().hex}"[:64]
    session.flush()

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=record.id,
        resource_label=record.record_label,
        summary=f"Withdrew the request to {record.recipient_email}",
        request=request,
    )
    session.flush()
    return Message(detail="Withdrawn. The link no longer works.")


# ==========================================================================
# In front of the sign-in: the invitation itself
# ==========================================================================
invites = APIRouter(prefix="/send", tags=["Data requests"])


def _resolve(session: DbSession, token: str) -> DataRequest:
    try:
        return datarequests.resolve(session, token)
    except datarequests.InviteProblem as problem:
        # 404 rather than 403: a probe learns only that this URL is not a
        # working invitation, which is what it would learn from any other
        # address on the platform.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(problem)) from problem


@router.get(
    "/invite/{token}",
    response_model=InviteRead,
    summary="What this link is asking for",
    description=(
        "No sign-in. Names the record so the sender knows they are sending the "
        "right files to the right thing, and says nothing else about it — not "
        "its location, not its description, not who else was asked.\n\n"
        "An invitation that has expired, been withdrawn or been filled reads "
        "as 'not valid' without saying which, so probing for live links "
        "learns nothing."
    ),
    responses={404: {"description": "Not a working invitation"}},
)
def read_invite(token: str, session: DbSession) -> InviteRead:
    record = _resolve(session, token)
    thing = datarequests.asked_for(record.kind)
    limit = settings.MAX_UPLOAD_SIZE_MB
    return InviteRead(
        record_label=record.record_label,
        kind=record.kind,
        asked_for=thing,
        message=record.message,
        requested_by=record.requested_by.full_name if record.requested_by else None,
        organisation=branding.read(session).display_name,
        expires_at=record.expires_at,
        uploads_left=record.uploads_left,
        accepted_note=(
            f"Pictures and documents up to {limit} MB each. "
            f"{record.uploads_left} file{'' if record.uploads_left == 1 else 's'} left on this "
            f"link. Nothing else about the archive is reachable from here."
        ),
    )


@router.post(
    "/invite/{token}",
    response_model=InviteUploadResult,
    status_code=status.HTTP_201_CREATED,
    summary="Send one file",
    description=(
        "No sign-in. The file attaches itself to the record the request names — "
        "which is fixed, and cannot be redirected by anything sent with the "
        "file.\n\n"
        "An image is validated by decoding it and filed as a photograph; "
        "anything else is magic-byte checked and filed as a document. A file "
        "arriving by invitation gets exactly the checks an uploaded one gets."
    ),
    responses={
        404: {"description": "Not a working invitation"},
        413: {"description": "Larger than the configured limit"},
        422: {"description": "Not a file this platform can store"},
    },
)
async def upload_to_invite(
    token: str,
    session: DbSession,
    request: Request,
    file: Annotated[UploadFile, File(description="One picture or document")],
    note: Annotated[str | None, Form(max_length=1000)] = None,
) -> InviteUploadResult:
    record = _resolve(session, token)
    links = record.parent_ids
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    try:
        data = images.read_upload(file.file, max_bytes=max_bytes)
    except images.ImageError as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc

    filename = file.filename or "sent file"
    title = f"{filename} — sent by {record.recipient_name or record.recipient_email}"

    stored_record: Any
    try:
        facts = images.inspect(data)
    except images.ImageError as picture_problem:
        # A file named like a picture that will not decode is a damaged
        # picture, not a document of an unsupported type. Saying ".png files
        # are not accepted" to somebody sending a .png would send them away to
        # convert a file that was never the problem.
        if filename.lower().endswith(_PICTURE_NAMES):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"{filename!r} looks like a picture but could not be read: "
                    f"{picture_problem}. It may have been damaged in transit — "
                    f"try sending it again, or export it afresh."
                ),
            ) from picture_problem
        stored_record = _store_document(session, record, data, filename, note, links)
    else:
        stored_record = _store_photograph(session, record, data, facts, filename, note, links)

    datarequests.record_upload(session, record)

    # Logged against the requester, not against nobody: the archive should be
    # able to say who asked for a file that arrived without a signed-in user
    # behind it.
    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=record.requested_by,
        resource_type=RESOURCE,
        resource_id=stored_record.id,
        resource_label=title,
        summary=(
            f"{record.recipient_email} sent {filename!r} for {record.record_label} "
            f"on an invitation"
        ),
        request=request,
    )
    session.flush()

    return InviteUploadResult(
        filename=filename,
        size_bytes=len(data),
        uploads_left=record.uploads_left,
        thanks=(
            f"Thank you — {filename!r} has been filed against {record.record_label}."
            + (
                f" You can send {record.uploads_left} more on this link."
                if record.uploads_left
                else " That was the last file this link accepts."
            )
        ),
    )


def _store_photograph(
    session: DbSession,
    record: DataRequest,
    data: bytes,
    facts: images.ImageFacts,
    filename: str,
    note: str | None,
    links: dict[str, uuid.UUID | None],
) -> Photograph:
    stored = storage.save_bytes(data, category=CATEGORY_PHOTOGRAPHS, extension=facts.extension)

    thumbnails: dict[str, str] = {}
    for size in images.thumbnail_sizes():
        try:
            rendered = images.make_thumbnail(data, size)
        except Exception:  # pragma: no cover - depends on the decoder
            continue
        thumbnails[str(size)] = storage.save_bytes(
            rendered, category=f"{CATEGORY_THUMBNAILS}/{size}", extension=".jpg"
        ).path

    photo = Photograph(
        title=filename,
        description=note,
        photographer=record.recipient_name or record.recipient_email,
        taken_at=facts.taken_at,
        camera_make=facts.camera_make,
        camera_model=facts.camera_model,
        lens=facts.lens,
        file_path=stored.path,
        original_filename=filename,
        mime_type=facts.mime_type,
        file_size=stored.size,
        checksum=stored.checksum,
        width=facts.width,
        height=facts.height,
        thumbnails=thumbnails or None,
        exif=facts.exif or None,
        latitude=facts.latitude,
        longitude=facts.longitude,
        altitude=facts.altitude,
        direction=facts.direction,
        # Owned by whoever asked for it. A record with no owner is a record no
        # permission check can reason about.
        owner_id=record.requested_by_id,
        # Always pending. Nobody inside the institution has looked at this yet,
        # and a file that arrived from outside is exactly what review is for.
        review_status=ReviewStatus.PENDING,
        **links,
    )
    session.add(photo)
    session.flush()
    return photo


def _store_document(
    session: DbSession,
    record: DataRequest,
    data: bytes,
    filename: str,
    note: str | None,
    links: dict[str, uuid.UUID | None],
) -> Document:
    try:
        facts = documents.inspect(data, filename)
    except documents.DocumentError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    stored = storage.save_bytes(data, category=CATEGORY_DOCUMENTS, extension=facts.extension)
    document = Document(
        title=filename,
        description=note,
        document_type=documents.guess_type(facts.extension, filename),
        file_path=stored.path,
        original_filename=filename,
        mime_type=facts.mime_type,
        file_size=stored.size,
        checksum=stored.checksum,
        owner_id=record.requested_by_id,
        review_status=ReviewStatus.PENDING,
        **links,
    )
    session.add(document)
    session.flush()
    return document
