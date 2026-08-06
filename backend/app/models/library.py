"""The library: references, the folders they sit in, and what they are about.

The bibliography is the one part of an excavation that already lives in a
reference manager, and asking somebody to keep a second one is asking them to
keep neither. So this is shaped like the tool they already use — folders that a
reference can be in several of at once, tags, notes, an attached PDF, BibTeX in
and out — with one addition that a reference manager cannot have:

**A reference can be attached to the thing it is about.** Not to a project as a
whole, but to *this site*, *this context*, *this object*, at *these pages*. That
is the entire reason for building it here rather than telling somebody to use
Zotero: an excavation report cited against a site is a bibliography, and the
same report cited against context 1042 at pages 88-91 is a finding aid. The
second is what somebody re-opening the archive in ten years actually needs.

The reference itself is :class:`app.models.taxonomy.Publication`, which already
existed and which finds already cite. It is extended rather than replaced, so
every citation already recorded lands in the library rather than beside it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, OwnedRecordMixin, TimestampMixin, UUIDPrimaryKeyMixin

#: Which references are in which folder.
#:
#: Many-to-many, like Zotero and unlike a filesystem: the same report is "Tell
#: el-Demo" and "Nabataean pottery" and "to read", and forcing a choice between
#: them is what makes people stop filing things.
library_collection_items = Table(
    "library_collection_items",
    Base.metadata,
    Column(
        "collection_id",
        PGUUID(as_uuid=True),
        ForeignKey("library_collections.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "publication_id",
        PGUUID(as_uuid=True),
        ForeignKey("publications.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class LibraryCollection(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """A named folder of references, which may contain other folders."""

    __tablename__ = "library_collections"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("library_collections.id", ondelete="CASCADE"), index=True
    )

    parent: Mapped[LibraryCollection | None] = relationship(
        remote_side="LibraryCollection.id", back_populates="children"
    )
    children: Mapped[list[LibraryCollection]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Two folders with the same name under the same parent is a filing
        # system nobody can navigate, and the second one always ends up empty.
        UniqueConstraint("parent_id", "name", name="uq_library_collections_sibling_name"),
        # And the same rule at the top level, which the constraint above does
        # *not* enforce: `parent_id` is NULL there, and in SQL two NULLs are not
        # equal, so a plain unique constraint lets every top-level duplicate
        # through. The partial index is the only thing that catches the case
        # people actually hit — the top of the tree is where folders are made.
        Index(
            "uq_library_collections_root_name",
            "name",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
    )


class ReferenceLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """What a reference is about — and where in it.

    The ``locator`` is the point. "Smith 1987 is about this site" is a
    bibliography entry; "Smith 1987, 88-91, describes context 1042" is the
    sentence somebody actually needed, and it is the one that is never written
    down because there has been nowhere to write it.
    """

    __tablename__ = "reference_links"

    publication_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("publications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    context_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("excavation_contexts.id", ondelete="CASCADE"), index=True
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    museum_object_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("museum_objects.id", ondelete="CASCADE"), index=True
    )

    #: "88-91", "fig. 14", "pl. IIIa". Free text, because a locator is whatever
    #: the publication numbers itself by, and a page-number column would refuse
    #: half of them.
    locator: Mapped[str | None] = mapped_column(String(120))
    #: Why this reference matters to this record: "first publication",
    #: "reinterprets the sequence", "the parallel".
    note: Mapped[str | None] = mapped_column(Text)

    publication: Mapped[Publication] = relationship()  # noqa: F821

    __table_args__ = (
        Index("ix_reference_links_targets", "site_id", "artifact_id", "museum_object_id"),
    )
