"""Site CRUD."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, CurrentUserOptional, DbSession
from app.core.permissions import (
    can_delete,
    can_edit,
    can_view,
    visibility_filter,
)
from app.models.artifact import Artifact
from app.models.context import ExcavationContext
from app.models.enums import ProtectionStatus, ResourceType, ReviewStatus, SiteType
from app.models.site import Site
from app.models.user import User
from app.schemas.common import Message, Page
from app.schemas.site import SiteCreate, SiteDetail, SiteSummary, SiteUpdate
from app.services import records

router = APIRouter(prefix="/sites", tags=["Sites"])

RESOURCE = ResourceType.SITE
#: How far a restricted coordinate is degraded before publication. Roughly a
#: kilometre — enough to place a site in its landscape, not enough to find it.
RESTRICTED_PRECISION = 2


def _detail(session: DbSession, site: Site, user: User | None) -> SiteDetail:
    artifact_count = (
        session.scalar(
            select(func.count()).select_from(Artifact).where(Artifact.site_id == site.id)
        )
        or 0
    )
    context_count = (
        session.scalar(
            select(func.count())
            .select_from(ExcavationContext)
            .where(ExcavationContext.site_id == site.id)
        )
        or 0
    )
    detail = SiteDetail.model_validate(site)
    detail.artifact_count = artifact_count
    detail.context_count = context_count
    detail.can_edit = can_edit(session, user, site, RESOURCE)
    detail.can_delete = can_delete(session, user, site, RESOURCE)
    return _mask_location(session, detail, site, user)


def _mask_location(
    session: DbSession, payload: SiteSummary, site: Site, user: User | None
) -> SiteSummary:
    """Blur the coordinates of a protected site for users who cannot edit it.

    Looting follows publication. When a site is flagged ``location_restricted``,
    outsiders get a rounded position — enough to show it on a regional map —
    while the team keeps the surveyed coordinate.
    """
    if not site.location_restricted:
        return payload
    if user is not None and can_edit(session, user, site, RESOURCE):
        return payload

    if payload.latitude is not None:
        payload.latitude = round(payload.latitude, RESTRICTED_PRECISION)
    if payload.longitude is not None:
        payload.longitude = round(payload.longitude, RESTRICTED_PRECISION)
    return payload


@router.get(
    "",
    response_model=Page[SiteSummary],
    summary="List sites",
    description=(
        "Sites visible to the caller. Supports filtering by project, type, "
        "period, protection status and geography, and a bounding box for the "
        "map. Coordinates of restricted sites are rounded for non-members."
    ),
)
def list_sites(
    session: DbSession,
    user: CurrentUserOptional,
    q: Annotated[str | None, Query(description="Match name, code or alternative names")] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    site_type: Annotated[SiteType | None, Query()] = None,
    protection_status: Annotated[ProtectionStatus | None, Query()] = None,
    period_id: Annotated[uuid.UUID | None, Query()] = None,
    country: Annotated[str | None, Query()] = None,
    region: Annotated[str | None, Query()] = None,
    date_from: Annotated[int | None, Query(description="Earliest year; negative is BCE")] = None,
    date_to: Annotated[int | None, Query(description="Latest year; negative is BCE")] = None,
    bbox: Annotated[
        str | None,
        Query(description="Bounding box as `minLon,minLat,maxLon,maxLat`"),
    ] = None,
    review_status: Annotated[ReviewStatus | None, Query()] = None,
    sort: Annotated[str, Query(pattern="^-?(name|code|created_at|date_from)$")] = "name",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[SiteSummary]:
    statement = select(Site).where(visibility_filter(user, Site, RESOURCE))

    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Site.name).like(pattern),
                func.lower(Site.code).like(pattern),
                # ARRAY(...)::text catches any alternative spelling without a
                # separate join or an unnest.
                func.lower(func.array_to_string(Site.alternative_names, " ")).like(pattern),
            )
        )
    if project_id is not None:
        statement = statement.where(Site.project_id == project_id)
    if site_type is not None:
        statement = statement.where(Site.site_type == site_type)
    if protection_status is not None:
        statement = statement.where(Site.protection_status == protection_status)
    if period_id is not None:
        statement = statement.where(Site.period_id == period_id)
    if country:
        statement = statement.where(func.lower(Site.country) == country.lower())
    if region:
        statement = statement.where(func.lower(Site.region).like(f"%{region.lower()}%"))
    if review_status is not None:
        statement = statement.where(Site.review_status == review_status)

    # Overlap, not containment: a site dated 3000–2000 BCE is a hit for a
    # search of 2500–2400 BCE even though neither range contains the other.
    if date_from is not None:
        statement = statement.where(or_(Site.date_to.is_(None), Site.date_to >= date_from))
    if date_to is not None:
        statement = statement.where(or_(Site.date_from.is_(None), Site.date_from <= date_to))

    if bbox:
        min_lon, min_lat, max_lon, max_lat = _parse_bbox(bbox)
        statement = statement.where(
            Site.longitude.between(min_lon, max_lon),
            Site.latitude.between(min_lat, max_lat),
        )

    descending = sort.startswith("-")
    column = getattr(Site, sort.lstrip("-"))
    statement = statement.order_by(column.desc() if descending else column.asc())

    rows, total = records.paginate(session, statement, limit, offset)
    items = [_mask_location(session, SiteSummary.model_validate(row), row, user) for row in rows]
    return Page[SiteSummary](items=items, total=total, limit=limit, offset=offset)


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        min_lon, min_lat, max_lon, max_lat = (float(part) for part in bbox.split(","))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="bbox must be four numbers: minLon,minLat,maxLon,maxLat",
        ) from exc
    if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="bbox longitude out of range"
        )
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="bbox latitude out of range"
        )
    if min_lon > max_lon or min_lat > max_lat:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="bbox minimum exceeds its maximum"
        )
    return min_lon, min_lat, max_lon, max_lat


@router.post(
    "",
    response_model=SiteDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a site",
    description=(
        "Records created by students enter the approval queue; those created "
        "by researchers and administrators are approved immediately."
    ),
    responses={409: {"description": "Site code already used in this project"}},
)
def create_site(
    payload: SiteCreate, session: DbSession, request: Request, user: CurrentUser
) -> SiteDetail:
    records.check_can_contribute(session, user, payload.project_id)

    clash = session.scalar(
        select(Site.id).where(Site.project_id == payload.project_id, Site.code == payload.code)
    )
    if clash is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Site code {payload.code!r} is already used in this project",
        )

    site = Site(
        **payload.model_dump(),
        owner_id=user.id,
        review_status=records.initial_review_status(user),
    )
    records.sync_point_geometry(site)
    session.add(site)
    session.flush()

    records.on_created(session, site, RESOURCE, user=user, request=request)
    session.flush()
    return _detail(session, site, user)


@router.get(
    "/{site_id}",
    response_model=SiteDetail,
    summary="Read a site",
    responses={404: {"description": "No such site, or not visible to you"}},
)
def read_site(site_id: uuid.UUID, session: DbSession, user: CurrentUserOptional) -> SiteDetail:
    site = records.get_or_404(session, Site, site_id, "Site")
    if not can_view(session, user, site, RESOURCE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Site not found")
    return _detail(session, site, user)


@router.patch(
    "/{site_id}",
    response_model=SiteDetail,
    summary="Update a site",
    responses={403: {"description": "You may not edit this site"}},
)
def update_site(
    site_id: uuid.UUID,
    payload: SiteUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> SiteDetail:
    site = records.get_or_404(session, Site, site_id, "Site")
    if not can_view(session, user, site, RESOURCE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Site not found")
    if not can_edit(session, user, site, RESOURCE):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You may not edit this site")

    changes = payload.model_dump(exclude_unset=True)

    if "code" in changes and changes["code"] != site.code:
        clash = session.scalar(
            select(Site.id).where(
                Site.project_id == site.project_id,
                Site.code == changes["code"],
                Site.id != site.id,
            )
        )
        if clash is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"Site code {changes['code']!r} is already used in this project",
            )

    # Coordinates are validated as a pair against the *resulting* state, so
    # sending only a new latitude cannot leave a half-set position behind.
    latitude = changes.get("latitude", site.latitude)
    longitude = changes.get("longitude", site.longitude)
    try:
        records.validate_coordinates(latitude, longitude)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    before = records.apply_changes(site, changes)
    if "latitude" in before or "longitude" in before:
        records.sync_point_geometry(site)

    records.on_updated(session, site, RESOURCE, before=before, user=user, request=request)
    session.flush()
    return _detail(session, site, user)


@router.delete(
    "/{site_id}",
    response_model=Message,
    summary="Delete a site",
    description="Removes the site with its artifacts and contexts. The final state is kept in the revision history.",
    responses={403: {"description": "You may not delete this site"}},
)
def delete_site(
    site_id: uuid.UUID, session: DbSession, request: Request, user: CurrentUser
) -> Message:
    site = records.get_or_404(session, Site, site_id, "Site")
    if not can_view(session, user, site, RESOURCE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Site not found")
    if not can_delete(session, user, site, RESOURCE):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You may not delete this site")

    label = site.name
    records.on_deleted(session, site, RESOURCE, user=user, request=request, label=label)
    session.delete(site)
    return Message(detail=f"Site {label!r} deleted")
