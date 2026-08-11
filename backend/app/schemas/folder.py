"""Folders in the media library."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import FolderKind


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = Field(
        default=None, description="Leave out for a folder at the top level."
    )
    kind: FolderKind = FolderKind.GENERAL
    note: str | None = None

    @field_validator("name", "note")
    @classmethod
    def _tidy(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None


class FolderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    #: Explicit ``null`` moves the folder to the top level, which is why this
    #: is read from ``model_fields_set`` rather than tested for ``None``.
    parent_id: uuid.UUID | None = None
    note: str | None = None


class FolderRead(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None
    kind: FolderKind
    note: str | None = None
    #: Files filed **directly** here, not counting sub-folders. A count that
    #: silently included everything underneath would make an empty folder look
    #: full.
    file_count: int
    created_at: datetime


class FolderMove(BaseModel):
    photograph_ids: list[uuid.UUID] = Field(default_factory=list)
    document_ids: list[uuid.UUID] = Field(default_factory=list)
