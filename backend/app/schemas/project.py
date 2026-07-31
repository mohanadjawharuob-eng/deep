"""Project schemas."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import ProjectRole, ProjectStatus
from app.schemas.common import ORMModel
from app.schemas.user import UserPublic

_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{1,49}$")


def slugify(value: str) -> str:
    """URL-safe form of a name, used for readable project URLs."""
    cleaned = re.sub(r"[^\w\s-]", "", value.lower(), flags=re.UNICODE)
    return re.sub(r"[\s_]+", "-", cleaned).strip("-")[:320] or "project"


class ProjectBase(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    description: str | None = None
    project_type: str | None = Field(default=None, max_length=60)

    principal_investigator: str | None = Field(default=None, max_length=200)
    principal_investigator_id: uuid.UUID | None = None
    institution: str | None = Field(default=None, max_length=300)
    partner_institutions: list[str] | None = None

    country: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    start_date: date | None = None
    end_date: date | None = None
    status: ProjectStatus = ProjectStatus.PLANNED

    funding_source: str | None = Field(default=None, max_length=300)
    funding_amount: float | None = Field(default=None, ge=0)
    funding_currency: str | None = Field(default=None, min_length=3, max_length=3)
    permit_number: str | None = Field(default=None, max_length=120)
    permit_authority: str | None = Field(default=None, max_length=300)

    keywords: list[str] | None = None
    metadata_json: dict[str, Any] | None = None
    is_public: bool = False

    @model_validator(mode="after")
    def _dates_in_order(self) -> ProjectBase:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        return self

    @field_validator("funding_currency")
    @classmethod
    def _upper_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class ProjectCreate(ProjectBase):
    code: str = Field(
        min_length=2,
        max_length=50,
        description="Short identifier used in inventory numbers, e.g. TELL-2024",
    )

    @field_validator("code")
    @classmethod
    def _valid_code(cls, value: str) -> str:
        upper = value.strip().upper()
        if not _CODE_RE.match(upper):
            raise ValueError(
                "Code must start with a letter or digit and contain only "
                "letters, digits, dot, underscore and hyphen"
            )
        return upper


class ProjectUpdate(BaseModel):
    """Every field optional; only what is sent is changed."""

    name: str | None = Field(default=None, min_length=2, max_length=300)
    description: str | None = None
    project_type: str | None = Field(default=None, max_length=60)
    principal_investigator: str | None = Field(default=None, max_length=200)
    principal_investigator_id: uuid.UUID | None = None
    institution: str | None = Field(default=None, max_length=300)
    partner_institutions: list[str] | None = None
    country: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    start_date: date | None = None
    end_date: date | None = None
    status: ProjectStatus | None = None
    funding_source: str | None = Field(default=None, max_length=300)
    funding_amount: float | None = Field(default=None, ge=0)
    funding_currency: str | None = Field(default=None, min_length=3, max_length=3)
    permit_number: str | None = Field(default=None, max_length=120)
    permit_authority: str | None = Field(default=None, max_length=300)
    keywords: list[str] | None = None
    metadata_json: dict[str, Any] | None = None
    is_public: bool | None = None


class ProjectSummary(ORMModel):
    """Compact form used in listings and in other records' responses."""

    id: uuid.UUID
    name: str
    code: str
    slug: str
    status: ProjectStatus
    country: str | None = None
    region: str | None = None
    institution: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_public: bool
    latitude: float | None = None
    longitude: float | None = None


class ProjectRead(ProjectSummary):
    description: str | None = None
    project_type: str | None = None
    principal_investigator: str | None = None
    principal_investigator_id: uuid.UUID | None = None
    partner_institutions: list[str] | None = None
    funding_source: str | None = None
    funding_amount: float | None = None
    funding_currency: str | None = None
    permit_number: str | None = None
    permit_authority: str | None = None
    keywords: list[str] | None = None
    metadata_json: dict[str, Any] | None = None
    owner_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class ProjectDetail(ProjectRead):
    """Read response with the counts the project page needs."""

    site_count: int = 0
    artifact_count: int = 0
    member_count: int = 0
    #: What the requesting user may do, so the UI need not re-derive the policy.
    can_edit: bool = False
    can_delete: bool = False


# --------------------------------------------------------------------------
# Membership
# --------------------------------------------------------------------------
class MembershipCreate(BaseModel):
    user_id: uuid.UUID
    role: ProjectRole = ProjectRole.STUDENT
    title: str | None = Field(default=None, max_length=150)


class MembershipUpdate(BaseModel):
    role: ProjectRole | None = None
    title: str | None = Field(default=None, max_length=150)


class MembershipRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    role: ProjectRole
    title: str | None = None
    created_at: datetime
    user: UserPublic
