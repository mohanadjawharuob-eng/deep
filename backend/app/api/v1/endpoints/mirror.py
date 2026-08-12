"""The archive as a folder tree, on the disk, for picking up locally.

The file store is content-addressed on purpose: ``photographs/ab/cd/9f3e….jpg``
means the same bytes are stored once, and a filename can never decide where
something lands. It is the right shape for a store and the wrong shape for a
person, and until now it was the *only* shape — so an institution that wanted
its own material without going through a browser had a disk full of hex.

The mirror is the other view. The same files, copied into folders named after
the records:

    Library/
      Sites/
        TED-A North trench/
          Photographs/
          Documents/
      Museum/
        Founding collection/
          Photographs/
      Sheets/

Three things it is careful about.

**It never moves the archive's copy.** The mirror is a second copy. Deleting
the whole of it costs nothing but disk.

**It rebuilds, it does not sync.** Working out what changed since last time is
where mirrors go wrong and start deleting things people put there by hand. This
writes into a fresh folder and swaps it in, so a half-finished run never leaves
a partial tree where the good one was.

**It is a button, not a schedule.** A copy of every photograph is a real cost
in disk and time, and a platform that quietly doubles its own storage in the
background is one that fills a disk at three in the morning.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from app.api.deps import DbSession, require_capability
from app.core.permissions import Capability
from app.models.enums import ActivityAction
from app.models.user import User
from app.services import activity, handover
from app.services.storage import storage

router = APIRouter(prefix="/mirror", tags=["Deliveries"])

Keeper = Annotated[User, Depends(require_capability(Capability.EXPORT_DATA))]

#: The one folder on the disk anybody outside the platform should ever need to
#: open. Named for what it is, in a word people already use for it.
FOLDER = "Library"


class MirrorState(BaseModel):
    """What is on the disk now."""

    folder_on_disk: str
    exists: bool
    files: int = 0
    size_bytes: int = 0
    built_at: datetime | None = None
    #: Files the database knows about that were not on disk when it was built.
    missing: list[str] = []


class MirrorResult(MirrorState):
    detail: str


def _state(root) -> MirrorState:
    if not root.is_dir():
        return MirrorState(folder_on_disk=str(root), exists=False)
    # The two bookkeeping files are not archive files, and counting them makes
    # the panel disagree with the message the build itself printed.
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.name not in {"About this folder.txt", ".built"}
    ]
    stamp = root / ".built"
    built = None
    if stamp.is_file():
        try:
            built = datetime.fromisoformat(stamp.read_text(encoding="utf-8").strip())
        except ValueError:
            built = None
    return MirrorState(
        folder_on_disk=str(root),
        exists=True,
        files=len(files),
        size_bytes=sum(path.stat().st_size for path in files),
        built_at=built,
    )


@router.get(
    "",
    response_model=MirrorState,
    summary="The folder on your disk",
    description=(
        "Where the readable copy of the archive sits, how much is in it, and "
        "when it was last built. On the machine the platform runs on this "
        "folder can simply be opened; on a NAS or a mounted drive it is the "
        "path to browse to."
    ),
)
def read_mirror(session: DbSession, user: Keeper) -> MirrorState:
    return _state(storage.root / FOLDER)


@router.post(
    "",
    response_model=MirrorResult,
    status_code=status.HTTP_200_OK,
    summary="Build the folder again",
    description=(
        "Copies every photograph, document and sheet into folders named after "
        "the records they belong to.\\n\\n"
        "It rebuilds rather than syncing: the new tree is written beside the "
        "old one and swapped in, so an interrupted run never leaves a partial "
        "tree where the good one was. Nothing in the archive is moved — the "
        "mirror is a second copy, and deleting all of it costs nothing but "
        "disk."
    ),
)
def build_mirror(session: DbSession, request: Request, user: Keeper) -> MirrorResult:
    root = storage.root / FOLDER
    staging = storage.root / f"{FOLDER}.building"
    shutil.rmtree(staging, ignore_errors=True)

    written = handover.write(handover.everything(session), staging)
    (staging / "About this folder.txt").write_text(
        handover.readme(
            "The archive, as folders",
            (
                "A readable copy of everything the platform holds, rebuilt on "
                "request. The platform still has its own copy of every file "
                "here; nothing was moved. Anything you add to this folder "
                "yourself will be gone the next time it is rebuilt."
            ),
            written,
        ),
        encoding="utf-8",
    )
    (staging / ".built").write_text(datetime.now(UTC).isoformat(), encoding="utf-8")

    # The swap. Old out of the way first, new into place, then the old one
    # deleted - so at no point is there no tree at all.
    retiring = storage.root / f"{FOLDER}.previous"
    shutil.rmtree(retiring, ignore_errors=True)
    if root.exists():
        root.rename(retiring)
    staging.rename(root)
    shutil.rmtree(retiring, ignore_errors=True)

    activity.log(
        session,
        action=ActivityAction.EXPORT,
        user=user,
        resource_label=FOLDER,
        summary=f"Rebuilt the readable folder on the disk ({written.files} files)",
        request=request,
    )

    state = _state(root)
    return MirrorResult(
        **state.model_dump(exclude={"missing"}),
        missing=written.missing,
        detail=(
            f"{written.files} file(s) written to {root}. "
            "Open that folder to browse the archive without the platform."
        ),
    )
