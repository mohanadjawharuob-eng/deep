"""Spatial search across everything that has a location.

Three questions, each asked of sites, artifacts, contexts and GIS features at
once:

- *What is near here?* — a radius in metres around a point.
- *What is in this box?* — the map's current viewport.
- *What is inside this shape?* — a supplied polygon, which is how a survey area
  or a modern development boundary is queried against the record.

All three run in PostGIS against the spatial index. Filtering in Python would
mean loading every located record in the database to discard most of them.

Restricted site coordinates are blurred here exactly as they are in the site
endpoints and in search. A spatial query is the most direct way a restricted
location would otherwise escape: asking "what is within 50 metres of this
point" and getting an exact answer defeats the blurring entirely, so the
*results* are rounded and, for a restricted site, the caller is not told the
distance either.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import String, func, literal, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserOptional, DbSession
from app.core.permissions import can_edit, visibility_filter
from app.models.artifact import Artifact
from app.models.context import ExcavationContext
from app.models.enums import ResourceType
from app.models.gis import GisFeature, GisLayer
from app.models.site import Site
from app.models.user import User
from app.schemas.gis import SpatialHit, SpatialSearchResult
from app.services import geo

router = APIRouter(prefix="/spatial", tags=["Spatial search"])

#: Decimal places a restricted site's coordinates are reduced to — about a
#: kilometre. Imported from the site endpoints so the two cannot drift.
from app.api.v1.endpoints.sites import RESTRICTED_PRECISION  # noqa: E402

#: The largest radius worth serving. Beyond this it is a country-wide query and
#: belongs in the ordinary search endpoint with a bounding box.
MAX_RADIUS_M = 500_000


class WithinRequest(BaseModel):
    """A polygon to search inside."""

    geometry: dict[str, Any] = Field(
        description="A GeoJSON Polygon or MultiPolygon",
        examples=[
            {
                "type": "Polygon",
                "coordinates": [
                    [[35.8, 32.5], [35.9, 32.5], [35.9, 32.6], [35.8, 32.6], [35.8, 32.5]]
                ],
            }
        ],
    )
    source_srid: int | None = Field(
        default=None, description="EPSG code of the polygon, if not longitude/latitude"
    )
    types: list[ResourceType] | None = Field(
        default=None, description="Restrict to these record types"
    )
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


def _translate(error: geo.GeometryError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))


def _blur(value: float | None, restricted: bool) -> float | None:
    if value is None:
        return None
    return round(float(value), RESTRICTED_PRECISION) if restricted else float(value)


def _site_restrictions(session: Session, user: User | None, site_ids: set[uuid.UUID]) -> set:
    """Which of these sites must have their coordinates blurred for this user.

    One query for the batch rather than a permission check per row: a viewport
    query returns hundreds of records and per-row checks would be the slowest
    part of the request.
    """
    if not site_ids:
        return set()

    restricted = list(
        session.scalars(
            select(Site).where(Site.id.in_(site_ids), Site.location_restricted.is_(True))
        ).all()
    )
    return {site.id for site in restricted if not can_edit(session, user, site, ResourceType.SITE)}


# --------------------------------------------------------------------------
# The per-type queries
# --------------------------------------------------------------------------
def _site_query(user: User | None, centre: tuple[float, float] | None) -> Any:
    distance = geo.distance_metres(Site.geom, centre[0], centre[1]) if centre else literal(None)
    return select(
        literal(ResourceType.SITE.value).label("resource_type"),
        Site.id.label("id"),
        Site.name.label("label"),
        Site.latitude.label("latitude"),
        Site.longitude.label("longitude"),
        Site.project_id.label("project_id"),
        Site.id.label("site_id"),
        distance.label("distance_m"),
    ).where(
        visibility_filter(user, Site, ResourceType.SITE),
        Site.geom.is_not(None),
    )


def _artifact_query(user: User | None, centre: tuple[float, float] | None) -> Any:
    distance = geo.distance_metres(Artifact.geom, centre[0], centre[1]) if centre else literal(None)
    return (
        select(
            literal(ResourceType.ARTIFACT.value).label("resource_type"),
            Artifact.id.label("id"),
            func.coalesce(Artifact.inventory_number, Artifact.name).label("label"),
            Artifact.latitude.label("latitude"),
            Artifact.longitude.label("longitude"),
            Site.project_id.label("project_id"),
            Artifact.site_id.label("site_id"),
            distance.label("distance_m"),
        )
        .join(Site, Site.id == Artifact.site_id)
        .where(
            visibility_filter(user, Artifact, ResourceType.ARTIFACT),
            Artifact.geom.is_not(None),
        )
    )


def _context_query(user: User | None, centre: tuple[float, float] | None) -> Any:
    distance = (
        geo.distance_metres(ExcavationContext.geom, centre[0], centre[1])
        if centre
        else literal(None)
    )
    return (
        select(
            literal(ResourceType.CONTEXT.value).label("resource_type"),
            ExcavationContext.id.label("id"),
            ExcavationContext.context_number.label("label"),
            ExcavationContext.latitude.label("latitude"),
            ExcavationContext.longitude.label("longitude"),
            Site.project_id.label("project_id"),
            ExcavationContext.site_id.label("site_id"),
            distance.label("distance_m"),
        )
        .join(Site, Site.id == ExcavationContext.site_id)
        .where(
            visibility_filter(user, ExcavationContext, ResourceType.CONTEXT),
            ExcavationContext.geom.is_not(None),
        )
    )


def _feature_query(user: User | None, centre: tuple[float, float] | None) -> Any:
    """GIS features, scoped by the visibility of the layer that holds them."""
    distance = (
        geo.distance_metres(GisFeature.geom, centre[0], centre[1]) if centre else literal(None)
    )
    centroid = func.ST_Centroid(GisFeature.geom)
    return (
        select(
            literal(ResourceType.GIS_LAYER.value).label("resource_type"),
            GisFeature.id.label("id"),
            func.coalesce(GisFeature.name, func.cast(GisFeature.id, String)).label("label"),
            func.ST_Y(centroid).label("latitude"),
            func.ST_X(centroid).label("longitude"),
            GisLayer.project_id.label("project_id"),
            GisLayer.site_id.label("site_id"),
            distance.label("distance_m"),
        )
        .join(GisLayer, GisLayer.id == GisFeature.layer_id)
        .where(visibility_filter(user, GisLayer, ResourceType.GIS_LAYER))
    )


#: Which column each query type measures against, for the spatial predicate.
_GEOMETRY_OF = {
    ResourceType.SITE: Site.geom,
    ResourceType.ARTIFACT: Artifact.geom,
    ResourceType.CONTEXT: ExcavationContext.geom,
    ResourceType.GIS_LAYER: GisFeature.geom,
}

_QUERY_OF = {
    ResourceType.SITE: _site_query,
    ResourceType.ARTIFACT: _artifact_query,
    ResourceType.CONTEXT: _context_query,
    ResourceType.GIS_LAYER: _feature_query,
}

SEARCHABLE_TYPES = tuple(_QUERY_OF)


def _run(
    session: DbSession,
    user: User | None,
    *,
    predicate_for: Any,
    centre: tuple[float, float] | None,
    types: list[ResourceType] | None,
    limit: int,
    offset: int,
) -> tuple[list[SpatialHit], int]:
    """Run one spatial predicate across every requested record type."""
    wanted = [kind for kind in SEARCHABLE_TYPES if types is None or kind in types]
    if not wanted:
        return [], 0

    parts = [
        _QUERY_OF[kind](user, centre).where(predicate_for(_GEOMETRY_OF[kind])) for kind in wanted
    ]
    combined = parts[0].union_all(*parts[1:]) if len(parts) > 1 else parts[0]
    subquery = combined.subquery()

    total = session.scalar(select(func.count()).select_from(subquery)) or 0

    # Nearest first when there is a centre; otherwise a stable order, with the
    # id as tiebreaker so paging cannot repeat or skip a row.
    order = (
        (subquery.c.distance_m.asc(), subquery.c.id.asc())
        if centre
        else (subquery.c.resource_type.asc(), subquery.c.label.asc(), subquery.c.id.asc())
    )
    rows = list(
        session.execute(select(subquery).order_by(*order).limit(limit).offset(offset)).all()
    )

    site_ids = {row.site_id for row in rows if row.site_id is not None}
    blurred = _site_restrictions(session, user, site_ids)

    hits: list[SpatialHit] = []
    for row in rows:
        is_blurred = row.site_id in blurred
        hits.append(
            SpatialHit(
                resource_type=ResourceType(row.resource_type),
                id=row.id,
                label=row.label or str(row.id),
                latitude=_blur(row.latitude, is_blurred),
                longitude=_blur(row.longitude, is_blurred),
                # A precise distance from a known point would undo the blurring
                # in one subtraction, so it is withheld rather than rounded.
                distance_m=None
                if is_blurred or row.distance_m is None
                else round(float(row.distance_m), 1),
                project_id=row.project_id,
                site_id=row.site_id,
                is_approximate=is_blurred,
            )
        )
    return hits, total


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@router.get(
    "/nearby",
    response_model=SpatialSearchResult,
    summary="What is near a point",
    description=(
        "Everything within `radius_m` metres of a longitude/latitude, nearest "
        "first, across sites, artifacts, contexts and GIS features.\n\n"
        "The radius is true metres on the ellipsoid, not degrees — a degree of "
        "longitude is 111 km at the equator and nothing at the pole, so a "
        "degree-based radius would silently change size with latitude."
    ),
)
def nearby(
    session: DbSession,
    user: CurrentUserOptional,
    lat: Annotated[float, Query(ge=-90, le=90, description="Latitude of the centre")],
    lon: Annotated[float, Query(ge=-180, le=180, description="Longitude of the centre")],
    radius_m: Annotated[float, Query(gt=0, le=MAX_RADIUS_M)] = 1000,
    types: Annotated[list[ResourceType] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SpatialSearchResult:
    hits, total = _run(
        session,
        user,
        predicate_for=lambda column: geo.within_metres(column, lon, lat, radius_m),
        centre=(lon, lat),
        types=types,
        limit=limit,
        offset=offset,
    )
    return SpatialSearchResult(
        items=hits,
        total=total,
        limit=limit,
        offset=offset,
        centre=[lon, lat],
        radius_m=radius_m,
    )


@router.get(
    "/bbox",
    response_model=SpatialSearchResult,
    summary="What is in a box",
    description=(
        "Everything overlapping `minLon,minLat,maxLon,maxLat`. This is what a "
        "map calls as the user pans: the bounding-box operator is index-"
        "accelerated, so the cost tracks what is on screen rather than what is "
        "in the database."
    ),
)
def in_bbox(
    session: DbSession,
    user: CurrentUserOptional,
    bbox: Annotated[str, Query(description="minLon,minLat,maxLon,maxLat")],
    types: Annotated[list[ResourceType] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SpatialSearchResult:
    try:
        extent = geo.parse_bbox(bbox)
    except geo.GeometryError as exc:
        raise _translate(exc) from exc

    hits, total = _run(
        session,
        user,
        predicate_for=lambda column: geo.bbox_filter(column, extent),
        centre=None,
        types=types,
        limit=limit,
        offset=offset,
    )
    return SpatialSearchResult(
        items=hits, total=total, limit=limit, offset=offset, bbox=extent.as_list()
    )


@router.post(
    "/within",
    response_model=SpatialSearchResult,
    summary="What is inside a shape",
    description=(
        "Everything falling inside a supplied polygon — a survey area, a "
        "development boundary, a protected zone. Sent as a POST because a "
        "polygon does not belong in a query string.\n\n"
        "A polygon in a projected coordinate system is reprojected when "
        "`source_srid` is given, and refused rather than misread when it is "
        "not."
    ),
    responses={422: {"description": "Not a usable polygon, or an ambiguous coordinate system"}},
)
def within(
    payload: WithinRequest, session: DbSession, user: CurrentUserOptional
) -> SpatialSearchResult:
    try:
        geometry = geo.validate_geojson_geometry(payload.geometry)
        if geometry["type"] not in ("Polygon", "MultiPolygon"):
            raise geo.GeometryError(
                f"Searching inside a {geometry['type']} is not meaningful — "
                f"send a Polygon or MultiPolygon."
            )
        srid = geo.resolve_srid(
            session,
            declared=payload.source_srid,
            sample_coordinates=geometry.get("coordinates"),
            crs_hint=None,
        )
    except geo.GeometryError as exc:
        raise _translate(exc) from exc

    hits, total = _run(
        session,
        user,
        predicate_for=lambda column: geo.within_geometry(column, geometry, srid),
        centre=None,
        types=payload.types,
        limit=payload.limit,
        offset=payload.offset,
    )
    return SpatialSearchResult(items=hits, total=total, limit=payload.limit, offset=payload.offset)
