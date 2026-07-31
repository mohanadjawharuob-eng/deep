"""Archaeological sites belonging to a project."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from geoalchemy2 import Geometry
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
from app.models.enums import ConditionState, ProtectionStatus, ReviewStatus, SiteType

if TYPE_CHECKING:
    from app.models.artifact import Artifact
    from app.models.project import Project


class Site(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    __tablename__ = "sites"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    #: Toponyms differ by language and era; kept as an array so all of them
    #: are searchable, not just the accepted form.
    alternative_names: Mapped[list[str] | None] = mapped_column(ARRAY(String(300)))
    code: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    site_type: Mapped[SiteType] = mapped_column(
        Enum(SiteType, name="site_type", values_callable=lambda e: [m.value for m in e]),
        default=SiteType.OTHER,
        nullable=False,
        index=True,
    )

    # --- Location -------------------------------------------------------
    # Decimal degrees are stored alongside the PostGIS point: the plain columns
    # are what forms, exports and CSV round-trips use, while ``geom`` is what
    # spatial queries and the map hit. The service layer keeps them in sync.
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7), index=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7), index=True)
    geom: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True)
    )
    #: Site extent, when surveyed, as a polygon.
    boundary: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=True)
    )
    elevation: Mapped[float | None] = mapped_column(Numeric(8, 2))
    #: Positional accuracy of the coordinate in metres.
    location_accuracy_m: Mapped[float | None] = mapped_column(Numeric(8, 2))
    #: Sensitive sites (looting risk) publish a blurred coordinate only.
    location_restricted: Mapped[bool] = mapped_column(default=False, nullable=False)

    # --- Administrative geography ---------------------------------------
    country: Mapped[str | None] = mapped_column(String(100), index=True)
    region: Mapped[str | None] = mapped_column(String(200), index=True)
    district: Mapped[str | None] = mapped_column(String(200))
    municipality: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(400))
    #: National heritage register identifier, when the site has one.
    national_register_id: Mapped[str | None] = mapped_column(String(120), index=True)

    # --- Chronology ------------------------------------------------------
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("periods.id", ondelete="SET NULL"), index=True
    )
    #: Free-text chronology when the controlled vocabulary does not fit.
    period_text: Mapped[str | None] = mapped_column(String(300))
    dating_method: Mapped[str | None] = mapped_column(String(200))
    date_from: Mapped[int | None] = mapped_column(index=True)  # signed year, BCE negative
    date_to: Mapped[int | None] = mapped_column(index=True)

    # --- Heritage management ---------------------------------------------
    protection_status: Mapped[ProtectionStatus] = mapped_column(
        Enum(
            ProtectionStatus,
            name="protection_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=ProtectionStatus.UNKNOWN,
        nullable=False,
        index=True,
    )
    condition: Mapped[ConditionState] = mapped_column(
        Enum(
            ConditionState, name="condition_state", values_callable=lambda e: [m.value for m in e]
        ),
        default=ConditionState.UNKNOWN,
        nullable=False,
    )
    threats: Mapped[list[str] | None] = mapped_column(ARRAY(String(120)))
    land_use: Mapped[str | None] = mapped_column(String(200))
    landowner: Mapped[str | None] = mapped_column(String(300))

    discovery_date: Mapped[date | None] = mapped_column(Date)
    discovered_by: Mapped[str | None] = mapped_column(String(300))
    excavation_start: Mapped[date | None] = mapped_column(Date)
    excavation_end: Mapped[date | None] = mapped_column(Date)

    references: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String(80)))
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status", values_callable=lambda e: [m.value for m in e]),
        default=ReviewStatus.APPROVED,
        nullable=False,
        index=True,
    )

    project: Mapped[Project] = relationship(back_populates="sites")
    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="site", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Site codes are unique per project, not globally: two projects may
        # each have a "TR-01".
        UniqueConstraint("project_id", "code", name="uq_sites_project_code"),
        Index("ix_sites_date_range", "date_from", "date_to"),
        Index("ix_sites_project_public", "project_id", "is_public"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Site {self.code} {self.name}>"
