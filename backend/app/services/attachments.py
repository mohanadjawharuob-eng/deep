"""Shared behaviour for media records.

Photographs, documents and 3D models all hang from a project, site, artifact or
context, and all inherit their permissions from whatever they hang from. This
module holds the parts that must behave identically for all three: resolving
those links, deciding who may attach, and serving a stored file back safely.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.permissions import can_edit, can_view, resolve_project_id
from app.models.artifact import Artifact
from app.models.context import ExcavationContext
from app.models.enums import ResourceType
from app.models.project import Project
from app.models.site import Site
from app.models.user import User
from app.services import records
from app.services.storage import StorageError, safe_filename, storage


def resolve_attachment(
    session: Session,
    user: User,
    *,
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    artifact_id: uuid.UUID | None = None,
    context_id: uuid.UUID | None = None,
) -> dict[str, uuid.UUID | None]:
    """Validate the parents a media record is being attached to.

    Every id given must exist and be visible, and the user must be entitled to
    contribute to the project they belong to. Returns the link columns with the
    project filled in — a photograph of an artifact belongs to that artifact
    *and* to its site and project, and storing all three is what lets the
    gallery at any level be a single indexed query.
    """
    links: dict[str, uuid.UUID | None] = {
        "project_id": project_id,
        "site_id": site_id,
        "artifact_id": artifact_id,
        "context_id": context_id,
    }

    if not any(links.values()):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Attach this to a project, site, artifact or context — an "
                "unattached file cannot be found again or permission-checked"
            ),
        )

    # Resolve from the most specific link upwards, so the parents are
    # consistent even when the client sends only the deepest one.
    if artifact_id is not None:
        artifact = records.get_or_404(session, Artifact, artifact_id, "Artifact")
        _require_visible(session, user, artifact, ResourceType.ARTIFACT, "Artifact")
        links["site_id"] = artifact.site_id
        if context_id is None and artifact.context_id is not None:
            links["context_id"] = artifact.context_id

    if links["context_id"] is not None:
        context = records.get_or_404(session, ExcavationContext, links["context_id"], "Context")
        _require_visible(session, user, context, ResourceType.CONTEXT, "Context")
        if artifact_id is not None and context.site_id != links["site_id"]:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="That context belongs to a different site than the artifact",
            )
        links["site_id"] = links["site_id"] or context.site_id

    if links["site_id"] is not None:
        site = records.get_or_404(session, Site, links["site_id"], "Site")
        _require_visible(session, user, site, ResourceType.SITE, "Site")
        links["project_id"] = site.project_id
    elif links["project_id"] is not None:
        project = records.get_or_404(session, Project, links["project_id"], "Project")
        _require_visible(session, user, project, ResourceType.PROJECT, "Project")

    # One check, at the project level, mirroring how records are created.
    records.check_can_contribute(session, user, links["project_id"])
    return links


def _require_visible(
    session: Session, user: User, record: Any, resource_type: ResourceType, name: str
) -> None:
    if not can_view(session, user, record, resource_type):
        # 404 rather than 403: whether the id exists is itself information.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{name} not found")


def require_readable(
    session: Session, user: User | None, record: Any, resource_type: ResourceType, name: str
) -> None:
    if not can_view(session, user, record, resource_type):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{name} not found")


def require_editable(
    session: Session, user: User | None, record: Any, resource_type: ResourceType, name: str
) -> None:
    require_readable(session, user, record, resource_type, name)
    if not can_edit(session, user, record, resource_type):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail=f"You may not edit this {name.lower()}"
        )


def serve(
    relative_path: str,
    *,
    filename: str | None,
    media_type: str | None,
    inline: bool = False,
) -> FileResponse:
    """Return a stored file as a download.

    ``Content-Disposition: attachment`` by default. Serving user-uploaded
    content inline from the API's own origin would let an uploaded HTML or SVG
    file run script as the platform; only image thumbnails and previews, whose
    type this application decides rather than the uploader, are served inline.
    """
    try:
        path = storage.absolute_path(relative_path)
    except StorageError as exc:
        # The row exists but the bytes do not — a restore that missed the
        # uploads volume, or a half-finished migration.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="The stored file is missing. It may not have survived a restore.",
        ) from exc

    disposition = "inline" if inline else "attachment"
    download_name = safe_filename(filename, "download")
    return FileResponse(
        path,
        media_type=media_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'{disposition}; filename="{download_name}"',
            # Belt and braces: even inline, never let the browser guess a type.
            "X-Content-Type-Options": "nosniff",
        },
    )


def project_of(session: Session, record: Any) -> uuid.UUID | None:
    return resolve_project_id(session, record)


def log_upload(
    session: Session,
    *,
    record: Any,
    resource_type: ResourceType,
    user: User,
    request: Request | None,
    summary: str | None = None,
) -> None:
    """Record an upload in the audit trail."""
    from app.models.enums import ActivityAction
    from app.services import activity

    activity.log(
        session,
        action=ActivityAction.UPLOAD,
        user=user,
        resource_type=resource_type,
        resource_id=record.id,
        resource_label=records.label_for(record),
        project_id=getattr(record, "project_id", None) or project_of(session, record),
        summary=summary,
        request=request,
    )
