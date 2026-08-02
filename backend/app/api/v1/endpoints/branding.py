"""The institution's name and mark, and each person's photograph.

Two things that look unrelated and are the same thing: whose installation this
is, and who is using it. Both are read on every page, both are set by somebody
who is not a developer, and both are images that have to be uploaded, decoded
and served safely.

**Branding is public.** The sign-in page has nobody signed in and still has to
draw the mark, so reading it needs no account. Setting it needs an
administrator: the name at the top of every page is not a personal preference.

**An avatar belongs to its owner.** Anybody may set their own; an administrator
may set anybody's, because the person who cannot work out how to upload a
photograph is exactly the person who asks the administrator to do it.

Uploaded images are decoded before they are stored, and the media type comes
from the decode rather than from what the uploader called the file. An SVG named
``logo.png`` that the browser then runs as script is the ordinary way a logo
upload becomes a cross-site scripting hole.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession, RequireAdmin
from app.models.enums import UserRole
from app.models.user import User
from app.services import attachments, branding, images, records
from app.services.storage import storage

router = APIRouter(tags=["Branding & avatars"])

#: Its own category in the file store, so a bucket policy can treat the logo —
#: which is public — differently from photographs, which are not.
CATEGORY_BRANDING = "branding"
CATEGORY_AVATARS = "avatars"

#: Bigger than this and it is a photograph somebody has not resized, not a logo.
_LOGO_MAX_MB = 8
_AVATAR_MAX_MB = 8

#: What the browser will draw without being told to run anything. Deliberately
#: no SVG: an SVG is a document that can carry script, and serving one inline
#: from this origin hands it the session.
_DRAWABLE = {"image/png", "image/jpeg", "image/webp", "image/gif"}


class BrandingRead(BaseModel):
    """What every page needs to render the institution's identity."""

    organisation_name: str | None = None
    tagline: str | None = None
    footer_note: str | None = None
    #: Null when nothing has been uploaded, in which case the platform draws
    #: its own mark.
    logo_url: str | None = None
    #: What the sidebar prints: the organisation's name, or "Stratum".
    display_name: str


class BrandingUpdate(BaseModel):
    """Only the fields sent are changed; an empty string clears one."""

    organisation_name: str | None = Field(default=None, max_length=120)
    tagline: str | None = Field(default=None, max_length=160)
    footer_note: str | None = Field(default=None, max_length=2000)


def _payload(session: DbSession) -> BrandingRead:
    current = branding.read(session)
    return BrandingRead(
        organisation_name=current.organisation_name,
        tagline=current.tagline,
        footer_note=current.footer_note,
        logo_url=current.logo_url,
        display_name=current.display_name,
    )


def _decode(file: UploadFile, *, max_mb: int, what: str) -> tuple[bytes, images.ImageFacts]:
    """Read and decode an upload, or say plainly why it will not do.

    Decoding is the check. A file's name and the media type the browser
    attaches are both supplied by whoever is uploading, and neither is evidence
    of anything.
    """
    try:
        data = images.read_upload(file.file, max_bytes=max_mb * 1024 * 1024)
    except images.ImageError as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc

    try:
        facts = images.inspect(data)
    except images.ImageError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"That file could not be read as an image, so it cannot be used as {what}.",
        ) from exc

    if facts.mime_type not in _DRAWABLE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"A {facts.mime_type} cannot be used as {what}. " f"Use a PNG, JPEG, WebP or GIF."
            ),
        )
    return data, facts


# --------------------------------------------------------------------------
# The institution
# --------------------------------------------------------------------------
@router.get(
    "/branding",
    response_model=BrandingRead,
    summary="The institution's name and mark",
    description=(
        "Readable without an account: the sign-in page has nobody signed in "
        "and still has to draw the mark."
    ),
)
def read_branding(session: DbSession) -> BrandingRead:
    return _payload(session)


@router.put(
    "/branding",
    response_model=BrandingRead,
    summary="Set the institution's name",
    description="Administrators only. The name at the top of every page is not a preference.",
)
def update_branding(
    payload: BrandingUpdate, session: DbSession, user: RequireAdmin
) -> BrandingRead:
    sent = payload.model_dump(exclude_unset=True)
    for field, key in (
        ("organisation_name", branding.ORGANISATION),
        ("tagline", branding.TAGLINE),
        ("footer_note", branding.FOOTER_NOTE),
    ):
        if field in sent:
            branding.put(session, key, sent[field])
    session.commit()
    return _payload(session)


@router.post(
    "/branding/logo",
    response_model=BrandingRead,
    summary="Upload the institution's logo",
    description=(
        "The image is decoded before it is stored, and its media type comes "
        "from that decode rather than from what the file was called.\n\n"
        "Roughly 240 pixels on the long edge is plenty — it is drawn about "
        "28 pixels high in the sidebar."
    ),
)
def upload_logo(
    session: DbSession,
    user: RequireAdmin,
    file: Annotated[UploadFile, File(description="PNG, JPEG, WebP or GIF")],
) -> BrandingRead:
    data, facts = _decode(file, max_mb=_LOGO_MAX_MB, what="a logo")
    stored = storage.save_bytes(data, category=CATEGORY_BRANDING, extension=facts.extension)

    branding.put(session, branding.LOGO_PATH, stored.path)
    branding.put(session, branding.LOGO_MIME, facts.mime_type)
    branding.put(session, branding.LOGO_CHECKSUM, stored.checksum)
    session.commit()
    return _payload(session)


@router.delete(
    "/branding/logo",
    response_model=BrandingRead,
    summary="Remove the institution's logo",
    description="The platform's own mark is drawn again.",
)
def delete_logo(session: DbSession, user: RequireAdmin) -> BrandingRead:
    branding.clear_logo(session)
    session.commit()
    return _payload(session)


@router.get(
    "/branding/logo",
    summary="The institution's logo",
    description=(
        "Public, like the mark on a letterhead. `v` is the file's checksum: it "
        "changes when the logo does, which is what stops half the staff seeing "
        "last month's logo out of their cache."
    ),
    response_class=FileResponse,
    responses={
        200: {"content": {"image/*": {}}, "description": "The logo"},
        404: {"description": "No logo has been uploaded"},
    },
)
def read_logo(session: DbSession) -> Response:
    location = branding.logo_location(session)
    if location is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No logo has been uploaded")
    path, media_type = location

    response = attachments.serve(path, filename="logo", media_type=media_type, inline=True)
    # A year, because the URL carries the checksum. Without the checksum this
    # would be the bug it is guarding against.
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


# --------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------
class AvatarRead(BaseModel):
    user_id: uuid.UUID
    avatar_url: str | None = None


def _avatar_payload(person: User) -> AvatarRead:
    return AvatarRead(
        user_id=person.id,
        avatar_url=f"/api/v1/users/{person.id}/avatar" if person.avatar_path else None,
    )


def _target(session: DbSession, user: User, user_id: uuid.UUID | None) -> User:
    """Whose avatar this call is about, refusing to set somebody else's.

    An administrator may set anybody's, because the person who cannot work out
    how to upload a photograph is the person who asks them to.
    """
    if user_id is None or user_id == user.id:
        return user
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="You may only change your own photograph"
        )
    return records.get_or_404(session, User, user_id, "User")


@router.post(
    "/users/me/avatar",
    response_model=AvatarRead,
    summary="Upload your photograph",
    description=(
        "Shown beside your name in the sidebar, on tasks assigned to you and "
        "against records you created.\n\n"
        "`user_id` sets somebody else's, which only an administrator may do."
    ),
)
def upload_avatar(
    session: DbSession,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="PNG, JPEG, WebP or GIF")],
    user_id: Annotated[uuid.UUID | None, Form()] = None,
) -> AvatarRead:
    person = _target(session, user, user_id)
    data, facts = _decode(file, max_mb=_AVATAR_MAX_MB, what="a photograph")

    # Stored small rather than at whatever size the camera produced: it is
    # drawn at 28 pixels, and a four-megabyte portrait fetched on every page
    # load is a real cost for no visible gain. If the resize fails the original
    # is still worth keeping — a large avatar beats no avatar.
    try:
        stored = storage.save_bytes(
            images.make_thumbnail(data, 256), category=CATEGORY_AVATARS, extension=".jpg"
        )
    except Exception:  # pragma: no cover - depends on the decoder
        stored = storage.save_bytes(data, category=CATEGORY_AVATARS, extension=facts.extension)

    person.avatar_path = stored.path
    session.commit()
    session.refresh(person)
    return _avatar_payload(person)


@router.delete(
    "/users/me/avatar",
    response_model=AvatarRead,
    summary="Remove your photograph",
)
def delete_avatar(
    session: DbSession,
    user: CurrentUser,
    user_id: uuid.UUID | None = None,
) -> AvatarRead:
    person = _target(session, user, user_id)
    person.avatar_path = None
    session.commit()
    return _avatar_payload(person)


@router.get(
    "/users/{user_id}/avatar",
    summary="Somebody's photograph",
    description=(
        "Visible to anyone with an account. A staff photograph is directory "
        "information within the institution, and hiding it would mean every "
        "list of people showed initials instead."
    ),
    response_class=FileResponse,
    responses={
        200: {"content": {"image/*": {}}, "description": "The photograph"},
        404: {"description": "No photograph has been uploaded"},
    },
)
def read_avatar(user_id: uuid.UUID, session: DbSession, user: CurrentUser) -> Response:
    person = records.get_or_404(session, User, user_id, "User")
    if not person.avatar_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No photograph has been uploaded")

    response = attachments.serve(
        person.avatar_path, filename="avatar", media_type="image/jpeg", inline=True
    )
    # Content-addressed, so the bytes at this path never change; but the path a
    # *person* points at does, so this is short.
    response.headers["Cache-Control"] = "private, max-age=300"
    return response
