"""Site schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.models.enums import ConditionState, ProtectionStatus, ReviewStatus, SiteType
from app.schemas.common import ORMModel


class SiteBase(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    alternative_names: list[str] | None = Field(
        default=None,
        description="Other names the site is known by, in any language or period",
    )
    description: str | None = None
    site_type: SiteType = SiteType.OTHER

    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    elevation: float | None = None
    location_accuracy_m: float | None = Field(default=None, ge=0)
    location_restricted: bool = Field(
        default=False,
        description="Publish only an approximate position; for sites at risk of looting",
    )

    country: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=200)
    district: str | None = Field(default=None, max_length=200)
    municipality: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=400)
    national_register_id: str | None = Field(default=None, max_length=120)

    period_id: uuid.UUID | None = None
    period_text: str | None = Field(default=None, max_length=300)
    dating_method: str | None = Field(default=None, max_length=200)
    date_from: int | None = Field(
        default=None, description="Start year; negative is BCE (e.g. -2900 = 2900 BCE)"
    )
    date_to: int | None = Field(default=None, description="End year; negative is BCE")

    protection_status: ProtectionStatus = ProtectionStatus.UNKNOWN
    condition: ConditionState = ConditionState.UNKNOWN
    threats: list[str] | None = None
    land_use: str | None = Field(default=None, max_length=200)
    landowner: str | None = Field(default=None, max_length=300)

    discovery_date: date | None = None
    discovered_by: str | None = Field(default=None, max_length=300)
    excavation_start: date | None = None
    excavation_end: date | None = None

    references: str | None = None
    notes: str | None = None
    keywords: list[str] | None = None
    metadata_json: dict[str, Any] | None = None
    is_public: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> SiteBase:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_to < self.date_from
        ):
            raise ValueError("date_to cannot be earlier than date_from")
        if (
            self.excavation_start
            and self.excavation_end
            and self.excavation_end < self.excavation_start
        ):
            raise ValueError("excavation_end cannot be before excavation_start")
        return self


class SiteCreate(SiteBase):
    project_id: uuid.UUID
    code: str = Field(
        min_length=1, max_length=60, description="Site code, unique within the project"
    )


class SiteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    code: str | None = Field(default=None, min_length=1, max_length=60)
    alternative_names: list[str] | None = None
    description: str | None = None
    site_type: SiteType | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    elevation: float | None = None
    location_accuracy_m: float | None = Field(default=None, ge=0)
    location_restricted: bool | None = None
    country: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=200)
    district: str | None = Field(default=None, max_length=200)
    municipality: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=400)
    national_register_id: str | None = Field(default=None, max_length=120)
    period_id: uuid.UUID | None = None
    period_text: str | None = Field(default=None, max_length=300)
    dating_method: str | None = Field(default=None, max_length=200)
    date_from: int | None = None
    date_to: int | None = None
    protection_status: ProtectionStatus | None = None
    condition: ConditionState | None = None
    threats: list[str] | None = None
    land_use: str | None = Field(default=None, max_length=200)
    landowner: str | None = Field(default=None, max_length=300)
    discovery_date: date | None = None
    discovered_by: str | None = Field(default=None, max_length=300)
    excavation_start: date | None = None
    excavation_end: date | None = None
    references: str | None = None
    notes: str | None = None
    keywords: list[str] | None = None
    metadata_json: dict[str, Any] | None = None
    is_public: bool | None = None


class SiteSummary(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    code: str
    site_type: SiteType
    latitude: float | None = None
    longitude: float | None = None
    country: str | None = None
    region: str | None = None
    period_text: str | None = None
    date_from: int | None = None
    date_to: int | None = None
    protection_status: ProtectionStatus
    condition: ConditionState
    review_status: ReviewStatus
    is_public: bool


class SiteRead(SiteSummary):
    alternative_names: list[str] | None = None
    description: str | None = None
    elevation: float | None = None
    location_accuracy_m: float | None = None
    location_restricted: bool
    district: str | None = None
    municipality: str | None = None
    address: str | None = None
    national_register_id: str | None = None
    period_id: uuid.UUID | None = None
    dating_method: str | None = None
    threats: list[str] | None = None
    land_use: str | None = None
    landowner: str | None = None
    discovery_date: date | None = None
    discovered_by: str | None = None
    excavation_start: date | None = None
    excavation_end: date | None = None
    references: str | None = None
    notes: str | None = None
    keywords: list[str] | None = None
    metadata_json: dict[str, Any] | None = None
    owner_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class SiteDetail(SiteRead):
    artifact_count: int = 0
    context_count: int = 0
    can_edit: bool = False
    can_delete: bool = False
