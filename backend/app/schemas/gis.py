"""Schemas for GIS layers, features and spatial search."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import GeometryKind, LayerCategory, ResourceType
from app.schemas.common import ORMModel


class LayerBase(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str | None = None
    category: LayerCategory = LayerCategory.OTHER
    geometry_kind: GeometryKind = GeometryKind.MIXED
    style: dict[str, Any] | None = Field(
        default=None,
        description="Leaflet path options: colour, weight, fillColor, dashArray",
        examples=[{"color": "#c2703d", "weight": 2, "fillOpacity": 0.25}],
    )
    opacity: float = Field(default=1.0, ge=0, le=1)
    z_index: int = 0
    is_visible_by_default: bool = True
    min_zoom: int | None = Field(default=None, ge=0, le=24)
    max_zoom: int | None = Field(default=None, ge=0, le=24)
    is_public: bool = False


class LayerCreate(LayerBase):
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _needs_a_parent(self) -> LayerCreate:
        if self.project_id is None and self.site_id is None:
            raise ValueError(
                "Attach the layer to a project or a site — an unattached layer "
                "cannot be found again or permission-checked"
            )
        return self

    @model_validator(mode="after")
    def _zoom_range(self) -> LayerCreate:
        both_set = self.min_zoom is not None and self.max_zoom is not None
        if both_set and self.min_zoom > self.max_zoom:
            raise ValueError("min_zoom cannot be greater than max_zoom")
        return self


class LayerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    category: LayerCategory | None = None
    geometry_kind: GeometryKind | None = None
    style: dict[str, Any] | None = None
    opacity: float | None = Field(default=None, ge=0, le=1)
    z_index: int | None = None
    is_visible_by_default: bool | None = None
    min_zoom: int | None = Field(default=None, ge=0, le=24)
    max_zoom: int | None = Field(default=None, ge=0, le=24)
    is_public: bool | None = None


class LayerSummary(ORMModel):
    id: uuid.UUID
    name: str
    category: LayerCategory
    geometry_kind: GeometryKind
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    feature_count: int
    #: ``[minLon, minLat, maxLon, maxLat]``, so a map can zoom to the layer
    #: without fetching a single feature.
    bbox: list[float] | None = None
    style: dict[str, Any] | None = None
    opacity: float
    z_index: int
    is_visible_by_default: bool
    min_zoom: int | None = None
    max_zoom: int | None = None
    is_public: bool
    created_at: datetime


class LayerRead(LayerSummary):
    description: str | None = None
    source_format: str | None = None
    source_filename: str | None = None
    source_crs: str | None = None
    owner_id: uuid.UUID | None = None
    updated_at: datetime


class LayerDetail(LayerRead):
    can_edit: bool = False
    can_delete: bool = False


class FeatureCreate(BaseModel):
    """One feature, in GeoJSON terms."""

    geometry: dict[str, Any] = Field(
        description="A GeoJSON geometry object",
        examples=[{"type": "Point", "coordinates": [35.85, 32.5556]}],
    )
    name: str | None = Field(default=None, max_length=300)
    properties: dict[str, Any] | None = None
    style: dict[str, Any] | None = None
    site_id: uuid.UUID | None = None
    context_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    source_srid: int | None = Field(
        default=None,
        description=(
            "EPSG code the coordinates are in. Omit only if they are already "
            "longitude/latitude — a projected coordinate sent without this is "
            "refused rather than misplaced."
        ),
        examples=[32636],
    )


class FeatureUpdate(BaseModel):
    geometry: dict[str, Any] | None = None
    name: str | None = Field(default=None, max_length=300)
    properties: dict[str, Any] | None = None
    style: dict[str, Any] | None = None
    site_id: uuid.UUID | None = None
    context_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    source_srid: int | None = None


class FeatureRead(BaseModel):
    """A feature as GeoJSON, which is what a map consumes."""

    type: Literal["Feature"] = "Feature"
    id: uuid.UUID
    geometry: dict[str, Any]
    properties: dict[str, Any]


class FeatureCollection(BaseModel):
    """A GeoJSON FeatureCollection.

    Deliberately the literal GeoJSON shape rather than a paginated envelope:
    this is handed straight to Leaflet, and wrapping it would mean every
    client unwraps it again.
    """

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[FeatureRead]
    #: Extras outside the GeoJSON specification but permitted by it.
    name: str | None = None
    bbox: list[float] | None = None
    total: int | None = None


class ImportResult(BaseModel):
    layer: LayerDetail
    imported: int
    skipped: int = 0
    source_format: str
    source_crs: str | None = None
    #: What the coordinates were reprojected from, when they were.
    reprojected_from_srid: int | None = None
    warnings: list[str] = []


class SpatialHit(BaseModel):
    """One record found by a spatial query, whatever kind of record it is."""

    resource_type: ResourceType
    id: uuid.UUID
    label: str
    latitude: float | None = None
    longitude: float | None = None
    #: Present when the query had a centre to measure from.
    distance_m: float | None = None
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    is_approximate: bool = Field(
        default=False,
        description=(
            "True when the coordinates have been blurred because the site's "
            "location is restricted."
        ),
    )


class SpatialSearchResult(BaseModel):
    items: list[SpatialHit]
    total: int
    limit: int
    offset: int
    #: Echoed back so a client can show what was actually searched.
    centre: list[float] | None = None
    radius_m: float | None = None
    bbox: list[float] | None = None
