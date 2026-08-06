"""Folders of files that live somewhere else."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import MediaFolderKind
from app.schemas.common import ORMModel


class MediaFolderBase(BaseModel):
    label: str = Field(max_length=300, description="What this folder is, in your own words")
    kind: MediaFolderKind = MediaFolderKind.PHOTOGRAPHS
    path: str = Field(
        max_length=1000,
        description=(
            "The folder exactly as written. Never opened, resolved or checked — "
            "it may be a Windows path, a share, a mount point on somebody "
            "else's laptop, or a shelf reference for a box of discs."
        ),
    )
    medium: str | None = Field(
        default=None,
        max_length=300,
        description=(
            "Which disk that path is on. The field most often left out and the "
            "one that matters in five years."
        ),
    )
    item_count: int | None = Field(default=None, ge=0)
    size_gb: float | None = Field(default=None, ge=0)
    recorded_on: date | None = None
    is_backed_up: bool | None = Field(
        default=None,
        description="Three states: yes, no, and nobody has said. The third is the common one.",
    )
    note: str | None = None

    @field_validator("label", "path")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned


class MediaFolderCreate(MediaFolderBase):
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    context_id: uuid.UUID | None = None


class MediaFolderUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=300)
    kind: MediaFolderKind | None = None
    path: str | None = Field(default=None, max_length=1000)
    medium: str | None = Field(default=None, max_length=300)
    item_count: int | None = Field(default=None, ge=0)
    size_gb: float | None = Field(default=None, ge=0)
    recorded_on: date | None = None
    is_backed_up: bool | None = None
    note: str | None = None


class MediaFolderRead(ORMModel, MediaFolderBase):
    id: uuid.UUID
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    context_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
