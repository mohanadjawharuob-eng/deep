"""Sending files to somebody who does not have an account.

The commonest request an institution gets is *send me the photographs of the
jar and the finds register*, and the person asking is a ministry officer, a
visiting specialist, a journalist. They will not be given an account and should
not need one.

So: pick the files, and the platform writes them to the assigned disk under
names a person can read — ``Sites / TED-A North trench / Photographs / Trench A
from the north.jpg`` — zips the folder, and mails the recipient a link with a
token in it. The link expires; nothing else in the archive is reachable through
it.

**On "sent to their desktop".** No web platform can put a folder on somebody
else's computer, and a design that appears to is lying about where the file
went. What this does is put the folder on the disk the institution assigned and
tell the person where to get it. On the machine the platform runs on, that
folder *is* local — which is the part that was actually wanted.

The bundle is a second copy, made for sending. Deleting a delivery deletes the
bundle and nothing else.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.api.deps import DbSession, require_capability
from app.core.config import settings
from app.core.permissions import Capability
from app.models.delivery import Delivery
from app.models.enums import ActivityAction, DeliveryStatus
from app.models.user import User
from app.schemas.common import Message, ORMModel, Page
from app.services import activity, branding, handover, mail, records
from app.services.storage import CATEGORY_DELIVERIES, storage

router = APIRouter(prefix="/deliveries", tags=["Deliveries"])

#: Sending files out of the institution is an export, and the platform already
#: has a word for who may do that.
Sender = Annotated[User, Depends(require_capability(Capability.EXPORT_DATA))]

#: How long a link lasts unless somebody says otherwise. Long enough that a
#: recipient who reads mail weekly still gets it; short enough that a link
#: forwarded onward in a year does not still work.
DEFAULT_DAYS = 30


class DeliveryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200, description="What this bundle is")
    to_name: str = Field(min_length=1, max_length=200)
    to_email: EmailStr
    note: str | None = Field(default=None, description="Shown to the recipient")
    photograph_ids: list[uuid.UUID] = Field(default_factory=list)
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    sheet_ids: list[uuid.UUID] = Field(default_factory=list)
    expires_in_days: int = Field(default=DEFAULT_DAYS, ge=1, le=365)


class DeliveryRead(ORMModel):
    id: uuid.UUID
    title: str
    note: str | None = None
    to_name: str
    to_email: str
    status: DeliveryStatus
    file_count: int
    size_bytes: int
    missing: list[str] | None = None
    expires_at: datetime | None = None
    collected_at: datetime | None = None
    collected_count: int
    notified: bool
    created_at: datetime
    #: Where the folder sits on the assigned disk, as an absolute path — this
    #: is the whole point for somebody standing at the machine, and it is shown
    #: to people inside the institution only.
    folder_on_disk: str | None = None
    owner_label: str | None = None
    #: Returned once, when the delivery is made, so the sender can pass the
    #: link on by hand where mail is not configured. Never in a listing.
    collect_url: str | None = None


class CollectionRead(BaseModel):
    """What the recipient sees, with nothing about the institution's insides."""

    title: str
    note: str | None = None
    from_organisation: str
    file_count: int
    size_bytes: int
    expires_at: datetime | None = None


def collect_url(token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/collect/{token}"


def _read(session: DbSession, record: Delivery, *, inside: bool) -> DeliveryRead:
    payload = DeliveryRead.model_validate(record)
    if inside and record.folder_path:
        try:
            payload.folder_on_disk = str(storage.absolute_path(record.folder_path).parent)
        except Exception:
            payload.folder_on_disk = None
    owner = session.get(User, record.owner_id)
    payload.owner_label = (owner.full_name or owner.username) if owner else None
    return payload


def _expired(record: Delivery) -> bool:
    if record.expires_at is None:
        return False
    cutoff = record.expires_at
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=UTC)
    return cutoff < datetime.now(UTC)


@router.post(
    "",
    response_model=DeliveryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Prepare files for somebody to collect",
    description=(
        "Writes the chosen files to the assigned disk under readable folder "
        "names, zips them, and mails the recipient a link.\\n\\n"
        "The reply carries the link once, so it can be passed on by hand when "
        "mail is not configured on the server — which is a supported way to "
        "run this and must not look like a failure."
    ),
    responses={422: {"description": "Nothing was chosen"}},
)
def create_delivery(
    payload: DeliveryCreate, session: DbSession, request: Request, user: Sender
) -> DeliveryRead:
    items = [
        *handover.items_for_photographs(session, payload.photograph_ids),
        *handover.items_for_documents(session, payload.document_ids),
        *handover.items_for_sheets(session, payload.sheet_ids),
    ]
    if not items:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Nothing was chosen, or nothing chosen still exists. Pick at "
                "least one photograph, document or sheet."
            ),
        )

    token = secrets.token_urlsafe(32)[:64]
    slug = handover.readable(payload.title, "Delivery")
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    # Named for a person rather than content-addressed: the point of this
    # folder is that somebody who is not the platform can find it on the disk.
    relative = f"{CATEGORY_DELIVERIES}/{stamp} {slug}"
    root = storage.root / relative

    record = Delivery(
        title=payload.title.strip(),
        note=payload.note,
        to_name=payload.to_name.strip(),
        to_email=str(payload.to_email),
        status=DeliveryStatus.PREPARING,
        photograph_ids=[str(value) for value in payload.photograph_ids],
        document_ids=[str(value) for value in payload.document_ids],
        sheet_ids=[str(value) for value in payload.sheet_ids],
        token=token,
        expires_at=datetime.now(UTC) + timedelta(days=payload.expires_in_days),
        owner_id=user.id,
    )
    session.add(record)
    session.flush()

    written = handover.write(items, root)
    (root / "About this folder.txt").write_text(
        handover.readme(payload.title, payload.note, written), encoding="utf-8"
    )
    zip_relative = f"{relative}.zip"
    size = handover.zip_up(root, storage.root / zip_relative)

    record.folder_path = f"{relative}/About this folder.txt"
    record.zip_path = zip_relative
    record.file_count = written.files
    record.size_bytes = size
    record.missing = written.missing or None
    record.status = DeliveryStatus.READY

    organisation = branding.read(session).display_name
    sent = mail.send(
        record.to_email,
        subject=f"{organisation}: {record.title}",
        body="\n".join(
            [
                f"Dear {record.to_name},",
                "",
                f"{user.full_name or user.username} at {organisation} has prepared",
                f"{written.files} file(s) for you to download:",
                "",
                f"    {record.title}",
                *(["", record.note] if record.note else []),
                "",
                "You can collect them here — no account is needed:",
                f"    {collect_url(token)}",
                "",
                (
                    f"The link stops working on " f"{record.expires_at:%d %B %Y}."
                    if record.expires_at
                    else ""
                ),
            ]
        ),
        reply_to=user.email,
    )
    record.notified = sent.ok

    activity.log(
        session,
        action=ActivityAction.EXPORT,
        user=user,
        resource_label=record.title,
        summary=(f"Prepared {written.files} file(s) for {record.to_name} <{record.to_email}>"),
        request=request,
    )
    session.flush()

    payload_out = _read(session, record, inside=True)
    payload_out.collect_url = collect_url(token)
    return payload_out


@router.get("", response_model=Page[DeliveryRead], summary="What has been sent out")
def list_deliveries(
    session: DbSession,
    user: Sender,
    mine: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[DeliveryRead]:
    statement = select(Delivery).order_by(Delivery.created_at.desc())
    if mine:
        statement = statement.where(Delivery.owner_id == user.id)
    rows, total = records.paginate(session, statement, limit, offset)
    return Page[DeliveryRead](
        items=[_read(session, row, inside=True) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{delivery_id}", response_model=DeliveryRead, summary="One delivery")
def read_delivery(delivery_id: uuid.UUID, session: DbSession, user: Sender) -> DeliveryRead:
    record = records.get_or_404(session, Delivery, delivery_id, "Delivery")
    return _read(session, record, inside=True)


@router.delete(
    "/{delivery_id}",
    response_model=Message,
    summary="Delete a bundle",
    description=(
        "Removes the zip and the folder from the disk. The archive's own copy "
        "of every file is untouched — a bundle is a second copy made for "
        "sending.\\n\\n"
        "The record of what was sent to whom is kept, because a rights query "
        "or a ministry asking what it was given arrives years later."
    ),
)
def delete_delivery(
    delivery_id: uuid.UUID, session: DbSession, request: Request, user: Sender
) -> Message:
    import shutil

    record = records.get_or_404(session, Delivery, delivery_id, "Delivery")
    if record.zip_path:
        (storage.root / record.zip_path).unlink(missing_ok=True)
    if record.folder_path:
        shutil.rmtree(storage.root / record.folder_path.rsplit("/", 1)[0], ignore_errors=True)

    record.status = DeliveryStatus.EXPIRED
    record.zip_path = None
    record.folder_path = None
    record.expires_at = datetime.now(UTC)

    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=user,
        resource_label=record.title,
        summary=f"Deleted the bundle prepared for {record.to_name}",
        request=request,
    )
    session.flush()
    return Message(
        detail=(
            f"The bundle is gone from the disk. What was sent to {record.to_name} "
            "is still on the record, and every file is still in the archive."
        )
    )


# --------------------------------------------------------------------------
# The recipient's door
#
# No authentication. The token in the path is the whole credential, so
# everything below is careful to give away nothing about the archive beyond
# the bundle itself.
# --------------------------------------------------------------------------
def _by_token(session: DbSession, token: str) -> Delivery:
    record = session.scalar(select(Delivery).where(Delivery.token == token))
    # One message for "no such link" and "expired link": telling an anonymous
    # caller which of the two it is turns this into a way to test tokens.
    if record is None or _expired(record) or record.zip_path is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=(
                "This link is not valid any more. Links expire, and a bundle "
                "can be removed once it has been collected — ask whoever sent "
                "it for a new one."
            ),
        )
    return record


@router.get(
    "/collect/{token}",
    response_model=CollectionRead,
    summary="What is waiting, for the person collecting it",
)
def read_collection(token: str, session: DbSession) -> CollectionRead:
    record = _by_token(session, token)
    return CollectionRead(
        title=record.title,
        note=record.note,
        from_organisation=branding.read(session).display_name,
        file_count=record.file_count,
        size_bytes=record.size_bytes,
        expires_at=record.expires_at,
    )


@router.get(
    "/collect/{token}/download",
    summary="Download the bundle",
    response_class=FileResponse,
)
def download_collection(token: str, session: DbSession) -> FileResponse:
    record = _by_token(session, token)
    record.collected_count += 1
    record.collected_at = datetime.now(UTC)
    record.status = DeliveryStatus.COLLECTED
    session.flush()
    return FileResponse(
        storage.root / record.zip_path,
        filename=f"{handover.readable(record.title, 'files')}.zip",
        media_type="application/zip",
    )
