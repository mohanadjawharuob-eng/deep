"""Artifact schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.models.enums import ConditionState, ConservationStatus, ReviewStatus
from app.schemas.common import ORMModel


class ArtifactBase(BaseModel):
    name: str | None = Field(default=None, max_length=300)
    field_number: str | None = Field(default=None, max_length=100)
    accession_number: str | None = Field(default=None, max_length=100)

    object_type: str | None = Field(default=None, max_length=200)
    category_id: uuid.UUID | None = None
    typology: str | None = Field(default=None, max_length=200)
    description: str | None = None

    material_id: uuid.UUID | None = None
    material_text: str | None = Field(default=None, max_length=200)
    technique: str | None = Field(default=None, max_length=200)
    decoration: str | None = None
    inscription: str | None = None

    # Measurements are millimetres and grams throughout, so the unit is never
    # ambiguous and integer arithmetic stays exact.
    length_mm: float | None = Field(default=None, ge=0)
    width_mm: float | None = Field(default=None, ge=0)
    height_mm: float | None = Field(default=None, ge=0)
    thickness_mm: float | None = Field(default=None, ge=0)
    diameter_mm: float | None = Field(default=None, ge=0)
    rim_diameter_mm: float | None = Field(default=None, ge=0)
    weight_g: float | None = Field(default=None, ge=0)
    dimensions_extra: dict[str, Any] | None = None
    quantity: int = Field(default=1, ge=1)
    is_fragment: bool = False

    period_id: uuid.UUID | None = None
    period_text: str | None = Field(default=None, max_length=200)
    dating_method: str | None = Field(default=None, max_length=200)
    date_from: int | None = Field(default=None, description="Negative is BCE")
    date_to: int | None = None

    context_id: uuid.UUID | None = None
    stratigraphic_unit: str | None = Field(default=None, max_length=80)
    trench: str | None = Field(default=None, max_length=80)
    square: str | None = Field(default=None, max_length=80)
    depth_cm: float | None = None
    elevation: float | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    find_date: date | None = None
    found_by: str | None = Field(default=None, max_length=300)
    recovery_method: str | None = Field(default=None, max_length=120)

    condition: ConditionState = ConditionState.UNKNOWN
    conservation_status: ConservationStatus = ConservationStatus.UNKNOWN
    conservation_notes: str | None = None
    current_location: str | None = Field(default=None, max_length=300)
    storage_box: str | None = Field(default=None, max_length=120)
    is_on_display: bool = False
    loan_status: str | None = Field(default=None, max_length=120)

    research_notes: str | None = None
    keywords: list[str] | None = None
    barcode: str | None = Field(default=None, max_length=120)
    metadata_json: dict[str, Any] | None = None
    is_public: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> ArtifactBase:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_to < self.date_from
        ):
            raise ValueError("date_to cannot be earlier than date_from")
        return self


class ArtifactCreate(ArtifactBase):
    site_id: uuid.UUID
    inventory_number: str = Field(
        min_length=1, max_length=100, description="Unique within the site"
    )


class ArtifactUpdate(BaseModel):
    inventory_number: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, max_length=300)
    field_number: str | None = Field(default=None, max_length=100)
    accession_number: str | None = Field(default=None, max_length=100)
    object_type: str | None = Field(default=None, max_length=200)
    category_id: uuid.UUID | None = None
    typology: str | None = Field(default=None, max_length=200)
    description: str | None = None
    material_id: uuid.UUID | None = None
    material_text: str | None = Field(default=None, max_length=200)
    technique: str | None = Field(default=None, max_length=200)
    decoration: str | None = None
    inscription: str | None = None
    length_mm: float | None = Field(default=None, ge=0)
    width_mm: float | None = Field(default=None, ge=0)
    height_mm: float | None = Field(default=None, ge=0)
    thickness_mm: float | None = Field(default=None, ge=0)
    diameter_mm: float | None = Field(default=None, ge=0)
    rim_diameter_mm: float | None = Field(default=None, ge=0)
    weight_g: float | None = Field(default=None, ge=0)
    dimensions_extra: dict[str, Any] | None = None
    quantity: int | None = Field(default=None, ge=1)
    is_fragment: bool | None = None
    period_id: uuid.UUID | None = None
    period_text: str | None = Field(default=None, max_length=200)
    dating_method: str | None = Field(default=None, max_length=200)
    date_from: int | None = None
    date_to: int | None = None
    context_id: uuid.UUID | None = None
    stratigraphic_unit: str | None = Field(default=None, max_length=80)
    trench: str | None = Field(default=None, max_length=80)
    square: str | None = Field(default=None, max_length=80)
    depth_cm: float | None = None
    elevation: float | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    find_date: date | None = None
    found_by: str | None = Field(default=None, max_length=300)
    recovery_method: str | None = Field(default=None, max_length=120)
    condition: ConditionState | None = None
    conservation_status: ConservationStatus | None = None
    conservation_notes: str | None = None
    current_location: str | None = Field(default=None, max_length=300)
    storage_box: str | None = Field(default=None, max_length=120)
    is_on_display: bool | None = None
    loan_status: str | None = Field(default=None, max_length=120)
    research_notes: str | None = None
    keywords: list[str] | None = None
    barcode: str | None = Field(default=None, max_length=120)
    metadata_json: dict[str, Any] | None = None
    is_public: bool | None = None


class ArtifactSummary(ORMModel):
    id: uuid.UUID
    site_id: uuid.UUID
    context_id: uuid.UUID | None = None
    inventory_number: str
    field_number: str | None = None
    name: str | None = None
    object_type: str | None = None
    material_id: uuid.UUID | None = None
    material_text: str | None = None
    period_id: uuid.UUID | None = None
    period_text: str | None = None
    date_from: int | None = None
    date_to: int | None = None
    condition: ConditionState
    conservation_status: ConservationStatus
    current_location: str | None = None
    review_status: ReviewStatus
    is_public: bool


class ArtifactRead(ArtifactSummary):
    accession_number: str | None = None
    category_id: uuid.UUID | None = None
    typology: str | None = None
    description: str | None = None
    technique: str | None = None
    decoration: str | None = None
    inscription: str | None = None
    length_mm: float | None = None
    width_mm: float | None = None
    height_mm: float | None = None
    thickness_mm: float | None = None
    diameter_mm: float | None = None
    rim_diameter_mm: float | None = None
    weight_g: float | None = None
    dimensions_extra: dict[str, Any] | None = None
    quantity: int
    is_fragment: bool
    dating_method: str | None = None
    stratigraphic_unit: str | None = None
    trench: str | None = None
    square: str | None = None
    depth_cm: float | None = None
    elevation: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    find_date: date | None = None
    found_by: str | None = None
    recovery_method: str | None = None
    conservation_notes: str | None = None
    storage_box: str | None = None
    is_on_display: bool
    loan_status: str | None = None
    research_notes: str | None = None
    keywords: list[str] | None = None
    barcode: str | None = None
    #: Stable token embedded in the printed QR label. Survives renumbering.
    public_token: str
    metadata_json: dict[str, Any] | None = None
    owner_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class ArtifactDetail(ArtifactRead):
    can_edit: bool = False
    can_delete: bool = False
