"""Schemas for the activity feed and version history."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ActivityAction, ResourceType
from app.schemas.common import ORMModel


class ActivityRead(ORMModel):
    id: uuid.UUID
    created_at: datetime
    action: ActivityAction
    user_id: uuid.UUID | None = None
    #: Kept even when the account is gone, so old entries still read sensibly.
    user_label: str | None = None
    resource_type: ResourceType | None = None
    resource_id: uuid.UUID | None = None
    resource_label: str | None = None
    project_id: uuid.UUID | None = None
    summary: str | None = None
    changes: dict[str, Any] | None = None


class RevisionSummary(ORMModel):
    """One version, without the payload — enough to render a history list."""

    id: uuid.UUID
    version: int
    created_at: datetime
    resource_type: ResourceType
    resource_id: uuid.UUID
    changed_by_id: uuid.UUID | None = None
    change_summary: str | None = None
    changed_fields: list[str] | None = None
    is_restore: bool


class RevisionRead(RevisionSummary):
    """A version including the full snapshot of the record at that point."""

    data: dict[str, Any]


class RestoreResponse(BaseModel):
    detail: str
    restored_version: int = Field(description="The version whose content was applied")
    new_version: int = Field(description="Version number given to the state it replaced")
    changed_fields: list[str]
