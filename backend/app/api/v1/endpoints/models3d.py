"""3D models: links to external viewers, and small uploaded meshes."""

from __future__ import annotations

import re
import uuid
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, CurrentUserOptional, DbSession
from app.core.config import settings
from app.core.permissions import can_delete, can_edit, visibility_filter
from app.models.enums import Model3DFormat, ResourceType
from app.models.media import Model3D
from app.models.user import User
from app.schemas.common import Message, Page
from app.schemas.media import Model3DCreate, Model3DDetail, Model3DSummary, Model3DUpdate
from app.services import attachments, records
from app.services.storage import CATEGORY_MODELS, extension_of, storage

router = APIRouter(prefix="/models3d", tags=["3D models"])

RESOURCE = ResourceType.MODEL3D

#: Mesh formats small enough to be worth hosting. Photogrammetry output is
#: usually far too large, which is why linking is the primary path.
MESH_EXTENSIONS: dict[str, tuple[Model3DFormat, str]] = {
    ".obj": (Model3DFormat.OBJ, "model/obj"),
    ".ply": (Model3DFormat.PLY, "application/octet-stream"),
    ".stl": (Model3DFormat.STL, "model/stl"),
    ".glb": (Model3DFormat.GLB, "model/gltf-binary"),
    ".gltf": (Model3DFormat.GLTF, "model/gltf+json"),
    ".fbx": (Model3DFormat.FBX, "application/octet-stream"),
}

#: Hosts whose viewers can be embedded, and how to build the embed URL.
#:
#: An allow-list rather than embedding whatever URL is supplied: an ``<iframe>``
#: pointing at an arbitrary address is a phishing surface, and the frontend
#: would be framing it under this platform's name.
#: Sketchfab addresses a model two ways: the old ``/models/<id>`` and the
#: current ``/3d-models/<title-slug>-<id>``, where the id is the last component
#: of the slug. Both end in the same 32-character hexadecimal id, which is all
#: the embed URL is built from — the rest of the supplied address is discarded
#: rather than passed through.
_SKETCHFAB_MODEL = re.compile(r"/(?:3d-)?models/(?:[^/]*-)?([0-9a-f]{32})(?:/|$)", re.IGNORECASE)


def embed_url_for(external_url: str | None) -> str | None:
    """The embeddable form of a known viewer URL, or ``None``.

    ``None`` is not a failure — it means "link to it, do not frame it", which
    is the right answer for anything not recognised.
    """
    if not external_url:
        return None

    parsed = urlparse(external_url)
    if parsed.scheme not in ("http", "https"):
        return None

    host = (parsed.hostname or "").lower()

    if host in ("sketchfab.com", "www.sketchfab.com"):
        match = _SKETCHFAB_MODEL.search(parsed.path.rstrip("/"))
        if match:
            return f"https://sketchfab.com/models/{match.group(1).lower()}/embed"
        return None

    # Potree and other self-hosted viewers are served by the institution
    # itself; they are linked, not framed, because we cannot vouch for them.
    return None


def _validate_external_url(url: str | None) -> None:
    if url is None:
        return
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The link must be an http or https address",
        )


def _summary(model: Model3D) -> Model3DSummary:
    payload = Model3DSummary.model_validate(model)
    payload.has_file = bool(model.file_path)
    return payload


def _detail(session: DbSession, model: Model3D, user: User | None) -> Model3DDetail:
    payload = Model3DDetail.model_validate(model)
    payload.has_file = bool(model.file_path)
    payload.can_edit = can_edit(session, user, model, RESOURCE)
    payload.can_delete = can_delete(session, user, model, RESOURCE)
    return payload


@router.post(
    "",
    response_model=Model3DDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Link a 3D model",
    description=(
        "Records a model that lives elsewhere — Sketchfab, a RealityScan or "
        "Metashape project, an institutional repository. Recognised viewers "
        "also get an `embed_url` that can be shown in the page; anything else "
        "is linked rather than framed.\n\n"
        "To upload a mesh instead, use `POST /models3d/upload`."
    ),
)
def link_model(
    payload: Model3DCreate, session: DbSession, request: Request, user: CurrentUser
) -> Model3DDetail:
    links = attachments.resolve_attachment(
        session,
        user,
        project_id=payload.project_id,
        site_id=payload.site_id,
        artifact_id=payload.artifact_id,
        context_id=payload.context_id,
    )
    _validate_external_url(payload.external_url)

    # Every parent comes back from `resolve_attachment`, which fills in the
    # ones the client did not send. Leaving them in `data` as well would pass
    # each twice.
    data = payload.model_dump(
        exclude={"project_id", "site_id", "artifact_id", "context_id", "museum_object_id"}
    )
    model = Model3D(
        **data,
        **links,
        embed_url=embed_url_for(payload.external_url),
        owner_id=user.id,
    )
    session.add(model)
    session.flush()

    attachments.log_upload(
        session,
        record=model,
        resource_type=RESOURCE,
        user=user,
        request=request,
        summary=f"Linked 3D model {model.title!r}",
    )
    session.flush()
    return _detail(session, model, user)


@router.post(
    "/upload",
    response_model=Model3DDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a 3D mesh",
    description=(
        "For meshes small enough to host — a decimated model for in-browser "
        "preview, typically. Full-resolution photogrammetry output belongs "
        "elsewhere; link to it with `POST /models3d` instead.\n\n"
        f"Accepted: {', '.join(sorted(MESH_EXTENSIONS))}."
    ),
    responses={413: {"description": "Larger than the configured limit"}},
)
async def upload_model(
    session: DbSession,
    request: Request,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="The mesh file")],
    title: Annotated[str | None, Form(max_length=300)] = None,
    description: Annotated[str | None, Form()] = None,
    capture_method: Annotated[str | None, Form(max_length=120)] = None,
    software: Annotated[str | None, Form(max_length=150)] = None,
    scale_note: Annotated[str | None, Form(max_length=200)] = None,
    license: Annotated[str | None, Form(max_length=120)] = None,
    is_public: Annotated[bool, Form()] = False,
    project_id: Annotated[uuid.UUID | None, Form()] = None,
    site_id: Annotated[uuid.UUID | None, Form()] = None,
    artifact_id: Annotated[uuid.UUID | None, Form()] = None,
    context_id: Annotated[uuid.UUID | None, Form()] = None,
    museum_object_id: Annotated[uuid.UUID | None, Form()] = None,
) -> Model3DDetail:
    links = attachments.resolve_attachment(
        session,
        user,
        project_id=project_id,
        site_id=site_id,
        artifact_id=artifact_id,
        context_id=context_id,
        museum_object_id=museum_object_id,
    )

    extension = extension_of(file.filename)
    if extension not in MESH_EXTENSIONS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{extension or 'That file'} is not an accepted mesh format. "
                f"Accepted: {', '.join(sorted(MESH_EXTENSIONS))}."
            ),
        )
    model_format, mime_type = MESH_EXTENSIONS[extension]

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"That mesh is larger than the {settings.MAX_UPLOAD_SIZE_MB} MB limit. "
                    f"Host it elsewhere and link to it instead."
                ),
            )

    stored = storage.save_bytes(bytes(data), category=CATEGORY_MODELS, extension=extension)

    model = Model3D(
        title=title or (file.filename or "3D model"),
        description=description,
        format=model_format,
        file_path=stored.path,
        file_size=stored.size,
        checksum=stored.checksum,
        capture_method=capture_method,
        software=software,
        scale_note=scale_note,
        license=license,
        is_public=is_public,
        owner_id=user.id,
        **links,
    )
    session.add(model)
    session.flush()

    attachments.log_upload(
        session,
        record=model,
        resource_type=RESOURCE,
        user=user,
        request=request,
        summary=f"Uploaded 3D mesh {model.title!r}",
    )
    session.flush()
    return _detail(session, model, user)


@router.get("", response_model=Page[Model3DSummary], summary="List 3D models")
def list_models(
    session: DbSession,
    user: CurrentUserOptional,
    q: Annotated[str | None, Query()] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    site_id: Annotated[uuid.UUID | None, Query()] = None,
    artifact_id: Annotated[uuid.UUID | None, Query()] = None,
    format: Annotated[Model3DFormat | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[Model3DSummary]:
    statement = select(Model3D).where(visibility_filter(user, Model3D, RESOURCE))

    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Model3D.title).like(pattern),
                func.lower(Model3D.description).like(pattern),
            )
        )
    if project_id is not None:
        statement = statement.where(Model3D.project_id == project_id)
    if site_id is not None:
        statement = statement.where(Model3D.site_id == site_id)
    if artifact_id is not None:
        statement = statement.where(Model3D.artifact_id == artifact_id)
    if format is not None:
        statement = statement.where(Model3D.format == format)

    statement = statement.order_by(Model3D.created_at.desc(), Model3D.id.desc())
    rows, total = records.paginate(session, statement, limit, offset)
    return Page[Model3DSummary](
        items=[_summary(row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.get("/{model_id}", response_model=Model3DDetail, summary="Read a 3D model")
def read_model(model_id: uuid.UUID, session: DbSession, user: CurrentUserOptional) -> Model3DDetail:
    model = records.get_or_404(session, Model3D, model_id, "3D model")
    attachments.require_readable(session, user, model, RESOURCE, "3D model")
    return _detail(session, model, user)


@router.get(
    "/{model_id}/file",
    summary="Download an uploaded mesh",
    responses={
        200: {"content": {"application/octet-stream": {}}, "description": "The mesh"},
        404: {"description": "This model is a link, not an uploaded file"},
    },
    response_class=FileResponse,
)
def download_model(
    model_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> FileResponse:
    model = records.get_or_404(session, Model3D, model_id, "3D model")
    attachments.require_readable(session, user, model, RESOURCE, "3D model")

    if not model.file_path:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="This model is hosted elsewhere; use its external_url",
        )

    extension = extension_of(model.file_path, ".bin")
    _, mime_type = MESH_EXTENSIONS.get(extension, (None, "application/octet-stream"))
    return attachments.serve(
        model.file_path,
        filename=f"{model.title}{extension}",
        media_type=mime_type,
        inline=False,
    )


@router.patch("/{model_id}", response_model=Model3DDetail, summary="Update a 3D model")
def update_model(
    model_id: uuid.UUID,
    payload: Model3DUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> Model3DDetail:
    model = records.get_or_404(session, Model3D, model_id, "3D model")
    attachments.require_editable(session, user, model, RESOURCE, "3D model")

    changes = payload.model_dump(exclude_unset=True)
    if "external_url" in changes:
        _validate_external_url(changes["external_url"])
        changes["embed_url"] = embed_url_for(changes["external_url"])

    before = records.apply_changes(model, changes)
    records.on_updated(session, model, RESOURCE, before=before, user=user, request=request)
    session.flush()
    return _detail(session, model, user)


@router.delete("/{model_id}", response_model=Message, summary="Delete a 3D model")
def delete_model(
    model_id: uuid.UUID, session: DbSession, request: Request, user: CurrentUser
) -> Message:
    model = records.get_or_404(session, Model3D, model_id, "3D model")
    attachments.require_readable(session, user, model, RESOURCE, "3D model")
    if not can_delete(session, user, model, RESOURCE):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You may not delete this model")

    label = model.title
    records.on_deleted(session, model, RESOURCE, user=user, request=request, label=label)
    session.delete(model)
    return Message(detail=f"3D model {label!r} deleted")
