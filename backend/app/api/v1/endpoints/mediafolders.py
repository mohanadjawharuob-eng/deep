"""Folders of files that live somewhere else.

Sometimes uploading is the wrong answer. A season's raw frames are four hundred
gigabytes, already on the project drive, already backed up, and nobody is going
to look at them through a web page. Pushing them through this platform costs a
week of somebody's time and buys nothing.

What is *not* optional is that the catalogue knows the material exists. A record
that is silent about four hundred gigabytes will be read as complete, and the
drive will be reformatted by somebody who checked the archive first.

So a folder can be recorded instead of uploaded: what is in it, where it is,
which disk that is, how many files were there when somebody looked. It is a note
in the archive, and everything here is careful not to pretend otherwise — the
platform cannot open the path, cannot check it, and cannot tell you when it
stops being true.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, CurrentUserOptional, DbSession
from app.core.permissions import can_delete, visibility_filter
from app.models.enums import MediaFolderKind, ResourceType
from app.models.media import MediaFolder
from app.schemas.common import Message, Page
from app.schemas.mediafolders import (
    MediaFolderCreate,
    MediaFolderRead,
    MediaFolderUpdate,
)
from app.services import attachments, records

router = APIRouter(prefix="/media-folders", tags=["Media folders"])

#: Which record a folder is filed under, for permission checks. The folder
#: itself is not a resource type: it has no life of its own, and its
#: visibility is entirely its parent's.
RESOURCE = ResourceType.PHOTOGRAPH


@router.post(
    "",
    response_model=MediaFolderRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record a folder that is not being uploaded",
    description=(
        "For material that exists and is not coming in here: a season's raw "
        "frames, a photogrammetry set, a shelf of survey data.\n\n"
        "The path is stored exactly as written and is never opened, resolved "
        "or checked. It may be a Windows path, a network share, a mount point "
        "on somebody's laptop, or a shelf reference for a box of discs.\n\n"
        "Name the **medium** as well as the path. It is the field most often "
        "left out and the one that matters in five years: a path with no disk "
        "names a folder on a machine nobody can identify."
    ),
)
def create_folder(
    payload: MediaFolderCreate, session: DbSession, request: Request, user: CurrentUser
) -> MediaFolderRead:
    links = attachments.resolve_attachment(
        session,
        user,
        project_id=payload.project_id,
        site_id=payload.site_id,
        artifact_id=payload.artifact_id,
        context_id=payload.context_id,
    )

    data = payload.model_dump(exclude={"project_id", "site_id", "artifact_id", "context_id"})
    folder = MediaFolder(**data, **links, owner_id=user.id)
    session.add(folder)
    session.commit()
    session.refresh(folder)
    return MediaFolderRead.model_validate(folder)


@router.get(
    "",
    response_model=Page[MediaFolderRead],
    summary="Folders recorded against a record",
    description=(
        "Filter by whichever parent you are looking at. Asking for none of "
        "them lists everything visible, which is the closest thing this "
        "platform has to a register of what is on the shelf."
    ),
)
def list_folders(
    session: DbSession,
    user: CurrentUserOptional,
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    artifact_id: uuid.UUID | None = None,
    context_id: uuid.UUID | None = None,
    kind: MediaFolderKind | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[MediaFolderRead]:
    statement = select(MediaFolder).where(visibility_filter(user, MediaFolder, RESOURCE))
    for column, value in (
        (MediaFolder.project_id, project_id),
        (MediaFolder.site_id, site_id),
        (MediaFolder.artifact_id, artifact_id),
        (MediaFolder.context_id, context_id),
        (MediaFolder.kind, kind),
    ):
        if value is not None:
            statement = statement.where(column == value)

    statement = statement.order_by(MediaFolder.kind, MediaFolder.label)
    rows, total = records.paginate(session, statement, limit, offset)
    return Page[MediaFolderRead](
        items=[MediaFolderRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{folder_id}", response_model=MediaFolderRead, summary="One recorded folder")
def read_folder(
    folder_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> MediaFolderRead:
    folder = records.get_or_404(session, MediaFolder, folder_id, "Folder")
    attachments.require_readable(session, user, folder, RESOURCE, "Folder")
    return MediaFolderRead.model_validate(folder)


@router.patch("/{folder_id}", response_model=MediaFolderRead, summary="Correct a recorded folder")
def update_folder(
    folder_id: uuid.UUID,
    payload: MediaFolderUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> MediaFolderRead:
    folder = records.get_or_404(session, MediaFolder, folder_id, "Folder")
    attachments.require_editable(session, user, folder, RESOURCE, "Folder")

    for name, value in payload.model_dump(exclude_unset=True).items():
        setattr(folder, name, value)
    session.commit()
    session.refresh(folder)
    return MediaFolderRead.model_validate(folder)


@router.delete("/{folder_id}", response_model=Message, summary="Forget a recorded folder")
def delete_folder(
    folder_id: uuid.UUID, session: DbSession, request: Request, user: CurrentUser
) -> Message:
    folder = records.get_or_404(session, MediaFolder, folder_id, "Folder")
    attachments.require_readable(session, user, folder, RESOURCE, "Folder")
    if not can_delete(session, user, folder, RESOURCE):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You may not delete this record")

    label = folder.label
    records.on_deleted(session, folder, RESOURCE, user=user, request=request, label=label)
    session.delete(folder)
    session.commit()
    # Said plainly, because "delete" beside a path reads like it might remove
    # the folder, and somebody has to be sure it does not.
    return Message(detail=f"{label!r} is no longer recorded. Nothing on disk was touched.")
