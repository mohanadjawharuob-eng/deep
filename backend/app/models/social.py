"""The social media repository: what the institution has said in public.

Outreach is a record like any other. A photograph of a find that went out on
Instagram in March is part of that find's history — it is how most people will
ever encounter the object, and "have we already published this" is a question
somebody asks before every press enquiry.

Three models:

:class:`SocialAccount`
    A channel the institution runs. One row per handle per platform.

:class:`SocialPost`
    Something published, or about to be. Carries its own copy of the text and
    its links to the records it is about, so the archive answers "what did we
    say about this site" without asking the platform it went out on — which
    may not exist in ten years, and whose API certainly will not.

:class:`PostMetric`
    Engagement, as a series rather than a number. A single stored "likes" goes
    stale the moment it is written and can never show whether a post grew or
    stalled.

The part that is specific to archaeology is :attr:`SocialPost.reveals_location`
and the check behind it. Publishing a findspot is how looters learn where to
dig, and the usual way it happens is not somebody typing coordinates — it is a
photograph going out with the GPS tag the camera wrote into it. The platform
already reads that tag on upload, so it can say so before the post goes out
rather than after.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, OwnedRecordMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import PostKind, PostStatus, ResourceType, SocialPlatform

if TYPE_CHECKING:
    from app.models.media import Photograph
    from app.models.project import Project
    from app.models.user import User


class SocialAccount(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """One channel the institution publishes on."""

    __tablename__ = "social_accounts"

    platform: Mapped[SocialPlatform] = mapped_column(
        Enum(
            SocialPlatform, name="social_platform", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
        index=True,
    )
    #: The @name, without the @. What somebody types to find you.
    handle: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)

    #: Who runs it day to day. A name as well as an account, because the person
    #: with the password is often a communications officer without a platform
    #: login.
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    manager_label: Mapped[str | None] = mapped_column(String(200))

    #: Dormant channels are kept. An account nobody posts to any more is still
    #: where three years of outreach lives.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    follower_count: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    manager: Mapped[User | None] = relationship(foreign_keys=[manager_id])
    posts: Mapped[list[SocialPost]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        order_by="SocialPost.created_at.desc()",
    )

    __table_args__ = (
        # One handle per platform. The same name on Instagram and on Bluesky is
        # two accounts; the same name twice on one platform is a mistake.
        UniqueConstraint("platform", "handle", name="uq_social_accounts_handle"),
        CheckConstraint(
            "follower_count IS NULL OR follower_count >= 0",
            name="ck_social_accounts_followers_not_negative",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SocialAccount {self.platform.value}/@{self.handle}>"


class SocialPost(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """One thing said in public, or about to be."""

    __tablename__ = "social_posts"

    account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("social_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: An internal handle for the post, so a content calendar reads as a list
    #: of subjects rather than a wall of opening sentences.
    title: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    #: The text as published. Kept here rather than fetched, because the
    #: platform it went out on may not exist in ten years and its API
    #: certainly will not.
    body: Mapped[str | None] = mapped_column(Text)
    #: Stored apart from the body so they can be counted and reused. A campaign
    #: is partly a set of tags used consistently.
    hashtags: Mapped[list[str] | None] = mapped_column(JSONB)
    language: Mapped[str | None] = mapped_column(String(8), index=True)

    kind: Mapped[PostKind] = mapped_column(
        Enum(PostKind, name="post_kind", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=PostKind.POST,
        index=True,
    )
    status: Mapped[PostStatus] = mapped_column(
        Enum(PostStatus, name="post_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=PostStatus.DRAFT,
        index=True,
    )

    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    #: Where it ended up. The one thing that cannot be reconstructed later.
    external_url: Mapped[str | None] = mapped_column(String(600))
    external_id: Mapped[str | None] = mapped_column(String(200))

    # --- What it is about ------------------------------------------------
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    #: The record it features, in the same polymorphic shape as the rest of the
    #: platform — so a find's card can say "this went out on Instagram in
    #: March" without the social module knowing what a find is.
    resource_type: Mapped[ResourceType | None] = mapped_column(
        Enum(ResourceType, name="resource_type", values_callable=lambda e: [m.value for m in e])
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)

    # --- Approval --------------------------------------------------------
    #: Outreach about an unpublished excavation has consequences for a permit,
    #: for a funder's embargo, and for who learns where to dig. Somebody has to
    #: say yes, and the record has to show who.
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_note: Mapped[str | None] = mapped_column(Text)

    # --- Location disclosure ---------------------------------------------
    #: Set deliberately by a person: this post shows where a site is. Separate
    #: from the automatic check below, because the automatic check finds GPS
    #: tags and a person recognises a landmark in the background.
    reveals_location: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: What the automatic check found the last time it ran, kept so the warning
    #: survives a page reload and shows up in a list. Advisory, never a bar.
    location_warning: Mapped[str | None] = mapped_column(Text)

    notes: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    account: Mapped[SocialAccount] = relationship(back_populates="posts")
    project: Mapped[Project | None] = relationship()
    approved_by: Mapped[User | None] = relationship(foreign_keys=[approved_by_id])
    assets: Mapped[list[PostAsset]] = relationship(
        back_populates="post", cascade="all, delete-orphan", order_by="PostAsset.position"
    )
    metrics: Mapped[list[PostMetric]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
        order_by="PostMetric.recorded_at.desc()",
    )
    notes_thread: Mapped[list[PostNote]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
        order_by="PostNote.created_at",
    )

    __table_args__ = (
        Index("ix_social_posts_account_status", "account_id", "status"),
        Index("ix_social_posts_calendar", "status", "scheduled_for"),
        Index("ix_social_posts_subject", "resource_type", "resource_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SocialPost {self.title[:40]} {self.status.value}>"


class PostAsset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One photograph used in one post.

    A join table rather than a copy. The photograph stays in the archive where
    it was catalogued, and this records that it also went out in public — which
    is exactly what somebody needs to know before publishing it again, or when
    a rights query arrives about an image already in circulation.
    """

    __tablename__ = "post_assets"

    post_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("social_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    photograph_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("photographs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Alternative text, written for this post. Not the photograph's caption:
    #: a catalogue caption says what an object is, alt text says what somebody
    #: who cannot see the image needs to know.
    alt_text: Mapped[str | None] = mapped_column(Text)
    #: The credit line as it appeared. Photographers move on and licences
    #: change; what was published cannot.
    credit: Mapped[str | None] = mapped_column(String(300))

    post: Mapped[SocialPost] = relationship(back_populates="assets")
    photograph: Mapped[Photograph] = relationship()

    __table_args__ = (
        UniqueConstraint("post_id", "photograph_id", name="uq_post_assets_once"),
        Index("ix_post_assets_order", "post_id", "position"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PostAsset {self.post_id} #{self.position}>"


class PostMetric(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Engagement at one moment.

    A series, not a number. A stored "likes" is stale the moment it is written
    and can never answer the question anybody actually has, which is whether a
    post kept growing or stopped after a day.
    """

    __tablename__ = "post_metrics"

    post_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("social_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    #: All nullable: platforms report different things, and a zero that means
    #: "this platform does not tell us" is a zero that ruins an average.
    impressions: Mapped[int | None] = mapped_column(Integer)
    reach: Mapped[int | None] = mapped_column(Integer)
    likes: Mapped[int | None] = mapped_column(Integer)
    comments: Mapped[int | None] = mapped_column(Integer)
    shares: Mapped[int | None] = mapped_column(Integer)
    saves: Mapped[int | None] = mapped_column(Integer)
    clicks: Mapped[int | None] = mapped_column(Integer)

    #: Typed in from the platform's own dashboard, in the usual case. Recorded
    #: so a figure can be traced back to where it came from.
    source: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)

    post: Mapped[SocialPost] = relationship(back_populates="metrics")

    __table_args__ = (
        # One reading per post per moment. Two rows for the same instant are a
        # double-entry, and they make every chart wrong in a way that looks
        # like real growth.
        UniqueConstraint("post_id", "recorded_at", name="uq_post_metrics_moment"),
        CheckConstraint(
            "(impressions IS NULL OR impressions >= 0) AND "
            "(reach IS NULL OR reach >= 0) AND "
            "(likes IS NULL OR likes >= 0) AND "
            "(comments IS NULL OR comments >= 0) AND "
            "(shares IS NULL OR shares >= 0) AND "
            "(saves IS NULL OR saves >= 0) AND "
            "(clicks IS NULL OR clicks >= 0)",
            name="ck_post_metrics_not_negative",
        ),
        Index("ix_post_metrics_series", "post_id", "recorded_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PostMetric {self.post_id} {self.recorded_at:%Y-%m-%d}>"


class PostNote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A colleague's remark on a post that has not gone out yet.

    Approving is one bit — yes or not yet — and almost every real review is
    not one bit. "The find number is wrong", "can we wait until the permit is
    signed", "lovely, but crop the trowel out" are the substance of getting a
    post right, and without somewhere to put them they are said in a corridor
    or a chat app and lost the moment the post goes out.

    Kept after publication rather than cleared. Why a post says what it says is
    a question that gets asked later, usually by somebody who was not in the
    room, and an empty thread cannot answer it.
    """

    __tablename__ = "post_notes"

    post_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("social_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: A note attached to an approval or a send-back, rather than said in
    #: passing. Shown differently, because "not yet, because X" is the reason a
    #: post is sitting still and a remark is not.
    decision: Mapped[str | None] = mapped_column(String(20))

    post: Mapped[SocialPost] = relationship(back_populates="notes_thread")
    author: Mapped[User | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PostNote on {self.post_id}>"
