"""Projects — the top-level container for excavations and surveys."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, OwnedRecordMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ProjectRole, ProjectStatus

if TYPE_CHECKING:
    from app.models.site import Site
    from app.models.user import User


class Project(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    #: Short human code used in inventory numbers, e.g. ``TELL-2024``.
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    project_type: Mapped[str | None] = mapped_column(String(60))  # excavation, survey, …

    principal_investigator: Mapped[str | None] = mapped_column(String(200))
    principal_investigator_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    institution: Mapped[str | None] = mapped_column(String(300), index=True)
    partner_institutions: Mapped[list[str] | None] = mapped_column(ARRAY(String(300)))

    country: Mapped[str | None] = mapped_column(String(100), index=True)
    region: Mapped[str | None] = mapped_column(String(200), index=True)
    #: Representative coordinate for the project as a whole; individual sites
    #: carry their own PostGIS geometry.
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7))

    start_date: Mapped[date | None] = mapped_column(Date, index=True)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status", values_callable=lambda e: [m.value for m in e]),
        default=ProjectStatus.PLANNED,
        nullable=False,
        index=True,
    )

    funding_source: Mapped[str | None] = mapped_column(String(300))
    funding_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    funding_currency: Mapped[str | None] = mapped_column(String(3))
    permit_number: Mapped[str | None] = mapped_column(String(120))
    permit_authority: Mapped[str | None] = mapped_column(String(300))

    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String(80)))
    #: Escape hatch for institution-specific fields; queryable via JSONB.
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    #: Stable public token embedded in the QR code, so a printed label keeps
    #: working even if the record is renamed or its code changes.
    public_token: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True, default=lambda: uuid.uuid4().hex
    )

    owner: Mapped[User | None] = relationship(foreign_keys="Project.owner_id")
    principal_investigator_user: Mapped[User | None] = relationship(
        foreign_keys="Project.principal_investigator_id"
    )
    memberships: Mapped[list[ProjectMembership]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    sites: Mapped[list[Site]] = relationship(back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_projects_status_public", "status", "is_public"),
        Index("ix_projects_country_region", "country", "region"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Project {self.code}>"


class ProjectMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Team membership: who works on a project and in what capacity.

    A user's *global* role caps what they may ever do; the project role decides
    what they may do here. Both are checked, and the more restrictive wins.
    """

    __tablename__ = "project_memberships"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ProjectRole] = mapped_column(
        Enum(ProjectRole, name="project_role", values_callable=lambda e: [m.value for m in e]),
        default=ProjectRole.STUDENT,
        nullable=False,
    )
    #: Free-text job title shown on the team page ("ceramics specialist").
    title: Mapped[str | None] = mapped_column(String(150))
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    project: Mapped[Project] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(foreign_keys=[user_id], back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_memberships_member"),
        Index("ix_project_memberships_user", "user_id", "project_id"),
    )
