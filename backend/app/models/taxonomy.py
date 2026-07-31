"""Controlled vocabularies: periods, materials and object categories.

These are tables rather than enums because every region and tradition names
its own chronology, and the administration panel must let curators extend the
lists without a code change.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


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


class Publication(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A bibliographic reference that records can cite."""

    __tablename__ = "publications"

    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    authors: Mapped[str | None] = mapped_column(String(500))
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    publisher: Mapped[str | None] = mapped_column(String(300))
    journal: Mapped[str | None] = mapped_column(String(300))
    volume: Mapped[str | None] = mapped_column(String(50))
    pages: Mapped[str | None] = mapped_column(String(50))
    doi: Mapped[str | None] = mapped_column(String(200), index=True)
    isbn: Mapped[str | None] = mapped_column(String(20))
    url: Mapped[str | None] = mapped_column(String(1000))
    abstract: Mapped[str | None] = mapped_column(Text)
    citation: Mapped[str | None] = mapped_column(Text)

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
