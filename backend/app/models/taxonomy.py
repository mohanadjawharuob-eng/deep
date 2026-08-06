"""Controlled vocabularies: periods, materials and object categories.

These are tables rather than enums because every region and tradition names
its own chronology, and the administration panel must let curators extend the
lists without a code change.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, OwnedRecordMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ReferenceType


class Period(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A chronological period, optionally nested (Bronze Age → Early Bronze).

    Years are signed integers where negative means BCE, which keeps range
    queries ("everything before 500 BCE") a plain integer comparison.
    """

    __tablename__ = "periods"

    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(150), nullable=False, unique=True, index=True)
    abbreviation: Mapped[str | None] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(Text)
    start_year: Mapped[int | None] = mapped_column(Integer, index=True)
    end_year: Mapped[int | None] = mapped_column(Integer, index=True)
    #: Region the chronology applies to; the same label means different dates
    #: in the Levant and in Scandinavia.
    region: Mapped[str | None] = mapped_column(String(150), index=True)
    #: Colour used for map and timeline rendering, ``#RRGGBB``.
    color: Mapped[str | None] = mapped_column(String(7))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("periods.id", ondelete="SET NULL"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    parent: Mapped[Period | None] = relationship(remote_side="Period.id", back_populates="children")
    children: Mapped[list[Period]] = relationship(back_populates="parent")

    __table_args__ = (Index("ix_periods_year_range", "start_year", "end_year"),)


class Material(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Artifact material (ceramic, bronze, obsidian, …), optionally nested."""

    __tablename__ = "materials"

    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(150), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    #: Coarse grouping used for filtering: stone, metal, organic, ceramic…
    group: Mapped[str | None] = mapped_column(String(80), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("materials.id", ondelete="SET NULL"), index=True
    )

    parent: Mapped[Material | None] = relationship(
        remote_side="Material.id", back_populates="children"
    )
    children: Mapped[list[Material]] = relationship(back_populates="parent")


class ObjectCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Typological category of an object (vessel → amphora → Dressel 1)."""

    __tablename__ = "object_categories"

    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(150), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("object_categories.id", ondelete="SET NULL"), index=True
    )

    parent: Mapped[ObjectCategory | None] = relationship(
        remote_side="ObjectCategory.id", back_populates="children"
    )
    children: Mapped[list[ObjectCategory]] = relationship(back_populates="parent")


class Publication(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """A bibliographic reference: the record at the centre of the library.

    Already existed, and finds already cite it, so it is extended rather than
    replaced — every citation recorded before the library was built lands *in*
    the library rather than beside it.

    The fields beyond the original handful are the ones a reference manager
    needs to hold an archaeologist's bibliography rather than a scientist's:
    grey literature, ministry archives, and site reports that have an editor and
    a series but no journal.
    """

    __tablename__ = "publications"

    reference_type: Mapped[ReferenceType] = mapped_column(
        Enum(ReferenceType, name="reference_type", values_callable=lambda e: [m.value for m in e]),
        default=ReferenceType.ARTICLE,
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    #: Kept as one string rather than a table of people. Every reference manager
    #: that split it has had to hold "Ministry of Antiquities" and "et al." in a
    #: surname column anyway, and the citation is written from this either way.
    authors: Mapped[str | None] = mapped_column(String(500))
    editors: Mapped[str | None] = mapped_column(String(500))
    year: Mapped[int | None] = mapped_column(Integer, index=True)

    publisher: Mapped[str | None] = mapped_column(String(300))
    #: Journal, or the book a chapter is in, or the archive holding a file.
    journal: Mapped[str | None] = mapped_column(String(300))
    series: Mapped[str | None] = mapped_column(String(300))
    volume: Mapped[str | None] = mapped_column(String(50))
    issue: Mapped[str | None] = mapped_column(String(50))
    pages: Mapped[str | None] = mapped_column(String(50))
    edition: Mapped[str | None] = mapped_column(String(50))
    place: Mapped[str | None] = mapped_column(String(200))
    institution: Mapped[str | None] = mapped_column(String(300))
    language: Mapped[str | None] = mapped_column(String(80))

    doi: Mapped[str | None] = mapped_column(String(200), index=True)
    isbn: Mapped[str | None] = mapped_column(String(20))
    url: Mapped[str | None] = mapped_column(String(1000))
    #: When a web page was read, which is the only thing that makes citing one
    #: honest.
    accessed_on: Mapped[date | None] = mapped_column(Date)

    abstract: Mapped[str | None] = mapped_column(Text)
    #: Whatever the reader wants to remember about it. Zotero's notes, and the
    #: field people use most.
    notes: Mapped[str | None] = mapped_column(Text)
    #: The rendered citation, when somebody has one they prefer to the
    #: platform's. Left alone if set.
    citation: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String(80)))

    #: The BibTeX key, so a reference imported from a .bib round-trips back to
    #: the same key and somebody's LaTeX keeps compiling.
    citation_key: Mapped[str | None] = mapped_column(String(120), index=True)

    collections: Mapped[list[LibraryCollection]] = relationship(  # noqa: F821
        secondary="library_collection_items", backref="publications", lazy="selectin"
    )

    __table_args__ = (UniqueConstraint("doi", name="uq_publications_doi"),)


class SystemSetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Key/value settings editable from the administration panel."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    value: Mapped[str | None] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(20), default="string", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    #: Settings readable without authentication (site title, map defaults).
    is_public: Mapped[bool] = mapped_column(default=False, nullable=False)
