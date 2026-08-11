"""Schemas for photographs, documents and 3D models."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.models.enums import DocumentType, Model3DFormat, ReviewStatus
from app.schemas.common import ORMModel


class AttachmentTargets(BaseModel):
    """Where a media record hangs from.

    At least one is required — a photograph attached to nothing is unfindable,
    and its permissions would have nothing to inherit from.
    """

    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    context_id: uuid.UUID | None = None
    museum_object_id: uuid.UUID | None = None
    folder_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> AttachmentTargets:
        if not any((self.project_id, self.site_id, self.artifact_id, self.context_id)):
            raise ValueError(
                "Attach this to a project, site, artifact or context — "
                "an unattached file cannot be found again or permission-checked"
            )
        return self


# --------------------------------------------------------------------------
# Photographs
# --------------------------------------------------------------------------
class PhotographUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    photographer: str | None = Field(default=None, max_length=200)
    taken_at: datetime | None = None
    camera_make: str | None = Field(default=None, max_length=120)
    camera_model: str | None = Field(default=None, max_length=120)
    lens: str | None = Field(default=None, max_length=150)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    altitude: float | None = None
    direction: float | None = Field(default=None, ge=0, lt=360)
    location_text: str | None = Field(default=None, max_length=300)
    shot_type: str | None = Field(default=None, max_length=80)
    has_scale: bool | None = None
    is_cover: bool | None = Field(
        default=None, description="Use as the representative image of its parent record"
    )
    tags: list[str] | None = None
    metadata_json: dict[str, Any] | None = None
    is_public: bool | None = None


class PhotographSummary(ORMModel):
    id: uuid.UUID
    title: str
    photographer: str | None = None
    taken_at: datetime | None = None
    shot_type: str | None = None
    is_cover: bool
    width: int | None = None
    height: int | None = None
    file_size: int | None = None
    mime_type: str | None = None
    #: Which thumbnail sizes exist, so the client can pick without guessing.
    thumbnail_sizes: list[int] = []
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    context_id: uuid.UUID | None = None
    museum_object_id: uuid.UUID | None = None
    folder_id: uuid.UUID | None = None
    review_status: ReviewStatus
    is_public: bool
    created_at: datetime


class PhotographRead(PhotographSummary):
    description: str | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    lens: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    direction: float | None = None
    location_text: str | None = None
    has_scale: bool | None = None
    tags: list[str] | None = None
    original_filename: str | None = None
    checksum: str | None = None
    #: The full EXIF block as extracted on upload, kept for provenance.
    exif: dict[str, Any] | None = None
    metadata_json: dict[str, Any] | None = None
    owner_id: uuid.UUID | None = None
    updated_at: datetime


class PhotographDetail(PhotographRead):
    can_edit: bool = False
    can_delete: bool = False


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------
class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    document_type: DocumentType | None = None
    author: str | None = Field(default=None, max_length=300)
    document_date: date | None = None
    language: str | None = Field(default=None, max_length=10)
    tags: list[str] | None = None
    publication_id: uuid.UUID | None = None
    metadata_json: dict[str, Any] | None = None
    is_public: bool | None = None


class DocumentSummary(ORMModel):
    id: uuid.UUID
    title: str
    document_type: DocumentType
    author: str | None = None
    document_date: date | None = None
    original_filename: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    page_count: int | None = None
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    context_id: uuid.UUID | None = None
    museum_object_id: uuid.UUID | None = None
    folder_id: uuid.UUID | None = None
    review_status: ReviewStatus
    is_public: bool
    created_at: datetime


class DocumentRead(DocumentSummary):
    description: str | None = None
    language: str | None = None
    tags: list[str] | None = None
    checksum: str | None = None
    publication_id: uuid.UUID | None = None
    researcher_id: uuid.UUID | None = None
    metadata_json: dict[str, Any] | None = None
    owner_id: uuid.UUID | None = None
    updated_at: datetime
    #: Whether text was extracted and is therefore searchable.
    has_extracted_text: bool = False


class DocumentDetail(DocumentRead):
    can_edit: bool = False
    can_delete: bool = False


# --------------------------------------------------------------------------
# 3D models
# --------------------------------------------------------------------------
class Model3DCreate(AttachmentTargets):
    """A 3D model, either linked or uploaded.

    Photogrammetry output routinely runs to gigabytes, so the common case is a
    *link* to where it already lives — Sketchfab, an institutional repository —
    with an optional lightweight mesh uploaded for in-browser preview.
    """

    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    format: Model3DFormat = Model3DFormat.OTHER
    external_url: str | None = Field(default=None, max_length=1000)
    capture_method: str | None = Field(default=None, max_length=120)
    software: str | None = Field(default=None, max_length=150)
    capture_date: date | None = None
    vertex_count: int | None = Field(default=None, ge=0)
    face_count: int | None = Field(default=None, ge=0)
    scale_note: str | None = Field(default=None, max_length=200)
    license: str | None = Field(default=None, max_length=120)
    metadata_json: dict[str, Any] | None = None
    is_public: bool = False

    @model_validator(mode="after")
    def _needs_a_source(self) -> Model3DCreate:
        if not self.external_url:
            raise ValueError(
                "Give an external_url. To upload a mesh file instead, use the file upload endpoint."
            )
        return self


class Model3DUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    format: Model3DFormat | None = None
    external_url: str | None = Field(default=None, max_length=1000)
    capture_method: str | None = Field(default=None, max_length=120)
    software: str | None = Field(default=None, max_length=150)
    capture_date: date | None = None
    vertex_count: int | None = Field(default=None, ge=0)
    face_count: int | None = Field(default=None, ge=0)
    scale_note: str | None = Field(default=None, max_length=200)
    license: str | None = Field(default=None, max_length=120)
    metadata_json: dict[str, Any] | None = None
    is_public: bool | None = None


class Model3DSummary(ORMModel):
    id: uuid.UUID
    title: str
    format: Model3DFormat
    external_url: str | None = None
    #: Set when the model can be shown in an ``<iframe>``; null when it cannot.
    embed_url: str | None = None
    has_file: bool = False
    file_size: int | None = None
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    context_id: uuid.UUID | None = None
    museum_object_id: uuid.UUID | None = None
    folder_id: uuid.UUID | None = None
    is_public: bool
    created_at: datetime


class Model3DRead(Model3DSummary):
    description: str | None = None
    capture_method: str | None = None
    software: str | None = None
    capture_date: date | None = None
    vertex_count: int | None = None
    face_count: int | None = None
    scale_note: str | None = None
    license: str | None = None
    checksum: str | None = None
    metadata_json: dict[str, Any] | None = None
    owner_id: uuid.UUID | None = None
    updated_at: datetime


class Model3DDetail(Model3DRead):
    can_edit: bool = False
    can_delete: bool = False
