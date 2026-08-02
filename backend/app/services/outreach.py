"""Checks worth running before a post goes out.

One of them is the reason this module exists in an archaeological platform
rather than being a spreadsheet.

**Publishing a findspot is how looting starts.** Not usually by somebody typing
coordinates — by a photograph going out with the GPS tag the camera wrote into
it without being asked. A phone geotags every frame by default; so does most
field kit. The picture looks like a picture of a pot.

The platform already reads that tag when a photograph is uploaded, so it can
say so *before* the post goes out. Which is the only time saying so is any use:
a warning after publication is a note about something that has already
happened.

The check is advisory throughout. It never blocks a post. Sometimes revealing a
location is exactly right — a site that is already a visitor attraction, a
museum's own address — and a platform that refuses is a platform people work
around, which loses the warning for the cases that matter.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import PostStatus, ResourceType
from app.models.media import Photograph
from app.models.site import Site
from app.models.social import PostAsset, PostMetric, SocialPost


@dataclass(slots=True)
class LocationFinding:
    """One reason a post might give away where a site is."""

    kind: str
    detail: str
    #: The photograph responsible, where one is. Lets a screen point at the
    #: image rather than making somebody work out which of nine it means.
    photograph_id: uuid.UUID | None = None


@dataclass(slots=True)
class LocationCheck:
    """What the check found. Advisory, never a bar."""

    findings: list[LocationFinding] = field(default_factory=list)

    @property
    def clear(self) -> bool:
        return not self.findings

    def summary(self) -> str | None:
        """One line for the record, or ``None`` when there is nothing to say."""
        if not self.findings:
            return None
        if len(self.findings) == 1:
            return self.findings[0].detail
        return f"{len(self.findings)} things could give away a location: " + "; ".join(
            finding.detail for finding in self.findings
        )


def check_location_disclosure(session: Session, post: SocialPost) -> LocationCheck:
    """What this post would tell somebody about where things are.

    Three things are looked at, in the order they matter:

    1. **GPS in an attached photograph.** The common case, and the invisible
       one. The coordinates are in the file the camera wrote.
    2. **A site that is not public.** If the post is about a site the
       institution has chosen not to publish, saying so publicly is at least
       worth a second look.
    3. **The author's own flag.** Somebody who has recognised a landmark in the
       background knows something no automatic check will find.
    """
    check = LocationCheck()

    rows = session.execute(
        select(Photograph)
        .join(PostAsset, PostAsset.photograph_id == Photograph.id)
        .where(PostAsset.post_id == post.id)
    ).scalars()

    for photograph in rows:
        if photograph.latitude is not None and photograph.longitude is not None:
            check.findings.append(
                LocationFinding(
                    kind="photo_gps",
                    detail=(
                        f"{photograph.original_filename or photograph.title} carries GPS coordinates "
                        f"from the camera. Publishing the file as it stands tells anyone "
                        f"who downloads it where this was taken."
                    ),
                    photograph_id=photograph.id,
                )
            )

    if post.resource_type is ResourceType.SITE and post.resource_id is not None:
        site = session.get(Site, post.resource_id)
        if site is not None and not site.is_public:
            check.findings.append(
                LocationFinding(
                    kind="private_site",
                    detail=(
                        f"{site.name} is not published in this platform. A post about it "
                        f"puts it in public before the record is."
                    ),
                )
            )

    if post.reveals_location:
        check.findings.append(
            LocationFinding(
                kind="declared",
                detail="Somebody has marked this post as showing where a site is.",
            )
        )

    return check


def record_location_check(session: Session, post: SocialPost) -> LocationCheck:
    """Run the check and keep what it found on the post.

    Stored so the warning survives a page reload and shows up in a list — a
    warning that only exists on the screen where it was raised is a warning
    somebody scrolls past once and never sees again.
    """
    check = check_location_disclosure(session, post)
    post.location_warning = check.summary()
    session.flush()
    return check


# --------------------------------------------------------------------------
# Engagement
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Engagement:
    """The latest reading for a post, and how it moved."""

    recorded_at: datetime | None = None
    impressions: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    #: Total interactions, for ranking posts against each other. ``None`` when
    #: the platform reported none of them, which is not the same as zero.
    interactions: int | None = None
    #: Change in interactions since the previous reading, so a list can say
    #: whether something is still moving.
    change: int | None = None
    readings: int = 0


def _interactions(metric: PostMetric) -> int | None:
    parts = [metric.likes, metric.comments, metric.shares, metric.saves]
    known = [value for value in parts if value is not None]
    return sum(known) if known else None


def engagement(session: Session, post_id: uuid.UUID) -> Engagement:
    """The most recent reading, with the movement since the one before it."""
    readings = list(
        session.scalars(
            select(PostMetric)
            .where(PostMetric.post_id == post_id)
            .order_by(PostMetric.recorded_at.desc())
            .limit(2)
        ).all()
    )
    if not readings:
        return Engagement()

    latest = readings[0]
    current = _interactions(latest)
    previous = _interactions(readings[1]) if len(readings) > 1 else None
    count = (
        session.scalar(
            select(func.count()).select_from(PostMetric).where(PostMetric.post_id == post_id)
        )
        or 0
    )

    return Engagement(
        recorded_at=latest.recorded_at,
        impressions=latest.impressions,
        likes=latest.likes,
        comments=latest.comments,
        shares=latest.shares,
        interactions=current,
        change=(current - previous) if current is not None and previous is not None else None,
        readings=count,
    )


# --------------------------------------------------------------------------
# Publishing
# --------------------------------------------------------------------------
class OutreachError(Exception):
    """Something the repository refuses to record."""


def mark_published(
    session: Session,
    post: SocialPost,
    *,
    url: str | None = None,
    external_id: str | None = None,
    when: datetime | None = None,
) -> SocialPost:
    """Record that a post went out.

    The platform does not publish for you. It has no API keys, and an
    institution's outreach account is not something a records system should be
    able to post from unattended — so this records what a person did, which is
    the part worth archiving.
    """
    if post.status is PostStatus.WITHDRAWN:
        raise OutreachError(
            "That post was withdrawn. Copy it into a new one rather than reviving it."
        )

    post.status = PostStatus.PUBLISHED
    post.published_at = when or datetime.now(UTC)
    if url:
        post.external_url = url
    if external_id:
        post.external_id = external_id
    session.flush()
    return post
