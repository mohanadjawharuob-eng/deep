"""GIS layers and their features.

A *layer* is what the map's layer manager shows and toggles (a trench plan, a
survey grid, a geophysics outline). A *feature* is one geometry inside it,
stored as a real PostGIS geometry so filtering, measuring and bounding-box
queries happen in the database rather than in the browser.
"""

from __future__ import annotations

import uuid

from geoalchemy2 import Geometry
from sqlalchemy import Enum, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, OwnedRecordMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import GeometryKind, LayerCategory


class GisLayer(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    __tablename__ = "gis_layers"

    name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[LayerCategory] = mapped_column(
        Enum(LayerCategory, name="layer_category", values_callable=lambda e: [m.value for m in e]),
        default=LayerCategory.OTHER,
        nullable=False,
        index=True,
    )
    geometry_kind: Mapped[GeometryKind] = mapped_column(
        Enum(GeometryKind, name="geometry_kind", values_callable=lambda e: [m.value for m in e]),
        default=GeometryKind.MIXED,
        nullable=False,
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )

    # --- Rendering -------------------------------------------------------
    #: Leaflet path options: stroke colour, fill, weight, dash. Kept as JSON
    #: so the frontend can extend the style vocabulary without a migration.
    style: Mapped[dict | None] = mapped_column(JSONB)
    opacity: Mapped[float] = mapped_column(Numeric(3, 2), default=1.0, nullable=False)
    z_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_visible_by_default: Mapped[bool] = mapped_column(default=True, nullable=False)
    min_zoom: Mapped[int | None] = mapped_column(Integer)
    max_zoom: Mapped[int | None] = mapped_column(Integer)

    # --- Provenance of the imported data ---------------------------------
    source_format: Mapped[str | None] = mapped_column(String(30))  # geojson, shapefile, kml
    source_filename: Mapped[str | None] = mapped_column(String(300))
    #: CRS the file arrived in; everything is reprojected to EPSG:4326 on import.
    source_crs: Mapped[str | None] = mapped_column(String(50))
    feature_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Cached extent as ``[minx, miny, maxx, maxy]`` so the map can zoom to a
    #: layer without scanning its features.
    bbox: Mapped[dict | None] = mapped_column(JSONB)

    features: Mapped[list[GisFeature]] = relationship(
        back_populates="layer", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_gis_layers_project_site", "project_id", "site_id"),)


class GisFeature(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One geometry within a layer.

    ``geom`` is a generic ``GEOMETRY`` column rather than a typed one because a
    single imported file routinely mixes points, lines and polygons.
    """

    __tablename__ = "gis_features"

    layer_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("gis_layers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str | None] = mapped_column(String(300), index=True)
    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=True), nullable=False
    )
    #: Attribute table row from the source file, preserved as-is.
    properties: Mapped[dict | None] = mapped_column(JSONB)
    style: Mapped[dict | None] = mapped_column(JSONB)

    # Optional links so a trench polygon can point at the context it records.
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sites.id", ondelete="SET NULL"), index=True
    )
    context_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("excavation_contexts.id", ondelete="SET NULL"), index=True
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="SET NULL"), index=True
    )

    layer: Mapped[GisLayer] = relationship(back_populates="features")
