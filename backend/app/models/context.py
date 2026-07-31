"""Excavation contexts and their stratigraphic relationships.

Modelled on single-context recording: every deposit, cut and structure gets a
context number, and the relationships between contexts form a Harris matrix.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
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
from app.models.enums import ContextType, ReviewStatus, StratigraphicRelation

if TYPE_CHECKING:
    from app.models.artifact import Artifact
    from app.models.site import Site


class ExcavationContext(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    __tablename__ = "excavation_contexts"

    site_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: The context number as written on the recording sheet. Kept as text
    #: because sites use schemes like "1042" but also "A/12b".
    context_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    context_type: Mapped[ContextType] = mapped_column(
        Enum(ContextType, name="context_type", values_callable=lambda e: [m.value for m in e]),
        default=ContextType.LAYER,
        nullable=False,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text)
    interpretation: Mapped[str | None] = mapped_column(Text)

    # --- Excavation location ---------------------------------------------
    trench: Mapped[str | None] = mapped_column(String(80), index=True)
    area: Mapped[str | None] = mapped_column(String(80), index=True)
    square: Mapped[str | None] = mapped_column(String(80))
    #: Stratigraphic unit / locus, when the project records one separately.
    stratigraphic_unit: Mapped[str | None] = mapped_column(String(80), index=True)
    phase: Mapped[str | None] = mapped_column(String(80), index=True)

    # --- Physical description --------------------------------------------
    #: Munsell notation, e.g. "10YR 5/3".
    munsell_color: Mapped[str | None] = mapped_column(String(30))
    composition: Mapped[str | None] = mapped_column(String(300))
    compaction: Mapped[str | None] = mapped_column(String(120))
    inclusions: Mapped[str | None] = mapped_column(Text)
    thickness_cm: Mapped[float | None] = mapped_column(Numeric(8, 2))
    length_cm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    width_cm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    depth_cm: Mapped[float | None] = mapped_column(Numeric(10, 2))

    # --- Elevations ------------------------------------------------------
    top_elevation: Mapped[float | None] = mapped_column(Numeric(8, 3))
    bottom_elevation: Mapped[float | None] = mapped_column(Numeric(8, 3))

    # --- Spatial ---------------------------------------------------------
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7))
    geom: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True)
    )
    #: Plan outline of the context, digitised from the site drawing.
    outline: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=True)
    )

    # --- Recording metadata ----------------------------------------------
    excavated_by: Mapped[str | None] = mapped_column(String(300))
    excavation_date: Mapped[date | None] = mapped_column(Date, index=True)
    recorded_by: Mapped[str | None] = mapped_column(String(300))
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("periods.id", ondelete="SET NULL"), index=True
    )
    dating_evidence: Mapped[str | None] = mapped_column(Text)
    date_from: Mapped[int | None] = mapped_column()
    date_to: Mapped[int | None] = mapped_column()
    #: Samples taken from this context (C14, flotation, micromorphology…).
    samples_taken: Mapped[list[str] | None] = mapped_column(ARRAY(String(120)))

    notes: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status", values_callable=lambda e: [m.value for m in e]),
        default=ReviewStatus.APPROVED,
        nullable=False,
        index=True,
    )

    site: Mapped[Site] = relationship()
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="context")
    relationships_from: Mapped[list[ContextRelationship]] = relationship(
        back_populates="context",
        foreign_keys="ContextRelationship.context_id",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("site_id", "context_number", name="uq_excavation_contexts_site_number"),
        Index("ix_excavation_contexts_trench_area", "site_id", "trench", "area"),
        CheckConstraint(
            "top_elevation IS NULL OR bottom_elevation IS NULL "
            "OR top_elevation >= bottom_elevation",
            name="top_above_bottom",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Context {self.context_number}>"


class ContextRelationship(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One edge of the Harris matrix.

    Edges are stored in both directions (A *above* B and B *below* A) so that
    querying a context's relationships never needs a UNION; the service layer
    creates and removes the mirrored row as a pair.
    """

    __tablename__ = "context_relationships"

    context_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("excavation_contexts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    related_context_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("excavation_contexts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation: Mapped[StratigraphicRelation] = mapped_column(
        Enum(
            StratigraphicRelation,
            name="stratigraphic_relation",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    certainty: Mapped[str | None] = mapped_column(String(30))  # certain / probable / possible
    notes: Mapped[str | None] = mapped_column(Text)

    context: Mapped[ExcavationContext] = relationship(
        foreign_keys=[context_id], back_populates="relationships_from"
    )
    related_context: Mapped[ExcavationContext] = relationship(foreign_keys=[related_context_id])

    __table_args__ = (
        UniqueConstraint(
            "context_id", "related_context_id", "relation", name="uq_context_relationships_edge"
        ),
        CheckConstraint("context_id <> related_context_id", name="no_self_relation"),
    )
