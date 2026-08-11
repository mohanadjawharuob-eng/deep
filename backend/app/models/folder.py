"""Folders: somewhere to put things, made by the people who use the platform.

Distinct from :class:`~app.models.media.MediaFolder`, and the difference is
worth stating because the names are close. A ``MediaFolder`` is a **note about
material that is not here** — four hundred gigabytes of raw frames on a drive
in a cupboard, recorded so the catalogue does not read as complete when it is
not. A ``Folder`` is **in here**: a drawer holding photographs and documents
that the platform actually has.

Two decisions.

**One folder per file, not many.** A photograph in three folders is a
photograph nobody can file, because "where is it" stops having an answer and
removing it from one place leaves it in two others. A file's folder is where
somebody put it, and moving it moves it.

**The tree is not the archive.** Every photograph still belongs to a record —
a site, a find, an object — and that link is what permissions are decided by
and what survives the folders being reorganised. Folders are for finding
things by hand; the record link is for everything else. Deleting a folder
therefore deletes no files: they return to being unfiled.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, OwnedRecordMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import FolderKind

if TYPE_CHECKING:
    pass


class Folder(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    __tablename__ = "folders"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("folders.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[FolderKind] = mapped_column(
        Enum(FolderKind, name="folder_kind", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=FolderKind.GENERAL,
        index=True,
    )
    note: Mapped[str | None] = mapped_column(Text)

    # `remote_side` on the *parent* side is what tells SQLAlchemy which end of
    # a self-reference is the "one": without it both ends look one-to-many and
    # the mapper refuses to build at all.
    parent: Mapped[Folder | None] = relationship(
        "Folder", remote_side="Folder.id", back_populates="children"
    )
    children: Mapped[list[Folder]] = relationship(
        "Folder", back_populates="parent", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Two folders called "Trench A" inside one parent is a filing system
        # that has stopped working. Two at the top level is the same mistake,
        # and a plain UNIQUE does not catch it because NULL is not equal to
        # NULL — hence the second, partial index.
        UniqueConstraint("parent_id", "name", name="uq_folders_sibling_name"),
        Index(
            "uq_folders_root_name",
            "name",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
    )
