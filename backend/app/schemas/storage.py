"""Schemas for storage locations and the movement register."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import MovementReason, ResourceType, StorageKind
from app.schemas.common import ORMModel


class StorageLocationBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(
        min_length=1,
        max_length=60,
        description="Short identifier used in the path and on labels, e.g. 203 or CAB-4",
    )
    description: str | None = None
    capacity: int | None = Field(default=None, ge=0)
    target_temperature_c: float | None = Field(default=None, ge=-40, le=60)
    target_humidity_percent: float | None = Field(default=None, ge=0, le=100)
    environment_notes: str | None = None
    metadata_json: dict[str, Any] | None = None


class StorageLocationCreate(StorageLocationBase):
    kind: StorageKind
    parent_id: uuid.UUID | None = Field(
        default=None, description="Omit for a root, e.g. the institution itself"
    )
    is_active: bool = True


class StorageLocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = None
    capacity: int | None = Field(default=None, ge=0)
    target_temperature_c: float | None = Field(default=None, ge=-40, le=60)
    target_humidity_percent: float | None = Field(default=None, ge=0, le=100)
    environment_notes: str | None = None
    is_active: bool | None = None
    metadata_json: dict[str, Any] | None = None


class StorageLocationMove(BaseModel):
    """Reparent a location, taking everything inside it along."""

    parent_id: uuid.UUID | None = Field(
        default=None, description="New parent, or null to make this a root"
    )


class StorageLocationSummary(ORMModel):
    id: uuid.UUID
    kind: StorageKind
    name: str
    code: str
    path: str
    display_path: str
    depth: int
    parent_id: uuid.UUID | None = None
    is_active: bool
    capacity: int | None = None


class StorageLocationRead(StorageLocationSummary):
    description: str | None = None
    target_temperature_c: float | None = None
    target_humidity_percent: float | None = None
    environment_notes: str | None = None
    public_token: str
    metadata_json: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class StorageLocationDetail(StorageLocationRead):
    #: The chain from the root down to this location, for a breadcrumb trail.
    ancestors: list[StorageLocationSummary] = []
    children: list[StorageLocationSummary] = []
    #: Objects filed directly here, and in the whole subtree.
    object_count: int = 0
    subtree_object_count: int = 0


class StorageLocationNode(StorageLocationSummary):
    """A location with its subtree inlined, for rendering a tree view."""

    children: list[StorageLocationNode] = []


class MovementCreate(BaseModel):
    """Move one object to a new place."""

    to_location_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Where the object is going. Null records it leaving storage "
            "altogether — repatriated, or consumed by destructive analysis."
        ),
    )
    reason: MovementReason = MovementReason.OTHER
    notes: str | None = None
    moved_at: datetime | None = Field(
        default=None,
        description="When it physically moved, if that is not now. Backdating is normal.",
    )


class MovementRead(ORMModel):
    id: uuid.UUID
    resource_type: ResourceType
    resource_id: uuid.UUID
    resource_label: str | None = None
    from_location_id: uuid.UUID | None = None
    to_location_id: uuid.UUID | None = None
    #: The paths as they read on the day, not as they read now.
    from_path: str | None = None
    to_path: str | None = None
    reason: MovementReason
    notes: str | None = None
    moved_at: datetime
    moved_by_id: uuid.UUID | None = None
    moved_by_label: str | None = None


class LocationOfRecord(BaseModel):
    """Where one object is, in the form a label or a listing needs."""

    resource_type: ResourceType
    resource_id: uuid.UUID
    location_id: uuid.UUID | None = None
    display_path: str | None = None
    #: The free-text location from before the hierarchy, when nothing
    #: structured has been recorded yet.
    legacy_location: str | None = None
    moved_at: datetime | None = None
