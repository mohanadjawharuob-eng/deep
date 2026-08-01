"""Geometry handling: validation, reprojection and extents.

Everything is stored in **EPSG:4326** — longitude and latitude in degrees,
which is what Leaflet and every web map expect. Files rarely arrive that way.
A site grid is almost always recorded in a projected national or UTM system,
because you cannot measure a trench in degrees.

That mismatch is the single most common way archaeological GIS data is
silently corrupted: eastings and northings in the hundreds of thousands, read
as if they were degrees, land the site off the coast of Africa at 0°N 0°E or
are rejected outright. So this module never guesses. Either the coordinates
are plausible as degrees, or a source SRID is supplied and PostGIS reprojects,
or the import is refused with a message naming what was found.

PostGIS carries the whole EPSG registry in ``spatial_ref_sys``, so
reprojection needs no Python dependency at all — ``ST_Transform`` does it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select, text
from sqlalchemy.orm import Session

#: What everything is stored as. Web maps speak this and nothing else.
STORAGE_SRID = 4326

#: Geometry types accepted from a file. Anything else — curves, TINs,
#: polyhedral surfaces — is real GIS but not something this platform renders,
#: and silently dropping it would be worse than refusing it.
ALLOWED_GEOMETRY_TYPES = frozenset(
    {
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
        "GeometryCollection",
    }
)

#: Caps on a single import. A layer beyond this is a basemap, not a record
#: set, and belongs in a tile server rather than in rows.
MAX_FEATURES = 50_000
MAX_COORDINATES_PER_FEATURE = 500_000


class GeometryError(ValueError):
    """The geometry cannot be used. The message is safe to show a user."""


@dataclass(frozen=True)
class Extent:
    """A bounding box in storage coordinates."""

    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    def as_list(self) -> list[float]:
        return [self.min_lon, self.min_lat, self.max_lon, self.max_lat]


def looks_like_degrees(coordinates: Any) -> bool:
    """Whether every coordinate pair could plausibly be longitude/latitude.

    Not proof — a UTM easting of 300000 is obviously not degrees, but a local
    site grid running 0–100 metres looks exactly like a point off the coast of
    Ghana. This catches the blatant case; the ambiguous one is why an explicit
    source SRID exists.
    """
    for longitude, latitude in _walk_positions(coordinates):
        if not (-180.0 <= longitude <= 180.0 and -90.0 <= latitude <= 90.0):
            return False
    return True


def _walk_positions(coordinates: Any) -> Any:
    """Yield every ``(x, y)`` pair in an arbitrarily nested coordinate array."""
    if not isinstance(coordinates, list | tuple) or not coordinates:
        return
    first = coordinates[0]
    if isinstance(first, int | float):
        if len(coordinates) >= 2:
            yield float(coordinates[0]), float(coordinates[1])
        return
    for item in coordinates:
        yield from _walk_positions(item)


def count_positions(coordinates: Any) -> int:
    return sum(1 for _ in _walk_positions(coordinates))


def validate_geojson_geometry(geometry: Any) -> dict[str, Any]:
    """Check one GeoJSON geometry object and return it.

    Raises :class:`GeometryError` with a message safe to show the uploader.
    """
    if not isinstance(geometry, dict):
        raise GeometryError("A feature's geometry must be a GeoJSON object")

    geometry_type = geometry.get("type")
    if geometry_type not in ALLOWED_GEOMETRY_TYPES:
        raise GeometryError(
            f"{geometry_type or 'That'} is not a supported geometry type. "
            f"Supported: {', '.join(sorted(ALLOWED_GEOMETRY_TYPES))}."
        )

    if geometry_type == "GeometryCollection":
        members = geometry.get("geometries")
        if not isinstance(members, list) or not members:
            raise GeometryError("A GeometryCollection needs a non-empty 'geometries' list")
        for member in members:
            validate_geojson_geometry(member)
        return geometry

    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        raise GeometryError(f"A {geometry_type} needs a non-empty 'coordinates' array")

    positions = count_positions(coordinates)
    if positions == 0:
        raise GeometryError(f"That {geometry_type} has no usable coordinates")
    if positions > MAX_COORDINATES_PER_FEATURE:
        raise GeometryError(
            f"A single feature with {positions:,} coordinates is beyond what this "
            f"platform stores as a record. Simplify it, or serve it as a tile layer."
        )
    return geometry


def resolve_srid(
    session: Session, *, declared: int | None, sample_coordinates: Any, crs_hint: str | None
) -> int:
    """Decide which SRID the incoming coordinates are in.

    Refuses rather than guesses. Getting this wrong does not raise an error
    later — it silently relocates a site by hundreds of kilometres, and the
    map looks plausible until somebody visits.
    """
    if declared is not None:
        if not srid_exists(session, declared):
            raise GeometryError(
                f"EPSG:{declared} is not in this database's spatial reference table. "
                f"Check the code, or convert the file to EPSG:4326 before uploading."
            )
        # A declaration of WGS84 over coordinates that cannot be degrees is a
        # file contradicting itself — most often a shapefile re-projected in a
        # GIS whose .prj was never updated. Trusting the declaration stores
        # eastings as longitudes, which PostGIS accepts without complaint and
        # nothing downstream ever questions.
        if declared == STORAGE_SRID and not looks_like_degrees(sample_coordinates):
            raise GeometryError(
                "This file says it is in longitude/latitude (EPSG:4326), but its "
                "coordinates are far outside that range — they look like a "
                "projected grid. The file contradicts itself, most often because "
                "it was reprojected without its .prj being updated. Send the "
                "real EPSG code as 'source_srid'."
            )
        return declared

    if looks_like_degrees(sample_coordinates):
        return STORAGE_SRID

    found = crs_hint or "a projected coordinate system"
    raise GeometryError(
        f"These coordinates are not longitude and latitude — they look like "
        f"{found}. Re-send with 'source_srid' set to the file's EPSG code "
        f"(for example 32636 for UTM zone 36N), or convert the file to "
        f"EPSG:4326 first. Guessing would put the site in the wrong place."
    )


def srid_exists(session: Session, srid: int) -> bool:
    return bool(
        session.scalar(
            text("SELECT 1 FROM spatial_ref_sys WHERE srid = :srid").bindparams(srid=srid)
        )
    )


def srid_name(session: Session, srid: int) -> str | None:
    """A readable name for an SRID, for recording the file's provenance."""
    row = session.execute(
        text("SELECT auth_name, auth_srid FROM spatial_ref_sys WHERE srid = :srid").bindparams(
            srid=srid
        )
    ).first()
    if row is None:
        return None
    return f"{row[0]}:{row[1]}"


def srid_from_wkt(session: Session, wkt: str | None) -> int | None:
    """Best-effort SRID for a shapefile's ``.prj`` text.

    Matched against the projection names PostGIS already carries, so no
    projection library is needed. Returns ``None`` when it cannot be matched
    with confidence — the caller then asks rather than assuming.
    """
    if not wkt or not wkt.strip():
        return None

    name = _projection_name(wkt)
    if name is None:
        return None

    # WGS 84 has many spellings and is worth short-circuiting: it is by far the
    # most common .prj in the wild and the one that needs no transform.
    normalised = name.replace("_", " ").strip().lower()
    if normalised in ("wgs 84", "wgs84", "gcs wgs 1984", "wgs 1984"):
        return STORAGE_SRID

    match = session.scalar(
        text(
            "SELECT srid FROM spatial_ref_sys "
            "WHERE lower(replace(srtext, '_', ' ')) LIKE :pattern "
            "ORDER BY srid LIMIT 1"
        ).bindparams(pattern=f'%"{normalised}"%')
    )
    return int(match) if match is not None else None


def _projection_name(wkt: str) -> str | None:
    """The quoted name that follows PROJCS or GEOGCS in a ``.prj``."""
    for keyword in ("PROJCS", "GEOGCS"):
        marker = wkt.find(keyword)
        if marker == -1:
            continue
        opening = wkt.find('"', marker)
        closing = wkt.find('"', opening + 1)
        if opening != -1 and closing != -1:
            return wkt[opening + 1 : closing]
    return None


# --------------------------------------------------------------------------
# Conversion, done in the database
# --------------------------------------------------------------------------
def geometry_element(geometry: dict[str, Any], srid: int):
    """A SQL expression producing a storage-SRID geometry from GeoJSON.

    The reprojection happens in PostGIS rather than Python: it carries the
    EPSG registry already, and a transform done anywhere else is one more
    place for the datum to be wrong.
    """
    payload = json.dumps(geometry)
    element = func.ST_SetSRID(func.ST_GeomFromGeoJSON(payload), srid)
    if srid != STORAGE_SRID:
        element = func.ST_Transform(element, STORAGE_SRID)
    # Repairs self-intersections and unclosed rings, which hand-drawn survey
    # polygons routinely contain and which make later spatial queries error.
    return func.ST_MakeValid(element)


def to_geojson(session: Session, geometry_column: Any, *, decimals: int = 7) -> Any:
    """Expression rendering a stored geometry back to GeoJSON.

    Seven decimal places is roughly a centimetre — beyond survey precision,
    and far short of the seventeen digits a naive float dump produces.
    """
    return func.ST_AsGeoJSON(geometry_column, decimals)


def extent_of(session: Session, layer_id: Any) -> Extent | None:
    """The bounding box of every feature in a layer."""
    from app.models.gis import GisFeature

    row = session.execute(
        select(
            func.ST_XMin(func.ST_Extent(GisFeature.geom)),
            func.ST_YMin(func.ST_Extent(GisFeature.geom)),
            func.ST_XMax(func.ST_Extent(GisFeature.geom)),
            func.ST_YMax(func.ST_Extent(GisFeature.geom)),
        ).where(GisFeature.layer_id == layer_id)
    ).first()

    if row is None or row[0] is None:
        return None
    return Extent(float(row[0]), float(row[1]), float(row[2]), float(row[3]))


def parse_bbox(raw: str) -> Extent:
    """``minLon,minLat,maxLon,maxLat`` into an extent."""
    parts = raw.split(",")
    if len(parts) != 4:
        raise GeometryError("bbox must be four numbers: minLon,minLat,maxLon,maxLat")
    try:
        min_lon, min_lat, max_lon, max_lat = (float(part) for part in parts)
    except ValueError as exc:
        raise GeometryError("bbox must be four numbers: minLon,minLat,maxLon,maxLat") from exc

    if min_lon > max_lon or min_lat > max_lat:
        raise GeometryError("bbox minimum exceeds its maximum")
    if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
        raise GeometryError("bbox longitudes must be between -180 and 180")
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        raise GeometryError("bbox latitudes must be between -90 and 90")
    return Extent(min_lon, min_lat, max_lon, max_lat)


def bbox_filter(column: Any, extent: Extent) -> Any:
    """Rows whose geometry intersects an extent, using the spatial index."""
    envelope = func.ST_MakeEnvelope(
        extent.min_lon, extent.min_lat, extent.max_lon, extent.max_lat, STORAGE_SRID
    )
    # && is the index-accelerated bounding-box overlap operator.
    return column.op("&&")(envelope)


def within_metres(column: Any, longitude: float, latitude: float, metres: float) -> Any:
    """Rows within a true-distance radius of a point.

    Cast to ``geography`` so the radius is metres on the ellipsoid rather than
    degrees, which are worth ~111 km of latitude but shrink to nothing near
    the poles — a degree-based radius silently changes size with the map.
    """
    point = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), STORAGE_SRID)
    return func.ST_DWithin(cast(column, Geography), cast(point, Geography), metres)


def distance_metres(column: Any, longitude: float, latitude: float) -> Any:
    """Great-circle distance in metres, for sorting by nearest."""
    point = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), STORAGE_SRID)
    return func.ST_Distance(cast(column, Geography), cast(point, Geography))


def within_geometry(column: Any, geometry: dict[str, Any], srid: int = STORAGE_SRID) -> Any:
    """Rows whose geometry falls inside a supplied polygon."""
    element = func.ST_SetSRID(func.ST_GeomFromGeoJSON(json.dumps(geometry)), srid)
    if srid != STORAGE_SRID:
        element = func.ST_Transform(element, STORAGE_SRID)
    return func.ST_Within(column, func.ST_MakeValid(element))
