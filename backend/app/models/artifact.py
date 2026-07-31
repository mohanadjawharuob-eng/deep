"""Artifacts (small finds) recovered from a site."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from geoalchemy2 import Geometry
from sqlalchemy import (
    Column,
    Date,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, OwnedRecordMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ConditionState, ConservationStatus, ReviewStatus

if TYPE_CHECKING:
    from app.models.context import ExcavationContext
    from app.models.site import Site
    from app.models.taxonomy import Material, ObjectCategory, Publication


#: Artifacts cite publications and publications cover many artifacts.
artifact_publications = Table(
    "artifact_publications",
    Base.metadata,
    Column(
        "artifact_id",
        PGUUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "publication_id",
        PGUUID(as_uuid=True),
        ForeignKey("publications.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

#: Secondary materials, for composite objects (a bronze knife with a bone handle).
artifact_materials = Table(
    "artifact_materials",
    Base.metadata,
    Column(
        "artifact_id",
        PGUUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "material_id",
        PGUUID(as_uuid=True),
        ForeignKey("materials.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Artifact(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    __tablename__ = "artifacts"

    site_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    context_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("excavation_contexts.id", ondelete="SET NULL"), index=True
    )

    #: Museum/inventory number — the identifier humans quote. Unique per site.
    inventory_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    #: Field/small-find number assigned during excavation.
    field_number: Mapped[str | None] = mapped_column(String(100), index=True)
    accession_number: Mapped[str | None] = mapped_column(String(100))

    name: Mapped[str | None] = mapped_column(String(300), index=True)
    object_type: Mapped[str | None] = mapped_column(String(200), index=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("object_categories.id", ondelete="SET NULL"), index=True
    )
    typology: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)

    # --- Material and technique ------------------------------------------
    material_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("materials.id", ondelete="SET NULL"), index=True
    )
    material_text: Mapped[str | None] = mapped_column(String(200))
    technique: Mapped[str | None] = mapped_column(String(200))
    decoration: Mapped[str | None] = mapped_column(Text)
    inscription: Mapped[str | None] = mapped_column(Text)

    # --- Measurements (millimetres and grams, so integers stay exact) ------
    length_mm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    width_mm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    height_mm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    thickness_mm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    diameter_mm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    rim_diameter_mm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    weight_g: Mapped[float | None] = mapped_column(Numeric(12, 3))
    #: Anything the fixed columns cannot express, e.g. {"blade_length_mm": 82}.
    dimensions_extra: Mapped[dict | None] = mapped_column(JSONB)
    quantity: Mapped[int] = mapped_column(default=1, nullable=False)
    is_fragment: Mapped[bool] = mapped_column(default=False, nullable=False)

    # --- Chronology ------------------------------------------------------
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("periods.id", ondelete="SET NULL"), index=True
    )
    period_text: Mapped[str | None] = mapped_column(String(200))
    dating_method: Mapped[str | None] = mapped_column(String(200))
    date_from: Mapped[int | None] = mapped_column(index=True)
    date_to: Mapped[int | None] = mapped_column(index=True)

    # --- Find location ----------------------------------------------------
    stratigraphic_unit: Mapped[str | None] = mapped_column(String(80), index=True)
    trench: Mapped[str | None] = mapped_column(String(80), index=True)
    square: Mapped[str | None] = mapped_column(String(80))
    depth_cm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    elevation: Mapped[float | None] = mapped_column(Numeric(8, 3))
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7))
    geom: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True)
    )
    find_date: Mapped[date | None] = mapped_column(Date)
    found_by: Mapped[str | None] = mapped_column(String(300))
    #: Recovery method: hand excavation, dry sieving, flotation…
    recovery_method: Mapped[str | None] = mapped_column(String(120))

    # --- Curation ---------------------------------------------------------
    condition: Mapped[ConditionState] = mapped_column(
        Enum(
            ConditionState, name="condition_state", values_callable=lambda e: [m.value for m in e]
        ),
        default=ConditionState.UNKNOWN,
        nullable=False,
    )
    conservation_status: Mapped[ConservationStatus] = mapped_column(
        Enum(
            ConservationStatus,
            name="conservation_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=ConservationStatus.UNKNOWN,
        nullable=False,
        index=True,
    )
    conservation_notes: Mapped[str | None] = mapped_column(Text)
    current_location: Mapped[str | None] = mapped_column(String(300), index=True)
    storage_box: Mapped[str | None] = mapped_column(String(120))
    is_on_display: Mapped[bool] = mapped_column(default=False, nullable=False)
    #: Set when the object has left the store (loan, analysis, repatriation).
    loan_status: Mapped[str | None] = mapped_column(String(120))

    research_notes: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String(80)))
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    # --- Identifiers ------------------------------------------------------
    #: Stable public token embedded in the QR code, so a printed label keeps
    #: working even if the record is later made private or renumbered.
    public_token: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True, default=lambda: uuid.uuid4().hex
    )
    qr_code_path: Mapped[str | None] = mapped_column(String(500))
    barcode: Mapped[str | None] = mapped_column(String(120), index=True)

    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status", values_callable=lambda e: [m.value for m in e]),
        default=ReviewStatus.APPROVED,
        nullable=False,
        index=True,
    )

    site: Mapped[Site] = relationship(back_populates="artifacts")
    context: Mapped[ExcavationContext | None] = relationship(back_populates="artifacts")
    material: Mapped[Material | None] = relationship(foreign_keys=[material_id])
    category: Mapped[ObjectCategory | None] = relationship()
    secondary_materials: Mapped[list[Material]] = relationship(secondary=artifact_materials)
    publications: Mapped[list[Publication]] = relationship(secondary=artifact_publications)

    __table_args__ = (
        UniqueConstraint("site_id", "inventory_number", name="uq_artifacts_site_inventory"),
        Index("ix_artifacts_date_range", "date_from", "date_to"),
        Index("ix_artifacts_site_review", "site_id", "review_status"),
        Index("ix_artifacts_material_period", "material_id", "period_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Artifact {self.inventory_number}>"
