"""GIS layers, their features, and interchange with the outside world.

A *layer* is what a map's layer manager toggles: a trench plan, a survey grid,
a geophysics outline. A *feature* is one geometry inside it.

Reading a layer returns a literal GeoJSON ``FeatureCollection`` rather than a
paginated envelope, because the answer is handed straight to Leaflet and
wrapping it would only mean every client unwraps it again.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi import status as http_status
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, CurrentUserOptional, DbSession
from app.core.config import settings
from app.core.permissions import can_delete, can_edit, visibility_filter
from app.models.enums import ActivityAction, GeometryKind, LayerCategory, ResourceType
from app.models.gis import GisFeature, GisLayer
from app.models.site import Site
from app.models.user import User
from app.schemas.common import Message, Page
from app.schemas.gis import (
    FeatureCollection,
    FeatureCreate,
    FeatureRead,
    FeatureUpdate,
    ImportResult,
    LayerCreate,
    LayerDetail,
    LayerSummary,
    LayerUpdate,
)
from app.services import activity, attachments, geo, records
from app.services import geoformats as formats

router = APIRouter(prefix="/gis", tags=["GIS"])

RESOURCE = ResourceType.GIS_LAYER

#: Which geometry kinds a set of features amounts to, for the layer's own
#: ``geometry_kind`` — used to pick a renderer without reading the features.
_KIND_OF = {
    "Point": GeometryKind.POINT,
    "MultiPoint": GeometryKind.POINT,
    "LineString": GeometryKind.LINE,
    "MultiLineString": GeometryKind.LINE,
    "Polygon": GeometryKind.POLYGON,
    "MultiPolygon": GeometryKind.POLYGON,
}


def _translate(error: geo.GeometryError) -> HTTPException:
    return HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))


def _get_layer(session: DbSession, layer_id: uuid.UUID) -> GisLayer:
    return records.get_or_404(session, GisLayer, layer_id, "Layer")


def _require_readable(session: DbSession, user: User | None, layer: GisLayer) -> None:
    attachments.require_readable(session, user, layer, RESOURCE, "Layer")


def _require_editable(session: DbSession, user: User | None, layer: GisLayer) -> None:
    attachments.require_editable(session, user, layer, RESOURCE, "Layer")


def _summary(layer: GisLayer) -> LayerSummary:
    return LayerSummary.model_validate(layer)


def _detail(session: DbSession, layer: GisLayer, user: User | None) -> LayerDetail:
    payload = LayerDetail.model_validate(layer)
    payload.can_edit = can_edit(session, user, layer, RESOURCE)
    payload.can_delete = can_delete(session, user, layer, RESOURCE)
    return payload


def _refresh_layer_stats(session: DbSession, layer: GisLayer) -> None:
    """Recount features and recompute the cached extent.

    Both are denormalised so a map can list layers and zoom to one without
    touching the feature table, which means both have to be refreshed by every
    path that changes what is in the layer.
    """
    layer.feature_count = (
        session.scalar(
            select(func.count()).select_from(GisFeature).where(GisFeature.layer_id == layer.id)
        )
        or 0
    )
    extent = geo.extent_of(session, layer.id)
    layer.bbox = extent.as_list() if extent is not None else None
    session.add(layer)


def _resolve_parents(session: DbSession, user: User, payload: LayerCreate) -> dict[str, Any]:
    """Validate the project/site a layer hangs from, as media records do."""
    links = attachments.resolve_attachment(
        session, user, project_id=payload.project_id, site_id=payload.site_id
    )
    return {"project_id": links["project_id"], "site_id": links["site_id"]}


# --------------------------------------------------------------------------
# Layers
# --------------------------------------------------------------------------
@router.post(
    "/layers",
    response_model=LayerDetail,
    status_code=http_status.HTTP_201_CREATED,
    summary="Create an empty layer",
    description=(
        "Creates a layer with no features. To create one *from a file* in a "
        "single step, use `POST /gis/import` instead."
    ),
)
def create_layer(
    payload: LayerCreate, session: DbSession, request: Request, user: CurrentUser
) -> LayerDetail:
    links = _resolve_parents(session, user, payload)
    data = payload.model_dump(exclude={"project_id", "site_id"})

    layer = GisLayer(**data, **links, owner_id=user.id)
    session.add(layer)
    session.flush()

    records.on_created(session, layer, RESOURCE, user=user, request=request)
    session.flush()
    return _detail(session, layer, user)


@router.get("/layers", response_model=Page[LayerSummary], summary="List layers")
def list_layers(
    session: DbSession,
    user: CurrentUserOptional,
    q: Annotated[str | None, Query(description="Match name or description")] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    site_id: Annotated[uuid.UUID | None, Query()] = None,
    category: Annotated[LayerCategory | None, Query()] = None,
    geometry_kind: Annotated[GeometryKind | None, Query()] = None,
    bbox: Annotated[
        str | None, Query(description="Only layers overlapping minLon,minLat,maxLon,maxLat")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[LayerSummary]:
    statement = select(GisLayer).where(visibility_filter(user, GisLayer, RESOURCE))

    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(GisLayer.name).like(pattern),
                func.lower(GisLayer.description).like(pattern),
            )
        )
    if project_id is not None:
        statement = statement.where(GisLayer.project_id == project_id)
    if site_id is not None:
        statement = statement.where(GisLayer.site_id == site_id)
    if category is not None:
        statement = statement.where(GisLayer.category == category)
    if geometry_kind is not None:
        statement = statement.where(GisLayer.geometry_kind == geometry_kind)

    if bbox:
        try:
            extent = geo.parse_bbox(bbox)
        except geo.GeometryError as exc:
            raise _translate(exc) from exc
        # Layers have no geometry of their own, so overlap is asked of their
        # features — one indexed sub-select rather than a join that would
        # duplicate a layer per matching feature.
        statement = statement.where(
            GisLayer.id.in_(
                select(GisFeature.layer_id).where(geo.bbox_filter(GisFeature.geom, extent))
            )
        )

    statement = statement.order_by(GisLayer.z_index, GisLayer.name, GisLayer.id)
    rows, total = records.paginate(session, statement, limit, offset)
    return Page[LayerSummary](
        items=[_summary(row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.get("/layers/{layer_id}", response_model=LayerDetail, summary="Read a layer")
def read_layer(layer_id: uuid.UUID, session: DbSession, user: CurrentUserOptional) -> LayerDetail:
    layer = _get_layer(session, layer_id)
    _require_readable(session, user, layer)
    return _detail(session, layer, user)


@router.patch("/layers/{layer_id}", response_model=LayerDetail, summary="Update a layer")
def update_layer(
    layer_id: uuid.UUID,
    payload: LayerUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> LayerDetail:
    layer = _get_layer(session, layer_id)
    _require_editable(session, user, layer)

    changes = payload.model_dump(exclude_unset=True)
    before = records.apply_changes(layer, changes)
    records.on_updated(session, layer, RESOURCE, before=before, user=user, request=request)
    session.flush()
    return _detail(session, layer, user)


@router.delete("/layers/{layer_id}", response_model=Message, summary="Delete a layer")
def delete_layer(
    layer_id: uuid.UUID, session: DbSession, request: Request, user: CurrentUser
) -> Message:
    layer = _get_layer(session, layer_id)
    _require_readable(session, user, layer)
    if not can_delete(session, user, layer, RESOURCE):
        raise HTTPException(http_status.HTTP_403_FORBIDDEN, detail="You may not delete this layer")

    label = layer.name
    count = layer.feature_count
    records.on_deleted(session, layer, RESOURCE, user=user, request=request, label=label)
    session.delete(layer)
    return Message(detail=f"Layer {label!r} and its {count} feature(s) deleted")


# --------------------------------------------------------------------------
# Features
# --------------------------------------------------------------------------
#: Columns a feature is read back with. ``ST_AsGeoJSON`` renders the geometry
#: in the database, so the WKB never crosses into Python.
_FEATURE_COLUMNS = (
    GisFeature.id,
    GisFeature.name,
    GisFeature.properties,
    GisFeature.style,
    GisFeature.site_id,
    GisFeature.context_id,
    GisFeature.artifact_id,
    func.ST_AsGeoJSON(GisFeature.geom, 7).label("geojson"),
)


def _read_one_feature(session: DbSession, feature_id: uuid.UUID) -> FeatureRead:
    row = session.execute(select(*_FEATURE_COLUMNS).where(GisFeature.id == feature_id)).one()
    return _as_geojson_feature(row)


def _feature_rows(
    session: DbSession, layer_id: uuid.UUID, *, extent: geo.Extent | None, limit: int, offset: int
) -> tuple[list[Any], int]:
    statement = select(*_FEATURE_COLUMNS).where(GisFeature.layer_id == layer_id)

    if extent is not None:
        statement = statement.where(geo.bbox_filter(GisFeature.geom, extent))

    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = list(
        session.execute(
            statement.order_by(GisFeature.name, GisFeature.id).limit(limit).offset(offset)
        ).all()
    )
    return rows, total


def _as_geojson_feature(row: Any) -> FeatureRead:
    properties = dict(row.properties or {})
    if row.name:
        properties.setdefault("name", row.name)
    if row.style:
        properties["_style"] = row.style
    for key, value in (
        ("site_id", row.site_id),
        ("context_id", row.context_id),
        ("artifact_id", row.artifact_id),
    ):
        if value is not None:
            properties[key] = str(value)

    return FeatureRead(
        id=row.id,
        geometry=json.loads(row.geojson),
        properties=properties,
    )


@router.get(
    "/layers/{layer_id}/features",
    response_model=FeatureCollection,
    summary="A layer's features as GeoJSON",
    description=(
        "A literal GeoJSON `FeatureCollection`, ready to hand to Leaflet.\n\n"
        "`bbox` restricts the answer to features overlapping a box, which is "
        "how a map fetches only what is on screen. `limit` still applies — a "
        "layer of fifty thousand survey points is not a single response."
    ),
)
def read_features(
    layer_id: uuid.UUID,
    session: DbSession,
    user: CurrentUserOptional,
    bbox: Annotated[str | None, Query(description="minLon,minLat,maxLon,maxLat")] = None,
    limit: Annotated[int, Query(ge=1, le=10_000)] = 2000,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FeatureCollection:
    layer = _get_layer(session, layer_id)
    _require_readable(session, user, layer)

    extent = None
    if bbox:
        try:
            extent = geo.parse_bbox(bbox)
        except geo.GeometryError as exc:
            raise _translate(exc) from exc

    rows, total = _feature_rows(session, layer_id, extent=extent, limit=limit, offset=offset)
    return FeatureCollection(
        features=[_as_geojson_feature(row) for row in rows],
        name=layer.name,
        bbox=layer.bbox,
        total=total,
    )


@router.post(
    "/layers/{layer_id}/features",
    response_model=FeatureRead,
    status_code=http_status.HTTP_201_CREATED,
    summary="Add one feature",
)
def create_feature(
    layer_id: uuid.UUID,
    payload: FeatureCreate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> FeatureRead:
    layer = _get_layer(session, layer_id)
    _require_editable(session, user, layer)

    try:
        geometry = geo.validate_geojson_geometry(payload.geometry)
        srid = geo.resolve_srid(
            session,
            declared=payload.source_srid,
            sample_coordinates=geometry.get("coordinates"),
            crs_hint=None,
        )
    except geo.GeometryError as exc:
        raise _translate(exc) from exc

    feature = GisFeature(
        layer_id=layer.id,
        name=payload.name,
        geom=geo.geometry_element(geometry, srid),
        properties=payload.properties,
        style=payload.style,
        site_id=payload.site_id,
        context_id=payload.context_id,
        artifact_id=payload.artifact_id,
    )
    session.add(feature)
    session.flush()

    _refresh_layer_stats(session, layer)
    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=layer.id,
        resource_label=layer.name,
        project_id=layer.project_id,
        summary=f"Added a feature to {layer.name!r}",
        request=request,
    )
    session.flush()

    return _read_one_feature(session, feature.id)


@router.patch(
    "/layers/{layer_id}/features/{feature_id}",
    response_model=FeatureRead,
    summary="Update one feature",
)
def update_feature(
    layer_id: uuid.UUID,
    feature_id: uuid.UUID,
    payload: FeatureUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> FeatureRead:
    layer = _get_layer(session, layer_id)
    _require_editable(session, user, layer)

    feature = session.get(GisFeature, feature_id)
    if feature is None or feature.layer_id != layer.id:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail="Feature not found")

    changes = payload.model_dump(exclude_unset=True)
    source_srid = changes.pop("source_srid", None)

    if "geometry" in changes and changes["geometry"] is not None:
        try:
            geometry = geo.validate_geojson_geometry(changes.pop("geometry"))
            srid = geo.resolve_srid(
                session,
                declared=source_srid,
                sample_coordinates=geometry.get("coordinates"),
                crs_hint=None,
            )
        except geo.GeometryError as exc:
            raise _translate(exc) from exc
        feature.geom = geo.geometry_element(geometry, srid)

    for field, value in changes.items():
        setattr(feature, field, value)
    session.add(feature)
    session.flush()

    _refresh_layer_stats(session, layer)
    session.flush()

    return _read_one_feature(session, feature.id)


@router.delete(
    "/layers/{layer_id}/features/{feature_id}",
    response_model=Message,
    summary="Delete one feature",
)
def delete_feature(
    layer_id: uuid.UUID,
    feature_id: uuid.UUID,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> Message:
    layer = _get_layer(session, layer_id)
    _require_editable(session, user, layer)

    feature = session.get(GisFeature, feature_id)
    if feature is None or feature.layer_id != layer.id:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail="Feature not found")

    session.delete(feature)
    session.flush()
    _refresh_layer_stats(session, layer)
    session.flush()
    return Message(detail="Feature deleted")


# --------------------------------------------------------------------------
# Import
# --------------------------------------------------------------------------
@router.post(
    "/import",
    response_model=ImportResult,
    status_code=http_status.HTTP_201_CREATED,
    summary="Import a GIS file as a new layer",
    description=(
        "Accepts **GeoJSON** (`.geojson`, `.json`), **KML** (`.kml`, `.kmz`) "
        "and a **zipped shapefile** (`.zip` holding at least `.shp`, `.shx` "
        "and `.dbf`). An archive containing several shapefiles is read as one "
        "layer.\n\n"
        "**Coordinate systems.** Everything is stored as longitude/latitude "
        "(EPSG:4326). If the file is in a projected system — as a site grid "
        "almost always is — give its EPSG code as `source_srid` and PostGIS "
        "reprojects. A file whose coordinates are clearly not degrees and that "
        "carries no usable `.prj` is **refused rather than guessed at**: "
        "guessing does not raise an error later, it silently puts the site in "
        "the wrong country."
    ),
    responses={
        413: {"description": "Larger than the configured upload limit"},
        422: {"description": "Unreadable, unsupported, or an ambiguous coordinate system"},
    },
)
async def import_layer(
    session: DbSession,
    request: Request,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="GeoJSON, KML/KMZ or zipped shapefile")],
    name: Annotated[str | None, Form(max_length=300)] = None,
    description: Annotated[str | None, Form()] = None,
    category: Annotated[LayerCategory, Form()] = LayerCategory.OTHER,
    project_id: Annotated[uuid.UUID | None, Form()] = None,
    site_id: Annotated[uuid.UUID | None, Form()] = None,
    source_srid: Annotated[
        int | None, Form(description="EPSG code of the file's coordinates, e.g. 32636")
    ] = None,
    is_public: Annotated[bool, Form()] = False,
) -> ImportResult:
    links = attachments.resolve_attachment(session, user, project_id=project_id, site_id=site_id)

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(
                http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"That file is larger than the {settings.MAX_UPLOAD_SIZE_MB} MB limit",
            )
    payload = bytes(data)

    from app.services.storage import extension_of

    extension = extension_of(file.filename)
    try:
        parsed, source_format = formats.read(payload, extension)
    except geo.GeometryError as exc:
        raise _translate(exc) from exc

    warnings: list[str] = []

    # Work out the coordinate system before writing anything: an import that
    # half-succeeds in the wrong projection is worse than one that refuses.
    declared = source_srid or parsed.srid_hint
    if declared is None and parsed.crs_hint:
        matched = geo.srid_from_wkt(session, parsed.crs_hint)
        if matched is not None:
            declared = matched
            if matched != geo.STORAGE_SRID:
                warnings.append(
                    f"Coordinate system read from the file's projection as EPSG:{matched}."
                )

    sample = parsed.features[0].geometry.get("coordinates")
    try:
        srid = geo.resolve_srid(
            session, declared=declared, sample_coordinates=sample, crs_hint=parsed.crs_hint
        )
    except geo.GeometryError as exc:
        raise _translate(exc) from exc

    layer = GisLayer(
        name=name or (file.filename or "Imported layer"),
        description=description,
        category=category,
        geometry_kind=_dominant_kind(parsed.features),
        source_format=source_format,
        source_filename=file.filename,
        source_crs=geo.srid_name(session, srid) or f"EPSG:{srid}",
        is_public=is_public,
        owner_id=user.id,
        **{"project_id": links["project_id"], "site_id": links["site_id"]},
    )
    session.add(layer)
    session.flush()

    imported = 0
    skipped = 0
    for parsed_feature in parsed.features:
        try:
            session.add(
                GisFeature(
                    layer_id=layer.id,
                    name=parsed_feature.name,
                    geom=geo.geometry_element(parsed_feature.geometry, srid),
                    properties=parsed_feature.properties or None,
                )
            )
            imported += 1
        except Exception:  # pragma: no cover - one bad row must not lose the file
            skipped += 1

    session.flush()
    _refresh_layer_stats(session, layer)

    if skipped:
        warnings.append(f"{skipped} feature(s) could not be read and were skipped.")

    records.on_created(session, layer, RESOURCE, user=user, request=request)
    activity.log(
        session,
        action=ActivityAction.UPLOAD,
        user=user,
        resource_type=RESOURCE,
        resource_id=layer.id,
        resource_label=layer.name,
        project_id=layer.project_id,
        summary=f"Imported {imported} feature(s) from {source_format} file {file.filename!r}",
        request=request,
    )
    session.flush()

    return ImportResult(
        layer=_detail(session, layer, user),
        imported=imported,
        skipped=skipped,
        source_format=source_format,
        source_crs=layer.source_crs,
        reprojected_from_srid=srid if srid != geo.STORAGE_SRID else None,
        warnings=warnings,
    )


def _dominant_kind(features: list[formats.ParsedFeature]) -> GeometryKind:
    kinds = {_KIND_OF.get(feature.geometry.get("type", "")) for feature in features}
    kinds.discard(None)
    if len(kinds) == 1:
        return next(iter(kinds))
    return GeometryKind.MIXED


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------
@router.get(
    "/layers/{layer_id}/export",
    summary="Export a layer",
    description=(
        "Downloads the layer as GeoJSON, KML or a zipped shapefile. Exports "
        "are always in EPSG:4326, and the shapefile carries a `.prj` saying "
        "so, because a consumer that has to guess the coordinate system is how "
        "this data gets misplaced.\n\n"
        "A shapefile holds one geometry type and a fixed attribute table, so a "
        "mixed layer is split into one shapefile per geometry type inside the "
        "archive — which is what any GIS package does when asked the same "
        "question."
    ),
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/geo+json": {},
                "application/vnd.google-earth.kml+xml": {},
                "application/zip": {},
            }
        }
    },
)
def export_layer(
    layer_id: uuid.UUID,
    session: DbSession,
    user: CurrentUserOptional,
    format: Annotated[str, Query(pattern="^(geojson|kml|shapefile)$")] = "geojson",
    bbox: Annotated[str | None, Query(description="Only features overlapping this box")] = None,
) -> Response:
    layer = _get_layer(session, layer_id)
    _require_readable(session, user, layer)

    extent = None
    if bbox:
        try:
            extent = geo.parse_bbox(bbox)
        except geo.GeometryError as exc:
            raise _translate(exc) from exc

    rows, _ = _feature_rows(session, layer_id, extent=extent, limit=geo.MAX_FEATURES, offset=0)
    features = [_as_geojson_feature(row).model_dump(mode="json") for row in rows]
    for feature in features:
        feature.pop("id", None)

    from app.services.storage import safe_filename

    stem = safe_filename(layer.name, "layer").rsplit(".", 1)[0][:60] or "layer"

    if format == "geojson":
        document = formats.write_geojson(features, name=layer.name)
        if layer.bbox:
            document["bbox"] = layer.bbox
        body = json.dumps(document, ensure_ascii=False).encode("utf-8")
        media_type, suffix = "application/geo+json", "geojson"
    elif format == "kml":
        body = formats.write_kml(features, name=layer.name)
        media_type, suffix = "application/vnd.google-earth.kml+xml", "kml"
    else:
        try:
            body = formats.write_shapefile(features, name=stem)
        except geo.GeometryError as exc:
            raise _translate(exc) from exc
        media_type, suffix = "application/zip", "zip"

    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{stem}.{suffix}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/export/sites",
    summary="Export site locations",
    description=(
        "Every site the caller may see, as points. Restricted sites are "
        "exported at reduced precision — the same blurring the site endpoints "
        "apply, because an export is exactly how a restricted location would "
        "otherwise escape."
    ),
    response_class=Response,
)
def export_sites(
    session: DbSession,
    user: CurrentUserOptional,
    format: Annotated[str, Query(pattern="^(geojson|kml|shapefile)$")] = "geojson",
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    bbox: Annotated[str | None, Query()] = None,
) -> Response:
    from app.api.v1.endpoints.sites import RESTRICTED_PRECISION

    statement = select(Site).where(
        visibility_filter(user, Site, ResourceType.SITE),
        Site.latitude.is_not(None),
        Site.longitude.is_not(None),
    )
    if project_id is not None:
        statement = statement.where(Site.project_id == project_id)
    if bbox:
        try:
            extent = geo.parse_bbox(bbox)
        except geo.GeometryError as exc:
            raise _translate(exc) from exc
        statement = statement.where(geo.bbox_filter(Site.geom, extent))

    features: list[dict[str, Any]] = []
    for site in session.scalars(statement.order_by(Site.name)).all():
        editable = can_edit(session, user, site, ResourceType.SITE)
        blurred = site.location_restricted and not editable
        latitude = float(site.latitude)
        longitude = float(site.longitude)
        if blurred:
            latitude = round(latitude, RESTRICTED_PRECISION)
            longitude = round(longitude, RESTRICTED_PRECISION)

        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                "properties": {
                    "name": site.name,
                    "code": site.code,
                    "site_type": site.site_type.value if site.site_type else None,
                    "country": site.country,
                    "project_id": str(site.project_id),
                    "location_is_approximate": blurred,
                },
            }
        )

    if format == "geojson":
        body = json.dumps(formats.write_geojson(features, name="Sites"), ensure_ascii=False).encode(
            "utf-8"
        )
        media_type, suffix = "application/geo+json", "geojson"
    elif format == "kml":
        body = formats.write_kml(features, name="Sites")
        media_type, suffix = "application/vnd.google-earth.kml+xml", "kml"
    else:
        try:
            body = formats.write_shapefile(features, name="sites")
        except geo.GeometryError as exc:
            raise _translate(exc) from exc
        media_type, suffix = "application/zip", "zip"

    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="sites.{suffix}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
