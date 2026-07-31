"""Excavation context schemas, including stratigraphic relationships."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.models.enums import ContextType, ReviewStatus, StratigraphicRelation
from app.schemas.common import ORMModel


class ContextBase(BaseModel):
    context_type: ContextType = ContextType.LAYER
    description: str | None = None
    interpretation: str | None = None

    trench: str | None = Field(default=None, max_length=80)
    area: str | None = Field(default=None, max_length=80)
    square: str | None = Field(default=None, max_length=80)
    stratigraphic_unit: str | None = Field(default=None, max_length=80)
    phase: str | None = Field(default=None, max_length=80)

    munsell_color: str | None = Field(
        default=None, max_length=30, description='Munsell notation, e.g. "10YR 5/3"'
    )
    composition: str | None = Field(default=None, max_length=300)
    compaction: str | None = Field(default=None, max_length=120)
    inclusions: str | None = None
    thickness_cm: float | None = Field(default=None, ge=0)
    length_cm: float | None = Field(default=None, ge=0)
    width_cm: float | None = Field(default=None, ge=0)
    depth_cm: float | None = Field(default=None, ge=0)

    top_elevation: float | None = None
    bottom_elevation: float | None = None

    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    excavated_by: str | None = Field(default=None, max_length=300)
    excavation_date: date | None = None
    recorded_by: str | None = Field(default=None, max_length=300)
    period_id: uuid.UUID | None = None
    dating_evidence: str | None = None
    date_from: int | None = Field(default=None, description="Negative is BCE")
    date_to: int | None = None
    samples_taken: list[str] | None = None

    notes: str | None = None
    metadata_json: dict[str, Any] | None = None
    is_public: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> ContextBase:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        if (
            self.top_elevation is not None
            and self.bottom_elevation is not None
            and self.top_elevation < self.bottom_elevation
        ):
            raise ValueError("top_elevation cannot be below bottom_elevation")
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_to < self.date_from
        ):
            raise ValueError("date_to cannot be earlier than date_from")
        return self


class ContextCreate(ContextBase):
    site_id: uuid.UUID
    context_number: str = Field(
        min_length=1,
        max_length=50,
        description="As written on the recording sheet; unique within the site",
    )


class ContextUpdate(BaseModel):
    context_number: str | None = Field(default=None, min_length=1, max_length=50)
    context_type: ContextType | None = None
    description: str | None = None
    interpretation: str | None = None
    trench: str | None = Field(default=None, max_length=80)
    area: str | None = Field(default=None, max_length=80)
    square: str | None = Field(default=None, max_length=80)
    stratigraphic_unit: str | None = Field(default=None, max_length=80)
    phase: str | None = Field(default=None, max_length=80)
    munsell_color: str | None = Field(default=None, max_length=30)
    composition: str | None = Field(default=None, max_length=300)
    compaction: str | None = Field(default=None, max_length=120)
    inclusions: str | None = None
    thickness_cm: float | None = Field(default=None, ge=0)
    length_cm: float | None = Field(default=None, ge=0)
    width_cm: float | None = Field(default=None, ge=0)
    depth_cm: float | None = Field(default=None, ge=0)
    top_elevation: float | None = None
    bottom_elevation: float | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    excavated_by: str | None = Field(default=None, max_length=300)
    excavation_date: date | None = None
    recorded_by: str | None = Field(default=None, max_length=300)
    period_id: uuid.UUID | None = None
    dating_evidence: str | None = None
    date_from: int | None = None
    date_to: int | None = None
    samples_taken: list[str] | None = None
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None
    is_public: bool | None = None


class ContextSummary(ORMModel):
    id: uuid.UUID
    site_id: uuid.UUID
    context_number: str
    context_type: ContextType
    trench: str | None = None
    area: str | None = None
    phase: str | None = None
    stratigraphic_unit: str | None = None
    period_id: uuid.UUID | None = None
    date_from: int | None = None
    date_to: int | None = None
    review_status: ReviewStatus
    is_public: bool


class ContextRead(ContextSummary):
    description: str | None = None
    interpretation: str | None = None
    square: str | None = None
    munsell_color: str | None = None
    composition: str | None = None
    compaction: str | None = None
    inclusions: str | None = None
    thickness_cm: float | None = None
    length_cm: float | None = None
    width_cm: float | None = None
    depth_cm: float | None = None
    top_elevation: float | None = None
    bottom_elevation: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    excavated_by: str | None = None
    excavation_date: date | None = None
    recorded_by: str | None = None
    dating_evidence: str | None = None
    samples_taken: list[str] | None = None
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None
    owner_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class RelationshipTarget(BaseModel):
    """One edge as returned to the client."""

    id: uuid.UUID
    relation: StratigraphicRelation
    related_context_id: uuid.UUID
    related_context_number: str
    certainty: str | None = None
    notes: str | None = None


class ContextDetail(ContextRead):
    artifact_count: int = 0
    relationships: list[RelationshipTarget] = []
    can_edit: bool = False
    can_delete: bool = False


class RelationshipCreate(BaseModel):
    related_context_id: uuid.UUID
    relation: StratigraphicRelation
    certainty: str | None = Field(
        default=None, pattern="^(certain|probable|possible)$", max_length=30
    )
    notes: str | None = None
