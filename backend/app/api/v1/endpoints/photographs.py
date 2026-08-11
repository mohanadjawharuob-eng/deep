"""Photograph upload, retrieval and thumbnails."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, CurrentUserOptional, DbSession
from app.core.config import settings
from app.core.permissions import can_delete, can_edit, visibility_filter
from app.models.enums import ResourceType, ReviewStatus
from app.models.media import Photograph
from app.models.user import User
from app.schemas.common import Message, Page
from app.schemas.media import PhotographDetail, PhotographSummary, PhotographUpdate
from app.services import attachments, images, records
from app.services.storage import CATEGORY_PHOTOGRAPHS, CATEGORY_THUMBNAILS, extension_of, storage

router = APIRouter(prefix="/photographs", tags=["Photographs"])

RESOURCE = ResourceType.PHOTOGRAPH


def _summary(photo: Photograph) -> PhotographSummary:
    payload = PhotographSummary.model_validate(photo)
    payload.thumbnail_sizes = sorted(int(size) for size in (photo.thumbnails or {}))
    return payload


def _detail(session: DbSession, photo: Photograph, user: User | None) -> PhotographDetail:
    payload = PhotographDetail.model_validate(photo)
    payload.thumbnail_sizes = sorted(int(size) for size in (photo.thumbnails or {}))
    payload.can_edit = can_edit(session, user, photo, RESOURCE)
    payload.can_delete = can_delete(session, user, photo, RESOURCE)
    return payload


@router.post(
    "",
    response_model=PhotographDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a photograph",
    description=(
        "Multipart upload. The image is validated by decoding it — the declared "
        "content type and the file extension are both ignored, since a client "
        "controls each.\n\n"
        "EXIF is read on upload: camera, lens, capture time and, when the "
        "camera recorded them, GPS coordinates. Anything given as a form field "
        "overrides what EXIF said.\n\n"
        "Thumbnails are generated at the configured sizes, oriented correctly "
        "and stripped of metadata."
    ),
    responses={
        413: {"description": "The file is larger than the configured limit"},
        422: {"description": "Not a usable image, or attached to nothing"},
    },
)
async def upload_photograph(
    session: DbSession,
    request: Request,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="The image file")],
    title: Annotated[str | None, Form(max_length=300)] = None,
    description: Annotated[str | None, Form()] = None,
    photographer: Annotated[str | None, Form(max_length=200)] = None,
    shot_type: Annotated[
        str | None, Form(description="overview, detail, working shot, section…")
    ] = None,
    has_scale: Annotated[bool | None, Form(description="Is a scale bar visible?")] = None,
    tags: Annotated[str | None, Form(description="Comma-separated")] = None,
    latitude: Annotated[float | None, Form(ge=-90, le=90)] = None,
    longitude: Annotated[float | None, Form(ge=-180, le=180)] = None,
    location_text: Annotated[str | None, Form(max_length=300)] = None,
    is_cover: Annotated[bool, Form()] = False,
    is_public: Annotated[bool, Form()] = False,
    project_id: Annotated[uuid.UUID | None, Form()] = None,
    site_id: Annotated[uuid.UUID | None, Form()] = None,
    artifact_id: Annotated[uuid.UUID | None, Form()] = None,
    context_id: Annotated[uuid.UUID | None, Form()] = None,
    museum_object_id: Annotated[uuid.UUID | None, Form()] = None,
) -> PhotographDetail:
    links = attachments.resolve_attachment(
        session,
        user,
        project_id=project_id,
        site_id=site_id,
        artifact_id=artifact_id,
        context_id=context_id,
        museum_object_id=museum_object_id,
    )

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    try:
        data = images.read_upload(file.file, max_bytes=max_bytes)
    except images.ImageError as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc

    try:
        facts = images.inspect(data)
    except images.ImageError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    stored = storage.save_bytes(data, category=CATEGORY_PHOTOGRAPHS, extension=facts.extension)

    # Thumbnails are best-effort: a photograph that resists resizing is still
    # worth keeping, and the gallery can fall back to the original.
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
        title=title or (file.filename or "Untitled photograph"),
        description=description,
        photographer=photographer or user.full_name,
        photographer_id=user.id,
        taken_at=facts.taken_at,
        camera_make=facts.camera_make,
        camera_model=facts.camera_model,
        lens=facts.lens,
        file_path=stored.path,
        original_filename=file.filename,
        mime_type=facts.mime_type,
        file_size=stored.size,
        checksum=stored.checksum,
        width=facts.width,
        height=facts.height,
        thumbnails=thumbnails or None,
        exif=facts.exif or None,
        # A coordinate typed into the form wins over the camera's, which is
        # often absent and sometimes wrong.
        latitude=latitude if latitude is not None else facts.latitude,
        longitude=longitude if longitude is not None else facts.longitude,
        altitude=facts.altitude,
        direction=facts.direction,
        location_text=location_text,
        shot_type=shot_type,
        has_scale=has_scale,
        is_cover=is_cover,
        tags=[tag.strip() for tag in tags.split(",") if tag.strip()] if tags else None,
        is_public=is_public,
        owner_id=user.id,
        review_status=records.initial_review_status(user),
        **links,
    )
    session.add(photo)
    session.flush()

    if is_cover:
        _clear_other_covers(session, photo)

    attachments.log_upload(
        session,
        record=photo,
        resource_type=RESOURCE,
        user=user,
        request=request,
        summary=f"Uploaded {photo.title!r}"
        + (" (duplicate of an existing file)" if stored.deduplicated else ""),
    )
    session.flush()
    return _detail(session, photo, user)


def _clear_other_covers(session: DbSession, photo: Photograph) -> None:
    """Only one cover per parent record."""
    for column, value in (
        (Photograph.artifact_id, photo.artifact_id),
        (Photograph.site_id, photo.site_id),
        (Photograph.project_id, photo.project_id),
    ):
        if value is None:
            continue
        others = session.scalars(
            select(Photograph).where(
                column == value, Photograph.is_cover.is_(True), Photograph.id != photo.id
            )
        ).all()
        for other in others:
            other.is_cover = False
            session.add(other)
        # The most specific link wins: a photograph of an artifact is that
        # artifact's cover, not the whole project's.
        break


@router.get("", response_model=Page[PhotographSummary], summary="List photographs")
def list_photographs(
    session: DbSession,
    user: CurrentUserOptional,
    q: Annotated[str | None, Query(description="Match title, description or tags")] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    site_id: Annotated[uuid.UUID | None, Query()] = None,
    artifact_id: Annotated[uuid.UUID | None, Query()] = None,
    context_id: Annotated[uuid.UUID | None, Query()] = None,
    museum_object_id: Annotated[uuid.UUID | None, Query()] = None,
    folder_id: Annotated[
        str | None, Query(description="A folder's id, or `none` for what is unfiled")
    ] = None,
    shot_type: Annotated[str | None, Query()] = None,
    photographer: Annotated[str | None, Query()] = None,
    covers_only: Annotated[bool, Query(description="Only representative images")] = False,
    review_status: Annotated[ReviewStatus | None, Query()] = None,
    sort: Annotated[str, Query(pattern="^-?(created_at|taken_at|title)$")] = "-created_at",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[PhotographSummary]:
    statement = select(Photograph).where(visibility_filter(user, Photograph, RESOURCE))

    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Photograph.title).like(pattern),
                func.lower(Photograph.description).like(pattern),
                func.lower(func.array_to_string(Photograph.tags, " ")).like(pattern),
            )
        )
    if project_id is not None:
        statement = statement.where(Photograph.project_id == project_id)
    if site_id is not None:
        statement = statement.where(Photograph.site_id == site_id)
    if artifact_id is not None:
        statement = statement.where(Photograph.artifact_id == artifact_id)
    if context_id is not None:
        statement = statement.where(Photograph.context_id == context_id)
    if museum_object_id is not None:
        statement = statement.where(Photograph.museum_object_id == museum_object_id)
    if folder_id == "none":
        statement = statement.where(Photograph.folder_id.is_(None))
    elif folder_id:
        statement = statement.where(Photograph.folder_id == uuid.UUID(folder_id))
    if shot_type:
        statement = statement.where(func.lower(Photograph.shot_type) == shot_type.lower())
    if photographer:
        statement = statement.where(
            func.lower(Photograph.photographer).like(f"%{photographer.lower()}%")
        )
    if covers_only:
        statement = statement.where(Photograph.is_cover.is_(True))
    if review_status is not None:
        statement = statement.where(Photograph.review_status == review_status)

    descending = sort.startswith("-")
    column = getattr(Photograph, sort.lstrip("-"))
    statement = statement.order_by(column.desc() if descending else column.asc())

    rows, total = records.paginate(session, statement, limit, offset)
    return Page[PhotographSummary](
        items=[_summary(row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.get("/{photograph_id}", response_model=PhotographDetail, summary="Read a photograph")
def read_photograph(
    photograph_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> PhotographDetail:
    photo = records.get_or_404(session, Photograph, photograph_id, "Photograph")
    attachments.require_readable(session, user, photo, RESOURCE, "Photograph")
    return _detail(session, photo, user)


@router.get(
    "/{photograph_id}/file",
    summary="Download the original image",
    description="The image exactly as uploaded, EXIF and all.",
    response_class=FileResponse,
    responses={200: {"content": {"image/*": {}}, "description": "The stored image"}},
)
def download_photograph(
    photograph_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> FileResponse:
    photo = records.get_or_404(session, Photograph, photograph_id, "Photograph")
    attachments.require_readable(session, user, photo, RESOURCE, "Photograph")
    return attachments.serve(
        photo.file_path,
        filename=photo.original_filename or f"{photo.title}{extension_of(photo.file_path)}",
        media_type=photo.mime_type,
        # Safe inline: the type was decided by decoding the image on upload,
        # not by trusting what the uploader called it.
        inline=True,
    )


@router.get(
    "/{photograph_id}/thumbnail",
    summary="Fetch a thumbnail",
    description=(
        "Returns the smallest generated thumbnail at least as large as `size`, "
        "or the largest available if none is big enough. Thumbnails carry no "
        "metadata, so they cannot leak the position of a restricted site."
    ),
    response_class=FileResponse,
    responses={200: {"content": {"image/jpeg": {}}, "description": "The thumbnail"}},
)
def download_thumbnail(
    photograph_id: uuid.UUID,
    session: DbSession,
    user: CurrentUserOptional,
    size: Annotated[int, Query(ge=16, le=4096)] = 200,
) -> FileResponse:
    photo = records.get_or_404(session, Photograph, photograph_id, "Photograph")
    attachments.require_readable(session, user, photo, RESOURCE, "Photograph")

    available = {int(key): value for key, value in (photo.thumbnails or {}).items()}
    if not available:
        # No thumbnail was generated; the original is the only thing to show.
        return attachments.serve(
            photo.file_path,
            filename=photo.original_filename,
            media_type=photo.mime_type,
            inline=True,
        )

    larger = sorted(width for width in available if width >= size)
    chosen = larger[0] if larger else max(available)
    return attachments.serve(
        available[chosen],
        filename=f"{photo.id}-{chosen}.jpg",
        media_type="image/jpeg",
        inline=True,
    )


@router.patch(
    "/{photograph_id}", response_model=PhotographDetail, summary="Update a photograph's details"
)
def update_photograph(
    photograph_id: uuid.UUID,
    payload: PhotographUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> PhotographDetail:
    photo = records.get_or_404(session, Photograph, photograph_id, "Photograph")
    attachments.require_editable(session, user, photo, RESOURCE, "Photograph")

    changes = payload.model_dump(exclude_unset=True)
    before = records.apply_changes(photo, changes)
    if changes.get("is_cover"):
        _clear_other_covers(session, photo)

    records.on_updated(session, photo, RESOURCE, before=before, user=user, request=request)
    session.flush()
    return _detail(session, photo, user)


@router.delete(
    "/{photograph_id}",
    response_model=Message,
    summary="Delete a photograph",
    description=(
        "Removes the record. The stored image itself is left in place: storage "
        "is content-addressed, so the same bytes may back another record, and "
        "only a sweep that checks every reference can safely remove them."
    ),
)
def delete_photograph(
    photograph_id: uuid.UUID, session: DbSession, request: Request, user: CurrentUser
) -> Message:
    photo = records.get_or_404(session, Photograph, photograph_id, "Photograph")
    attachments.require_readable(session, user, photo, RESOURCE, "Photograph")
    if not can_delete(session, user, photo, RESOURCE):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You may not delete this photograph")

    label = photo.title
    records.on_deleted(session, photo, RESOURCE, user=user, request=request, label=label)
    session.delete(photo)
    return Message(detail=f"Photograph {label!r} deleted")
