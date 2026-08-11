"""Schemas for the social media repository."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.models.enums import PostKind, PostStatus, ResourceType, SocialPlatform
from app.schemas.common import ORMModel

# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------


class AccountBase(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=500)
    description: str | None = None
    manager_id: uuid.UUID | None = None
    manager_label: str | None = Field(default=None, max_length=200)
    follower_count: int | None = Field(default=None, ge=0)
    notes: str | None = None


class AccountCreate(AccountBase):
    platform: SocialPlatform
    handle: str = Field(min_length=1, max_length=160, description="The @name, without the @")
    is_active: bool = True
    is_public: bool = False


class AccountUpdate(AccountBase):
    handle: str | None = Field(default=None, min_length=1, max_length=160)
    is_active: bool | None = None
    is_public: bool | None = None


class AccountRead(ORMModel):
    id: uuid.UUID
    platform: SocialPlatform
    handle: str
    display_name: str | None = None
    url: str | None = None
    description: str | None = None
    manager_id: uuid.UUID | None = None
    manager_label: str | None = None
    follower_count: int | None = None
    is_active: bool
    is_public: bool
    notes: str | None = None
    owner_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    post_count: int = 0
    published_count: int = 0
    #: Posts waiting on somebody. The number a communications officer opens
    #: the screen to see.
    awaiting_approval: int = 0


# --------------------------------------------------------------------------
# Posts
# --------------------------------------------------------------------------


class PostBase(BaseModel):
    title: str = Field(min_length=1, max_length=300, description="An internal handle for it")
    body: str | None = None
    hashtags: list[str] | None = None
    language: str | None = Field(default=None, max_length=8)
    kind: PostKind = PostKind.POST
    scheduled_for: datetime | None = None
    project_id: uuid.UUID | None = None
    resource_type: ResourceType | None = None
    resource_id: uuid.UUID | None = None
    reveals_location: bool = False
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _a_subject_needs_both_halves(self) -> PostBase:
        """A resource type with no id points at nothing; an id with no type
        cannot be looked up. Either both or neither."""
        if (self.resource_type is None) != (self.resource_id is None):
            raise ValueError(
                "Say both what kind of record this post is about and which one, or neither"
            )
        return self


class PostCreate(PostBase):
    is_public: bool = False


class PostUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    body: str | None = None
    hashtags: list[str] | None = None
    language: str | None = Field(default=None, max_length=8)
    kind: PostKind | None = None
    #: Draft, needs approval, scheduled and withdrawn are all settable here.
    #: `published` is not: publishing is an action with a URL attached. See
    #: the `/publish` endpoint.
    status: PostStatus | None = None
    scheduled_for: datetime | None = None
    external_url: str | None = Field(default=None, max_length=600)
    project_id: uuid.UUID | None = None
    reveals_location: bool | None = None
    notes: str | None = None
    is_public: bool | None = None

    @model_validator(mode="after")
    def _publishing_is_not_an_edit(self) -> PostUpdate:
        if self.status is PostStatus.PUBLISHED:
            raise ValueError(
                "Marking a post published needs the address it went out at. "
                "Use /social/posts/{id}/publish."
            )
        if self.status is PostStatus.APPROVED:
            raise ValueError(
                "Approval records who said yes, so it is its own action. "
                "Use /social/posts/{id}/approve."
            )
        return self


class PublishRequest(BaseModel):
    """Record that a post went out.

    The platform holds no API keys and posts nothing itself — an institution's
    outreach account is not something a records system should be able to
    publish from unattended. This records what a person did.
    """

    external_url: str | None = Field(default=None, max_length=600)
    external_id: str | None = Field(default=None, max_length=200)
    published_at: datetime | None = Field(default=None, description="Defaults to now")


class ApprovalRequest(BaseModel):
    note: str | None = Field(
        default=None, description="Why, or what was changed as a condition of saying yes"
    )


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, description="What needs saying about this post")


class NoteRead(ORMModel):
    id: uuid.UUID
    body: str
    #: ``approved`` or ``sent_back`` when the note came with a decision, so a
    #: reason a post is sitting still reads differently from a passing remark.
    decision: str | None = None
    author_label: str | None = None
    created_at: datetime


class SendBackRequest(BaseModel):
    note: str = Field(
        min_length=1,
        description=(
            "What needs changing. Required: 'not yet' with no reason is a dead "
            "end for whoever wrote the post."
        ),
    )


class ComposerRead(BaseModel):
    """How one channel wants a post written."""

    platform: str
    label: str
    text_label: str
    text_help: str
    text_limit: int | None = None
    needs_image: bool
    image_help: str
    allows_link: bool
    link_help: str | None = None
    kinds: list[str] = Field(default_factory=list)
    hashtag_help: str


class LocationFinding(BaseModel):
    kind: str
    detail: str
    photograph_id: uuid.UUID | None = None


class LocationCheckResult(BaseModel):
    """What the pre-publication check found. Advisory, never a bar."""

    clear: bool
    findings: list[LocationFinding] = Field(default_factory=list)
    summary: str | None = None


class AssetRead(ORMModel):
    id: uuid.UUID
    photograph_id: uuid.UUID
    position: int
    alt_text: str | None = None
    credit: str | None = None
    #: Filled from the photograph, so a screen can draw the strip without a
    #: request per image.
    filename: str | None = None
    thumbnail_url: str | None = None
    #: True when this image still carries the coordinates the camera wrote.
    has_gps: bool = False


class AssetAdd(BaseModel):
    photograph_id: uuid.UUID
    alt_text: str | None = None
    credit: str | None = Field(default=None, max_length=300)
    position: int | None = Field(default=None, ge=0)


class MetricCreate(BaseModel):
    recorded_at: datetime | None = Field(default=None, description="Defaults to now")
    impressions: int | None = Field(default=None, ge=0)
    reach: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    saves: int | None = Field(default=None, ge=0)
    clicks: int | None = Field(default=None, ge=0)
    source: str | None = Field(default=None, max_length=120)
    notes: str | None = None

    @model_validator(mode="after")
    def _a_reading_of_nothing_is_not_a_reading(self) -> MetricCreate:
        counts = [
            self.impressions,
            self.reach,
            self.likes,
            self.comments,
            self.shares,
            self.saves,
            self.clicks,
        ]
        if all(value is None for value in counts):
            raise ValueError("Give at least one figure — a reading with no numbers records nothing")
        return self


class MetricRead(ORMModel):
    id: uuid.UUID
    post_id: uuid.UUID
    recorded_at: datetime
    impressions: int | None = None
    reach: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    clicks: int | None = None
    source: str | None = None
    notes: str | None = None


class Engagement(BaseModel):
    """The latest reading, and how it moved since the one before."""

    recorded_at: datetime | None = None
    impressions: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    interactions: int | None = None
    change: int | None = None
    readings: int = 0


class PostSummary(ORMModel):
    id: uuid.UUID
    account_id: uuid.UUID
    title: str
    kind: PostKind
    status: PostStatus
    scheduled_for: datetime | None = None
    published_at: datetime | None = None
    external_url: str | None = None
    language: str | None = None
    project_id: uuid.UUID | None = None
    resource_type: ResourceType | None = None
    resource_id: uuid.UUID | None = None
    reveals_location: bool
    location_warning: str | None = None
    is_public: bool
    created_at: datetime

    platform: SocialPlatform | None = None
    handle: str | None = None
    asset_count: int = 0
    engagement: Engagement | None = None


class PostRead(PostSummary):
    body: str | None = None
    hashtags: list[str] | None = None
    approved_by_id: uuid.UUID | None = None
    approved_at: datetime | None = None
    approval_note: str | None = None
    external_id: str | None = None
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None
    owner_id: uuid.UUID | None = None
    updated_at: datetime


class PostDetail(PostRead):
    assets: list[AssetRead] = Field(default_factory=list)
    metrics: list[MetricRead] = Field(default_factory=list)
    project_name: str | None = None
    #: What the post is about, resolved to something readable.
    subject_label: str | None = None
    approved_by_label: str | None = None
    location_check: LocationCheckResult | None = None
    can_edit: bool = False
    can_delete: bool = False
    can_approve: bool = False
    notes_thread: list[NoteRead] = Field(default_factory=list)


class OutreachSummary(BaseModel):
    """The module's front page."""

    accounts: int = 0
    published: int = 0
    scheduled: int = 0
    awaiting_approval: int = 0
    #: Posts carrying an unresolved location warning. The number worth acting
    #: on before anything else on this screen.
    with_location_warnings: int = 0
    by_platform: dict[str, int] = Field(default_factory=dict)


class CoverageEntry(BaseModel):
    """One post that featured a record, for that record's own card."""

    id: uuid.UUID
    title: str
    platform: SocialPlatform | None = None
    handle: str | None = None
    status: PostStatus
    published_at: datetime | None = None
    external_url: str | None = None
