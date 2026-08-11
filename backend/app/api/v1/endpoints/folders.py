"""The media library: folders people make, and what they put in them.

Every photograph already belongs to a **record** — a site, a find, an object —
and that link is what permissions are decided by, what search uses, and what
survives somebody reorganising their filing. This is the other axis: a drawer,
made by hand, for finding things the way the person who put them away thinks
about them. "2024 / Trench A / working shots" is not a fact about the archive;
it is a fact about how one institution works, and it belongs to them.

The two do not compete, and the rule that keeps them from competing is that
**deleting a folder deletes no files**. A folder is a label. Removing the
label leaves what it was on.

Channels are folders. "The pictures we posted to Instagram" is a real drawer
in a real institution, and giving it a place in this tree beats a separate
module with a second, incompatible idea of a folder.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.models import ActivityAction, Document, Folder, FolderKind, Photograph, ResourceType
from app.schemas.common import Message
from app.schemas.folder import FolderCreate, FolderMove, FolderRead, FolderUpdate
from app.services import activity, records

router = APIRouter(prefix="/folders", tags=["Media library"])

RESOURCE = ResourceType.PHOTOGRAPH

#: How deep a tree may go. Not a technical limit — it is the depth past which
#: a folder tree stops being a way of finding things.
MAX_DEPTH = 8


def _counts(session: DbSession) -> dict[uuid.UUID, int]:
    """How many files are in each folder, in two queries rather than N."""
    totals: dict[uuid.UUID, int] = {}
    for model in (Photograph, Document):
        rows = session.execute(
            select(model.folder_id, func.count())
            .where(model.folder_id.is_not(None))
            .group_by(model.folder_id)
        )
        for folder_id, count in rows:
            totals[folder_id] = totals.get(folder_id, 0) + count
    return totals


def _read(folder: Folder, counts: dict[uuid.UUID, int]) -> FolderRead:
    return FolderRead(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        kind=folder.kind,
        note=folder.note,
        file_count=counts.get(folder.id, 0),
        created_at=folder.created_at,
    )


@router.get(
    "",
    response_model=list[FolderRead],
    summary="Every folder",
    description=(
        "The whole tree, flat, with each folder's parent. Flat rather than "
        "nested because the client draws the tree either way and a flat list "
        "can be searched, sorted and re-parented without unpicking it.\n\n"
        "`file_count` is what is filed **directly** in that folder, not "
        "including its children. A count that silently included everything "
        "underneath would make an empty folder look full."
    ),
)
def list_folders(
    session: DbSession,
    user: CurrentUser,
    kind: Annotated[FolderKind | None, Query(description="Only channel folders, say")] = None,
) -> list[FolderRead]:
    statement = select(Folder).order_by(Folder.name)
    if kind is not None:
        statement = statement.where(Folder.kind == kind)

    counts = _counts(session)
    return [_read(row, counts) for row in session.scalars(statement)]


def _depth(session: DbSession, folder_id: uuid.UUID | None) -> int:
    depth = 0
    current = folder_id
    seen: set[uuid.UUID] = set()
    while current is not None:
        if current in seen:  # pragma: no cover - a cycle cannot be created
            break
        seen.add(current)
        parent = session.get(Folder, current)
        if parent is None:
            break
        current = parent.parent_id
        depth += 1
    return depth


@router.post(
    "",
    response_model=FolderRead,
    status_code=status.HTTP_201_CREATED,
    summary="Make a folder",
    responses={
        409: {"description": "A folder of that name is already there"},
        422: {"description": "Nested too deeply, or the parent does not exist"},
    },
)
def create_folder(
    payload: FolderCreate, session: DbSession, request: Request, user: CurrentUser
) -> FolderRead:
    if payload.parent_id is not None:
        records.get_or_404(session, Folder, payload.parent_id, "Folder")
        if _depth(session, payload.parent_id) >= MAX_DEPTH:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"That would be {MAX_DEPTH + 1} folders deep. Past about "
                    f"{MAX_DEPTH} a tree stops being a way of finding things."
                ),
            )

    clash = session.scalar(
        select(Folder).where(
            Folder.parent_id.is_(payload.parent_id)
            if payload.parent_id is None
            else Folder.parent_id == payload.parent_id,
            func.lower(Folder.name) == payload.name.lower(),
        )
    )
    if clash is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"There is already a folder called {payload.name!r} there.",
        )

    folder = Folder(
        name=payload.name,
        parent_id=payload.parent_id,
        kind=payload.kind,
        note=payload.note,
        owner_id=user.id,
    )
    session.add(folder)
    session.flush()

    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=folder.id,
        resource_label=folder.name,
        summary=f"Made the folder {folder.name!r}",
        request=request,
    )
    session.flush()
    return _read(folder, _counts(session))


@router.patch(
    "/{folder_id}",
    response_model=FolderRead,
    summary="Rename or move a folder",
    responses={422: {"description": "Would put a folder inside itself"}},
)
def update_folder(
    folder_id: uuid.UUID, payload: FolderUpdate, session: DbSession, user: CurrentUser
) -> FolderRead:
    folder = records.get_or_404(session, Folder, folder_id, "Folder")

    if payload.parent_id is not None or "parent_id" in payload.model_fields_set:
        target = payload.parent_id
        if target == folder.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A folder cannot be inside itself.",
            )
        # Walking up from the intended parent is the only way to catch this:
        # dropping a folder into its own grandchild detaches the whole branch
        # from the tree, and it is then reachable from nothing.
        walker = target
        while walker is not None:
            if walker == folder.id:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "That would put this folder inside one of its own "
                        "folders, and everything in it would be unreachable."
                    ),
                )
            parent = session.get(Folder, walker)
            walker = parent.parent_id if parent else None
        folder.parent_id = target

    if payload.name is not None:
        folder.name = payload.name
    if payload.note is not None:
        folder.note = payload.note
    session.flush()
    return _read(folder, _counts(session))


@router.delete(
    "/{folder_id}",
    response_model=Message,
    summary="Remove a folder",
    description=(
        "The folder and its sub-folders go. **The files do not** — they become "
        "unfiled and are still on the records they belong to. A folder is a "
        "label; removing the label leaves what it was on."
    ),
)
def delete_folder(
    folder_id: uuid.UUID, session: DbSession, request: Request, user: CurrentUser
) -> Message:
    folder = records.get_or_404(session, Folder, folder_id, "Folder")
    label = folder.name

    session.delete(folder)
    session.flush()

    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=user,
        resource_type=RESOURCE,
        resource_id=folder_id,
        resource_label=label,
        summary=f"Removed the folder {label!r}",
        request=request,
    )
    session.flush()
    return Message(
        detail=(
            f"Folder {label!r} removed. Nothing in it was deleted — those files "
            f"are unfiled now, and still on their records."
        )
    )


@router.post(
    "/{folder_id}/contents",
    response_model=Message,
    summary="Put files in a folder",
    description=(
        "Moves them: a file is in one folder, because a photograph in three "
        "folders is a photograph nobody can file.\n\n"
        "Post to `/folders/none/contents` to take them out again."
    ),
)
def file_into(
    folder_id: str, payload: FolderMove, session: DbSession, request: Request, user: CurrentUser
) -> Message:
    target: uuid.UUID | None = None
    label = "unfiled"
    if folder_id != "none":
        try:
            target = uuid.UUID(folder_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such folder") from exc
        folder = records.get_or_404(session, Folder, target, "Folder")
        label = folder.name

    moved = 0
    for model, ids in ((Photograph, payload.photograph_ids), (Document, payload.document_ids)):
        for identifier in ids:
            record: Any = session.get(model, identifier)
            if record is None:
                continue
            record.folder_id = target
            moved += 1
    session.flush()

    if moved == 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nothing was moved — none of those files exist.",
        )

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=target,
        resource_label=label,
        summary=f"Filed {moved} file{'' if moved == 1 else 's'} into {label!r}",
        request=request,
    )
    session.flush()
    return Message(detail=f"{moved} file{'' if moved == 1 else 's'} moved to {label}.")
