"""Asking somebody for a file, and what a stranger holding the link may see."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, computed_field, field_validator

from app.models.enums import DataRequestKind, DataRequestStatus
from app.schemas.common import ORMModel


class DataRequestCreate(BaseModel):
    recipient_email: EmailStr = Field(description="Who is being asked. They need no account.")
    recipient_name: str | None = Field(default=None, max_length=200)
    kind: DataRequestKind = DataRequestKind.PHOTOGRAPHS
    message: str | None = Field(
        default=None,
        description="The ask in your own words. Goes into the e-mail as written.",
    )
    max_uploads: int = Field(
        default=20,
        ge=1,
        le=200,
        description="How many files this invitation may deliver in total.",
    )
    expires_in_days: int | None = Field(
        default=None,
        ge=1,
        le=180,
        description="Defaults to three weeks.",
    )

    # Exactly one of these says what the files are about.
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    context_id: uuid.UUID | None = None
    museum_object_id: uuid.UUID | None = None

    @field_validator("message", "recipient_name")
    @classmethod
    def _tidy(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class DataRequestRead(ORMModel):
    id: uuid.UUID
    record_label: str
    kind: DataRequestKind
    message: str | None = None
    recipient_email: str
    recipient_name: str | None = None
    status: DataRequestStatus
    delivery_note: str | None = None
    expires_at: datetime
    max_uploads: int
    upload_count: int
    sent_at: datetime | None = None
    first_upload_at: datetime | None = None
    closed_at: datetime | None = None
    created_at: datetime

    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    context_id: uuid.UUID | None = None
    museum_object_id: uuid.UUID | None = None

    requested_by_id: uuid.UUID | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def uploads_left(self) -> int:
        return max(0, self.max_uploads - self.upload_count)


class DataRequestCreated(DataRequestRead):
    """The one response that carries the link.

    Only the hash is stored, so this is the single moment the platform can show
    it. Shown once so it can be copied and sent by hand when e-mail is not
    configured, or when the recipient says it never arrived.
    """

    invite_url: str


class InviteRead(BaseModel):
    """What the person holding the link is told.

    Deliberately thin. It names the record so they know they are sending the
    right files to the right thing, and says nothing else about it — not its
    location, not its description, not who else was asked. Whoever forwards an
    invitation should not be forwarding a window into the archive.
    """

    record_label: str
    kind: DataRequestKind
    asked_for: str = Field(description="The kind, worded for a sentence: 'photographs'.")
    message: str | None = None
    requested_by: str | None = None
    organisation: str
    expires_at: datetime
    uploads_left: int
    accepted_note: str = Field(
        description="What this link will and will not accept, in plain words."
    )


class InviteUploadResult(BaseModel):
    filename: str
    size_bytes: int
    uploads_left: int
    thanks: str
