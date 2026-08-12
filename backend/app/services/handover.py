"""Getting files out of the platform and onto a disk somebody can open.

Two things use this, and they are the same problem at different sizes.

**A delivery.** Somebody picks forty photographs and a sheet and asks for them
to go to a colleague. The colleague does not have an account and should not
need one.

**The mirror.** The whole archive, written out to the assigned disk as a tree
of named folders, so the institution can pick material up locally — from a
backup drive, from the machine the platform runs on, from anywhere the
platform itself is not.

Both need the same thing the file store deliberately does not provide: **names
a person can read**. Storage is content-addressed — ``photographs/ab/cd/9f3e…
.jpg`` — which is right for a store and useless for a human being standing in
front of a folder. So this module builds the other view: the same bytes, under
names taken from the records.

Three rules the layout keeps, all of them learned from filing systems that did
not:

**No single-child chains.** A folder that contains exactly one folder that
contains exactly one folder is four clicks of nothing. Where a level would hold
one child and no files, it is collapsed into its parent's name.

**Three levels, and then files.** ``Sites / TED-A North trench / Photographs``.
Deeper than that and nobody can say where anything is without opening it.

**The name says what it is.** A site folder is named with its code *and* its
name, because the code is what is written on the bags and the name is what
people say out loud, and somebody looking for the material has only one of the
two in their head.
"""

from __future__ import annotations

import re
import shutil
import unicodedata
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.imports import ImportBatch
from app.models.media import Document, Photograph
from app.models.museum import Collection, MuseumObject
from app.models.site import Site
from app.services.storage import storage

#: Characters that make a filename unusable on Windows, on a network share, or
#: in a shell. Replaced rather than stripped, so two different names cannot
#: collapse into one.
_AWKWARD = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def readable(name: str | None, fallback: str = "Untitled") -> str:
    """A folder or file name a person can read and every system accepts."""
    if not name:
        return fallback
    cleaned = unicodedata.normalize("NFC", name).strip()
    cleaned = _AWKWARD.sub("-", cleaned)
    # Trailing dots and spaces are legal on Linux and refused by Windows, which
    # is exactly the sort of thing that breaks a copy at 98%.
    cleaned = cleaned.rstrip(". ").strip()
    return cleaned[:80] or fallback


def _unique(folder: Path, name: str) -> Path:
    """A path in ``folder`` called ``name``, or the next free variation.

    Two photographs called "Trench A" is normal and must not silently become
    one file. The suffix goes before the extension so the file still opens.
    """
    candidate = folder / name
    if not candidate.exists():
        return candidate
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        stem, suffix = name, ""
    for counter in range(2, 1000):
        attempt = folder / (f"{stem} ({counter}).{suffix}" if suffix else f"{stem} ({counter})")
        if not attempt.exists():
            return attempt
    return folder / f"{stem} ({uuid.uuid4().hex[:8]}).{suffix}"


@dataclass(slots=True)
class Item:
    """One file on its way out: where it is now, and what to call it."""

    #: Relative path inside the file store.
    stored_path: str
    #: Folder within the bundle, using ``/``. May be empty for the top level.
    folder: str
    filename: str


@dataclass(slots=True)
class Written:
    """What actually landed on disk."""

    root: Path
    files: int = 0
    missing: list[str] = field(default_factory=list)
    bytes_written: int = 0


# --------------------------------------------------------------------------
# Naming records
# --------------------------------------------------------------------------
def site_folder(site: Site) -> str:
    """``TED-A North trench`` — the code and the name, because people carry one
    of the two in their head and not always the same one."""
    parts = [part for part in (site.code, site.name) if part]
    return readable(" ".join(parts), "Site")


def object_folder(item: MuseumObject) -> str:
    parts = [part for part in (item.accession_number, item.title) if part]
    return readable(" ".join(parts), "Object")


def photograph_name(photo: Photograph) -> str:
    """The title, keeping the original file's extension.

    Named from the title rather than from ``original_filename`` because
    ``IMG_4471.JPG`` tells nobody anything, and the title is what somebody
    typed when they knew what the picture was of.
    """
    suffix = Path(photo.original_filename or "").suffix or ".jpg"
    return readable(photo.title, "Photograph") + suffix.lower()


def document_name(document: Document) -> str:
    suffix = Path(document.original_filename or "").suffix
    return readable(document.title, "Document") + suffix.lower()


# --------------------------------------------------------------------------
# Where a photograph belongs in the readable tree
# --------------------------------------------------------------------------
def _folder_for_photograph(session: Session, photo: Photograph) -> str:
    """The one place in the tree this picture goes.

    A photograph of a find sits under its site, not in a separate Finds tree:
    somebody looking for "everything from Tell el-Demo" wants one folder, and
    the platform already knows the site because an upload against a find
    records it.
    """
    if photo.museum_object_id is not None:
        item = session.get(MuseumObject, photo.museum_object_id)
        if item is not None:
            collection = session.get(Collection, item.collection_id) if item.collection_id else None
            where = readable(collection.name if collection else "Museum", "Museum")
            return f"Museum/{where}/Photographs"
    if photo.site_id is not None:
        site = session.get(Site, photo.site_id)
        if site is not None:
            return f"Sites/{site_folder(site)}/Photographs"
    if photo.project_id is not None:
        from app.models.project import Project

        project = session.get(Project, photo.project_id)
        if project is not None:
            return f"Projects/{readable(project.name, 'Project')}/Photographs"
    # Deliberately a real folder rather than the top level. A picture attached
    # to nothing is a fact about the archive, and hiding it among the filed
    # ones is how it stays unattached forever.
    return "Not attached to a record"


# --------------------------------------------------------------------------
# Building the list of what goes out
# --------------------------------------------------------------------------
def items_for_photographs(session: Session, ids: list[uuid.UUID]) -> list[Item]:
    rows = session.scalars(select(Photograph).where(Photograph.id.in_(ids))).all() if ids else []
    return [
        Item(
            stored_path=photo.file_path,
            folder=_folder_for_photograph(session, photo),
            filename=photograph_name(photo),
        )
        for photo in rows
    ]


def items_for_documents(session: Session, ids: list[uuid.UUID]) -> list[Item]:
    rows = session.scalars(select(Document).where(Document.id.in_(ids))).all() if ids else []
    return [
        Item(stored_path=doc.file_path, folder="Documents", filename=document_name(doc))
        for doc in rows
    ]


def items_for_sheets(session: Session, ids: list[uuid.UUID]) -> list[Item]:
    """Sheets go out as they arrived, and up to date where a copy exists.

    Both, side by side, with names that say which is which. Sending only the
    rebuilt one loses the evidence; sending only the original sends stale data
    to somebody who asked for the current state.
    """
    rows = session.scalars(select(ImportBatch).where(ImportBatch.id.in_(ids))).all() if ids else []
    items: list[Item] = []
    for batch in rows:
        stem = batch.filename.rsplit(".", 1)[0]
        suffix = Path(batch.filename).suffix or ".xlsx"
        items.append(
            Item(
                stored_path=batch.stored_path,
                folder="Sheets",
                filename=readable(f"{stem} (as received)") + suffix,
            )
        )
        if batch.refreshed_path:
            items.append(
                Item(
                    stored_path=batch.refreshed_path,
                    folder="Sheets",
                    filename=readable(f"{stem} (up to date)") + ".xlsx",
                )
            )
    return items


def everything(session: Session) -> list[Item]:
    """The whole archive as a readable tree, for the mirror."""
    items: list[Item] = []

    for photo in session.scalars(select(Photograph)).all():
        items.append(
            Item(
                stored_path=photo.file_path,
                folder=_folder_for_photograph(session, photo),
                filename=photograph_name(photo),
            )
        )

    for document in session.scalars(select(Document)).all():
        folder = "Documents"
        if document.site_id is not None:
            site = session.get(Site, document.site_id)
            if site is not None:
                folder = f"Sites/{site_folder(site)}/Documents"
        items.append(
            Item(stored_path=document.file_path, folder=folder, filename=document_name(document))
        )

    items.extend(
        items_for_sheets(session, [batch.id for batch in session.scalars(select(ImportBatch)).all()])
    )
    return items


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------
def _collapse(items: list[Item]) -> list[Item]:
    """Remove folder levels that hold exactly one thing and nothing else.

    ``Sites / TED-A / Photographs / one.jpg`` is fine. ``Projects / Season 1 /
    Photographs`` holding a single picture and nothing beside it is three
    clicks to reach one file, and it is how a filing system becomes something
    people avoid.

    Only the *leaf* level is collapsed, and only when the parent has no other
    children — enough to kill the one-file-in-one-folder chains without
    reorganising anything somebody would have to relearn.
    """
    by_folder: dict[str, list[Item]] = {}
    for item in items:
        by_folder.setdefault(item.folder, []).append(item)

    # A folder is a sole child when no other folder shares its parent prefix.
    result: list[Item] = []
    for folder, group in by_folder.items():
        parent, _, leaf = folder.rpartition("/")
        siblings = [
            other
            for other in by_folder
            if other != folder and (other.rpartition("/")[0] == parent) and parent
        ]
        if len(group) == 1 and parent and not siblings:
            # One file, in a folder nothing else shares. Fold the leaf's name
            # into the filename so the fact is kept and the click is not.
            only = group[0]
            stem, dot, suffix = only.filename.rpartition(".")
            named = f"{stem} - {leaf}.{suffix}" if dot else f"{only.filename} - {leaf}"
            result.append(Item(stored_path=only.stored_path, folder=parent, filename=named))
        else:
            result.extend(group)
    return result


def write(items: list[Item], root: Path, *, collapse: bool = True) -> Written:
    """Copy every item into ``root`` under its readable name."""
    root.mkdir(parents=True, exist_ok=True)
    written = Written(root=root)

    for item in _collapse(items) if collapse else items:
        try:
            source = storage.absolute_path(item.stored_path)
        except Exception:
            # A file the database knows about and the disk does not. Named in
            # the result rather than raised: one missing file is not a reason
            # to refuse the other four hundred.
            written.missing.append(f"{item.folder}/{item.filename}")
            continue

        folder = root / Path(*[part for part in item.folder.split("/") if part])
        folder.mkdir(parents=True, exist_ok=True)
        destination = _unique(folder, item.filename)
        shutil.copy2(source, destination)
        written.files += 1
        written.bytes_written += destination.stat().st_size

    return written


def zip_up(root: Path, destination: Path) -> int:
    """Zip a written folder, returning the size of the archive.

    A zip as well as the folder, not instead of it. Somebody on the same
    machine wants the folder; somebody being sent a link wants one file.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root))
    return destination.stat().st_size


def readme(title: str, note: str | None, written: Written) -> str:
    """A plain-text note inside the folder saying what it is.

    A folder of four hundred files on a disk, with nothing saying where it came
    from or when, is a folder somebody deletes in two years because nobody can
    say what it was.
    """
    lines = [
        title,
        "=" * len(title),
        "",
        f"{written.files} file(s), prepared by Stratum.",
        "",
        "The folders are named after the records these files belong to.",
        "Nothing here is a copy of the archive's only copy - the platform",
        "still holds every one of these files.",
    ]
    if note:
        lines[3:3] = [note, ""]
    if written.missing:
        lines += [
            "",
            "The following were expected and are not on the platform's disk:",
            *(f"  - {name}" for name in written.missing),
        ]
    return "\n".join(lines) + "\n"
