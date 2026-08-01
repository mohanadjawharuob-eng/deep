"""Reading and writing the three interchange formats.

GeoJSON, KML and Shapefile all reduce to the same thing: a list of
``(geometry, properties, name)``. Each reader produces that; each writer
consumes it. Everything downstream of this module speaks GeoJSON geometry
objects and never knows which format the data arrived in.

Every reader is parsing a file from someone else, so each one is a place an
attacker gets to choose the bytes:

- **KML is XML**, and XML from a stranger is an entity-expansion attack unless
  the parser is hardened. Parsed with ``defusedxml``.
- **A shapefile arrives as a ZIP**, which invites a decompression bomb and
  path traversal through member names. Members are size-capped and read into
  memory by name match — nothing is ever extracted to disk.
- **GeoJSON is JSON**, which is safe to parse but trivially large; the caller
  caps the byte count before this module sees it.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any

from defusedxml import ElementTree as SafeElementTree

from app.services.geo import (
    MAX_FEATURES,
    GeometryError,
    validate_geojson_geometry,
)

#: Uncompressed ceiling for a shapefile ZIP. A survey shapefile is measured in
#: megabytes; anything approaching this is a bomb or a basemap.
MAX_UNCOMPRESSED_BYTES = 300 * 1024 * 1024
#: Members in the archive. A shapefile is 3–8 files; a hundred is not a
#: shapefile.
MAX_ZIP_MEMBERS = 100

#: The KML namespace, in both spellings that exist in the wild.
KML_NAMESPACES = (
    "{http://www.opengis.net/kml/2.2}",
    "{http://earth.google.com/kml/2.1}",
    "{http://earth.google.com/kml/2.0}",
    "",
)


@dataclass
class ParsedFeature:
    """One feature, in the shape everything downstream expects."""

    geometry: dict[str, Any]
    properties: dict[str, Any] = field(default_factory=dict)
    name: str | None = None


@dataclass
class ParsedLayer:
    """What a reader produces from one file."""

    features: list[ParsedFeature]
    #: Coordinate system as declared by the file, when it declares one.
    crs_hint: str | None = None
    srid_hint: int | None = None


# --------------------------------------------------------------------------
# GeoJSON
# --------------------------------------------------------------------------
def read_geojson(payload: bytes) -> ParsedLayer:
    """Parse a FeatureCollection, a Feature, or a bare geometry."""
    try:
        document = json.loads(payload.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise GeometryError("That file is not UTF-8 text, so it is not GeoJSON") from exc
    except json.JSONDecodeError as exc:
        raise GeometryError(f"That file is not valid JSON: {exc.msg} at line {exc.lineno}") from exc

    if not isinstance(document, dict):
        raise GeometryError("GeoJSON must be an object, not a bare list or value")

    document_type = document.get("type")
    features: list[ParsedFeature] = []

    if document_type == "FeatureCollection":
        raw_features = document.get("features")
        if not isinstance(raw_features, list):
            raise GeometryError("A FeatureCollection needs a 'features' list")
        if len(raw_features) > MAX_FEATURES:
            raise GeometryError(
                f"That file holds {len(raw_features):,} features; the limit is "
                f"{MAX_FEATURES:,}. Split it, or serve it as a tile layer."
            )
        for index, raw in enumerate(raw_features):
            features.append(_read_geojson_feature(raw, index))
    elif document_type == "Feature":
        features.append(_read_geojson_feature(document, 0))
    else:
        # A bare geometry object.
        features.append(ParsedFeature(geometry=validate_geojson_geometry(document)))

    if not features:
        raise GeometryError("That file contains no features")

    return ParsedLayer(features=features, crs_hint=_geojson_crs(document))


def _read_geojson_feature(raw: Any, index: int) -> ParsedFeature:
    if not isinstance(raw, dict):
        raise GeometryError(f"Feature {index + 1} is not an object")

    geometry = raw.get("geometry")
    if geometry is None:
        raise GeometryError(f"Feature {index + 1} has no geometry")

    properties = raw.get("properties")
    if not isinstance(properties, dict):
        properties = {}

    return ParsedFeature(
        geometry=validate_geojson_geometry(geometry),
        properties=properties,
        name=_name_from_properties(properties),
    )


def _geojson_crs(document: dict[str, Any]) -> str | None:
    """The CRS member, which RFC 7946 removed but real files still carry."""
    crs = document.get("crs")
    if isinstance(crs, dict):
        properties = crs.get("properties")
        if isinstance(properties, dict):
            name = properties.get("name")
            if isinstance(name, str):
                return name
    return None


#: Property keys that usually hold a human label, in the order to try them.
_NAME_KEYS = ("name", "Name", "NAME", "title", "Title", "label", "id", "ID")


def _name_from_properties(properties: dict[str, Any]) -> str | None:
    for key in _NAME_KEYS:
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:300]
        if isinstance(value, int | float):
            return str(value)[:300]
    return None


def write_geojson(
    features: list[dict[str, Any]], *, name: str | None = None, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A FeatureCollection ready to serialise."""
    document: dict[str, Any] = {"type": "FeatureCollection", "features": features}
    if name:
        document["name"] = name
    if extra:
        document.update(extra)
    return document


# --------------------------------------------------------------------------
# KML
# --------------------------------------------------------------------------
def read_kml(payload: bytes) -> ParsedLayer:
    """Parse a KML document, or a KMZ archive containing one.

    Parsed with ``defusedxml``: a KML from a stranger is XML from a stranger,
    and the billion-laughs entity expansion is a two-line file.
    """
    if payload[:2] == b"PK":
        payload = _kml_from_kmz(payload)

    try:
        root = SafeElementTree.fromstring(payload)
    except Exception as exc:
        raise GeometryError(f"That file is not readable KML: {type(exc).__name__}") from exc

    features: list[ParsedFeature] = []
    for placemark in _findall_any(root, "Placemark"):
        parsed = _read_placemark(placemark)
        features.extend(parsed)
        if len(features) > MAX_FEATURES:
            raise GeometryError(
                f"That file holds more than {MAX_FEATURES:,} placemarks. "
                f"Split it, or serve it as a tile layer."
            )

    if not features:
        raise GeometryError("That KML contains no placemarks with geometry")

    # KML is defined as WGS84 by its own specification, so no CRS question
    # arises — which is the one pleasant thing about the format.
    return ParsedLayer(features=features, crs_hint="EPSG:4326", srid_hint=4326)


def _kml_from_kmz(payload: bytes) -> bytes:
    """The doc.kml inside a KMZ."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise GeometryError("That file looks like a KMZ but could not be opened") from exc

    _check_archive(archive)
    for info in archive.infolist():
        if info.filename.lower().endswith(".kml"):
            return archive.read(info)
    raise GeometryError("That KMZ contains no .kml document")


def _findall_any(element: Any, tag: str) -> list[Any]:
    """Find descendants by tag across the KML namespaces in circulation."""
    found: list[Any] = []
    for namespace in KML_NAMESPACES:
        found.extend(element.iter(f"{namespace}{tag}"))
    return found


def _find_child(element: Any, tag: str) -> Any | None:
    for namespace in KML_NAMESPACES:
        child = element.find(f"{namespace}{tag}")
        if child is not None:
            return child
    return None


def _read_placemark(placemark: Any) -> list[ParsedFeature]:
    name_element = _find_child(placemark, "name")
    name = (name_element.text or "").strip()[:300] if name_element is not None else None

    properties: dict[str, Any] = {}
    description = _find_child(placemark, "description")
    if description is not None and description.text:
        properties["description"] = description.text.strip()[:5000]
    properties.update(_read_extended_data(placemark))
    if name:
        properties.setdefault("name", name)

    features: list[ParsedFeature] = []
    for geometry in _placemark_geometries(placemark):
        features.append(ParsedFeature(geometry=geometry, properties=properties, name=name or None))
    return features


def _read_extended_data(placemark: Any) -> dict[str, Any]:
    """KML's attribute table: ``<ExtendedData><Data name="x"><value>``."""
    attributes: dict[str, Any] = {}
    extended = _find_child(placemark, "ExtendedData")
    if extended is None:
        return attributes

    for data in _findall_any(extended, "Data"):
        key = data.get("name")
        value_element = _find_child(data, "value")
        if key and value_element is not None and value_element.text:
            attributes[key[:120]] = value_element.text.strip()[:2000]

    for simple in _findall_any(extended, "SimpleData"):
        key = simple.get("name")
        if key and simple.text:
            attributes[key[:120]] = simple.text.strip()[:2000]

    return attributes


def _placemark_geometries(placemark: Any) -> list[dict[str, Any]]:
    geometries: list[dict[str, Any]] = []

    for point in _findall_any(placemark, "Point"):
        positions = _read_coordinates(point)
        if positions:
            geometries.append({"type": "Point", "coordinates": positions[0]})

    for line in _findall_any(placemark, "LineString"):
        positions = _read_coordinates(line)
        if len(positions) >= 2:
            geometries.append({"type": "LineString", "coordinates": positions})

    for polygon in _findall_any(placemark, "Polygon"):
        rings = _read_polygon_rings(polygon)
        if rings:
            geometries.append({"type": "Polygon", "coordinates": rings})

    return geometries


def _read_polygon_rings(polygon: Any) -> list[list[list[float]]]:
    rings: list[list[list[float]]] = []

    outer = _find_child(polygon, "outerBoundaryIs")
    if outer is not None:
        positions = _read_coordinates(outer)
        if len(positions) >= 4:
            rings.append(_close_ring(positions))

    for inner in _findall_any(polygon, "innerBoundaryIs"):
        positions = _read_coordinates(inner)
        if len(positions) >= 4:
            rings.append(_close_ring(positions))

    return rings


def _close_ring(positions: list[list[float]]) -> list[list[float]]:
    """A GeoJSON ring must close; KML files frequently do not bother."""
    if positions[0] != positions[-1]:
        return [*positions, positions[0]]
    return positions


def _read_coordinates(element: Any) -> list[list[float]]:
    """KML coordinates are ``lon,lat[,alt]`` triples separated by whitespace."""
    node = _find_child(element, "coordinates")
    if node is None:
        for namespace in KML_NAMESPACES:
            found = element.find(f".//{namespace}coordinates")
            if found is not None:
                node = found
                break
    if node is None or not node.text:
        return []

    positions: list[list[float]] = []
    for chunk in node.text.replace("\n", " ").replace("\t", " ").split():
        parts = chunk.split(",")
        if len(parts) < 2:
            continue
        try:
            longitude, latitude = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        positions.append([longitude, latitude])
    return positions


def write_kml(features: list[dict[str, Any]], *, name: str = "Layer") -> bytes:
    """Render a FeatureCollection's features as KML.

    Written by hand rather than with a library: the output is a fixed, small
    subset of KML, and generating it directly means no dependency and no
    surprise about what ends up in the file.
    """
    from xml.sax.saxutils import escape

    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        "  <Document>",
        f"    <name>{escape(name)}</name>",
    ]

    for feature in features:
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        label = properties.get("name") or properties.get("title") or ""
        rendered = _geometry_to_kml(geometry)
        if not rendered:
            continue

        parts.append("    <Placemark>")
        if label:
            parts.append(f"      <name>{escape(str(label))}</name>")
        if properties:
            parts.append("      <ExtendedData>")
            for key, value in properties.items():
                if value is None:
                    continue
                parts.append(
                    f'        <Data name="{escape(str(key))}">'
                    f"<value>{escape(str(value))}</value></Data>"
                )
            parts.append("      </ExtendedData>")
        parts.append(rendered)
        parts.append("    </Placemark>")

    parts.extend(["  </Document>", "</kml>", ""])
    return "\n".join(parts).encode("utf-8")


def _geometry_to_kml(geometry: dict[str, Any]) -> str:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")

    if kind == "Point":
        return f"      <Point><coordinates>{_kml_position(coordinates)}</coordinates></Point>"
    if kind == "LineString":
        return (
            f"      <LineString><coordinates>{_kml_positions(coordinates)}"
            f"</coordinates></LineString>"
        )
    if kind == "Polygon" and coordinates:
        rings = [
            "        <outerBoundaryIs><LinearRing><coordinates>"
            f"{_kml_positions(coordinates[0])}"
            "</coordinates></LinearRing></outerBoundaryIs>"
        ]
        for hole in coordinates[1:]:
            rings.append(
                "        <innerBoundaryIs><LinearRing><coordinates>"
                f"{_kml_positions(hole)}"
                "</coordinates></LinearRing></innerBoundaryIs>"
            )
        return "      <Polygon>\n" + "\n".join(rings) + "\n      </Polygon>"
    if kind in ("MultiPoint", "MultiLineString", "MultiPolygon") and coordinates:
        member = {
            "MultiPoint": "Point",
            "MultiLineString": "LineString",
            "MultiPolygon": "Polygon",
        }[kind]
        rendered = [_geometry_to_kml({"type": member, "coordinates": part}) for part in coordinates]
        return (
            "      <MultiGeometry>\n"
            + "\n".join(part for part in rendered if part)
            + "\n      </MultiGeometry>"
        )
    if kind == "GeometryCollection":
        rendered = [_geometry_to_kml(part) for part in geometry.get("geometries", [])]
        return (
            "      <MultiGeometry>\n"
            + "\n".join(part for part in rendered if part)
            + "\n      </MultiGeometry>"
        )
    return ""


def _kml_position(position: Any) -> str:
    if not isinstance(position, list | tuple) or len(position) < 2:
        return ""
    return f"{position[0]},{position[1]}"


def _kml_positions(positions: Any) -> str:
    if not isinstance(positions, list | tuple):
        return ""
    return " ".join(_kml_position(position) for position in positions)


# --------------------------------------------------------------------------
# Shapefile
# --------------------------------------------------------------------------
#: pyshp's numeric shape types, mapped to what they mean in GeoJSON. Types
#: absent here (multipatch, and the measured variants) are not renderable as
#: GeoJSON and are refused rather than silently mangled.
_SHAPE_TYPES = {
    0: "Null",
    1: "Point",
    3: "LineString",
    5: "Polygon",
    8: "MultiPoint",
    11: "PointZ",
    13: "LineStringZ",
    15: "PolygonZ",
    18: "MultiPointZ",
    21: "PointM",
    23: "LineStringM",
    25: "PolygonM",
    28: "MultiPointM",
}


def read_shapefile(payload: bytes) -> ParsedLayer:
    """Parse a zipped shapefile, or an archive holding several.

    Shapefiles are a set of sidecar files, so they arrive as a ZIP. Members are
    read by name from memory; nothing is written to disk, so a member called
    ``../../etc/cron.d/x`` is just an odd name rather than a path.

    More than one shapefile in the archive is normal and is read as one layer.
    A shapefile holds a single geometry type, so a survey with trenches, finds
    and a site boundary *is* three files — and zipping a whole folder is what
    people do.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise GeometryError(
            "A shapefile must be uploaded as a .zip containing at least the "
            ".shp, .shx and .dbf files. That file is not a readable ZIP."
        ) from exc

    _check_archive(archive)
    stems = _shapefile_stems(archive)

    if not stems:
        raise GeometryError("That archive contains no .shp file")

    incomplete = [stem for stem, parts in stems.items() if "shx" not in parts]
    if incomplete and len(incomplete) == len(stems):
        raise GeometryError(
            "That archive has no .shx index file. A shapefile needs .shp, .shx "
            "and .dbf together — re-export it with all its sidecar files."
        )

    features: list[ParsedFeature] = []
    projection: str | None = None

    for stem in sorted(stems):
        parts = stems[stem]
        if "shx" not in parts:
            # One broken component should not lose the rest of the archive.
            continue
        if projection is None and "prj" in parts:
            projection = archive.read(parts["prj"]).decode("utf-8", errors="replace")

        features.extend(_read_one_shapefile(archive, parts, stem))
        if len(features) > MAX_FEATURES:
            raise GeometryError(
                f"That archive holds more than {MAX_FEATURES:,} features. "
                f"Split it, or serve it as a tile layer."
            )

    if not features:
        raise GeometryError("That shapefile contains no usable geometry")

    return ParsedLayer(features=features, crs_hint=projection)


def _read_one_shapefile(
    archive: zipfile.ZipFile, parts: dict[str, str], stem: str
) -> list[ParsedFeature]:
    import shapefile  # pyshp

    arguments: dict[str, Any] = {
        "shp": io.BytesIO(archive.read(parts["shp"])),
        "shx": io.BytesIO(archive.read(parts["shx"])),
    }
    if "dbf" in parts:
        arguments["dbf"] = io.BytesIO(archive.read(parts["dbf"]))

    try:
        reader = shapefile.Reader(**arguments)
        records = reader.shapeRecords()
    except Exception as exc:
        raise GeometryError(f"{stem}.shp could not be read: {type(exc).__name__}") from exc

    fields = [definition[0] for definition in reader.fields[1:]]
    features: list[ParsedFeature] = []

    for record in records:
        geometry = _shape_to_geojson(record.shape)
        if geometry is None:
            continue
        properties = _clean_record(dict(zip(fields, list(record.record), strict=False)))
        features.append(
            ParsedFeature(
                geometry=validate_geojson_geometry(geometry),
                properties=properties,
                name=_name_from_properties(properties),
            )
        )
    return features


def _shapefile_stems(archive: zipfile.ZipFile) -> dict[str, dict[str, str]]:
    """Group members by shapefile stem: ``{"trenches": {"shp": ..., ...}}``.

    Directory structure and case are ignored, and only stems that actually
    have a ``.shp`` are returned.
    """
    stems: dict[str, dict[str, str]] = {}

    for info in archive.infolist():
        if info.is_dir():
            continue
        basename = info.filename.replace("\\", "/").split("/")[-1]
        if basename.startswith(".") or "__MACOSX" in info.filename:
            continue
        if "." not in basename:
            continue
        stem, extension = basename.rsplit(".", 1)
        stems.setdefault(stem.lower(), {}).setdefault(extension.lower(), info.filename)

    return {stem: parts for stem, parts in stems.items() if "shp" in parts}


def _check_archive(archive: zipfile.ZipFile) -> None:
    """Refuse an archive that would cost too much to read.

    The declared uncompressed size is checked before anything is read, so a
    file that expands a thousandfold is refused rather than absorbed.
    """
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_MEMBERS:
        raise GeometryError(
            f"That archive holds {len(infos)} files. A shapefile is a handful; "
            f"this looks like something else."
        )

    total = sum(info.file_size for info in infos)
    if total > MAX_UNCOMPRESSED_BYTES:
        raise GeometryError(
            f"That archive expands to {total // (1024 * 1024)} MB, over the "
            f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB limit."
        )


def _clean_record(record: dict[str, Any]) -> dict[str, Any]:
    """DBF values into something JSONB accepts."""
    import datetime

    cleaned: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, bytes):
            cleaned[key] = value.decode("utf-8", errors="replace").strip()
        elif isinstance(value, datetime.date):
            cleaned[key] = value.isoformat()
        elif isinstance(value, str):
            cleaned[key] = value.strip()
        elif isinstance(value, int | float | bool) or value is None:
            cleaned[key] = value
        else:
            cleaned[key] = str(value)
    return cleaned


def _shape_to_geojson(shape: Any) -> dict[str, Any] | None:
    """pyshp shape into a GeoJSON geometry.

    pyshp offers ``__geo_interface__``, which is used where it works; it
    raises on a few edge shapes, and returning ``None`` there skips the
    feature rather than failing the whole import for one bad row.
    """
    if getattr(shape, "shapeType", 0) == 0:
        return None
    try:
        geometry = shape.__geo_interface__
    except Exception:
        return None
    if not isinstance(geometry, dict) or not geometry.get("coordinates"):
        return None
    return json.loads(json.dumps(geometry))  # tuples → lists


def write_shapefile(features: list[dict[str, Any]], *, name: str = "layer") -> bytes:
    """Render features as a zipped shapefile.

    A shapefile holds **one** geometry type and a fixed attribute table, which
    a mixed archaeological layer does not. Features are therefore split by
    geometry type into separate shapefiles inside one archive, and the
    attribute table is the union of the properties present — which is what any
    GIS package does when asked the same question.
    """
    import shapefile  # pyshp

    by_kind: dict[str, list[dict[str, Any]]] = {}
    for feature in features:
        geometry = feature.get("geometry") or {}
        kind = _shapefile_kind(geometry.get("type"))
        if kind is None:
            continue
        by_kind.setdefault(kind, []).append(feature)

    if not by_kind:
        raise GeometryError("None of these features can be written as a shapefile")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for kind, group in by_kind.items():
            stem = name if len(by_kind) == 1 else f"{name}_{kind.lower()}"
            for extension, data in _write_one_shapefile(shapefile, kind, group).items():
                archive.writestr(f"{stem}.{extension}", data)
            # One .prj per stem, not one per archive: a .prj belongs to the
            # shapefile of the same name, and a reader that finds none assumes
            # whatever it likes — which is the mistake this module exists to
            # prevent on the way in.
            archive.writestr(f"{stem}.prj", _WGS84_PRJ)

    return buffer.getvalue()


#: The .prj text for EPSG:4326, which is what every export is in. Written
#: literally so a consumer never has to guess the CRS of our output — the
#: mistake this module works hardest to prevent on the way in.
_WGS84_PRJ = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
    'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
)


def _shapefile_kind(geometry_type: str | None) -> str | None:
    return {
        "Point": "POINT",
        "MultiPoint": "MULTIPOINT",
        "LineString": "POLYLINE",
        "MultiLineString": "POLYLINE",
        "Polygon": "POLYGON",
        "MultiPolygon": "POLYGON",
    }.get(geometry_type or "")


def _write_one_shapefile(shapefile: Any, kind: str, features: list[dict[str, Any]]) -> dict:
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    writer = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=getattr(shapefile, kind))

    columns = _attribute_columns(features)
    for column in columns:
        writer.field(column, "C", size=254)

    for feature in features:
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        writer.record(*[_as_text(properties.get(column)) for column in columns])
        _write_shape(writer, geometry)

    writer.close()
    return {"shp": shp.getvalue(), "shx": shx.getvalue(), "dbf": dbf.getvalue()}


def _attribute_columns(features: list[dict[str, Any]]) -> list[str]:
    """Union of property keys, truncated to the DBF ten-character limit.

    Truncation can collide — ``excavation_year`` and ``excavation_zone`` both
    become ``excavatio`` — so collisions get a numeric suffix rather than
    silently overwriting each other.
    """
    columns: list[str] = []
    seen: set[str] = set()

    for feature in features:
        for key in feature.get("properties") or {}:
            candidate = str(key)[:10]
            if candidate in seen:
                if any(str(key) == existing for existing in columns):
                    continue
                suffix = 1
                while f"{candidate[:8]}_{suffix}" in seen and suffix < 100:
                    suffix += 1
                candidate = f"{candidate[:8]}_{suffix}"
            if candidate not in seen:
                seen.add(candidate)
                columns.append(candidate)

    # A DBF must declare at least one field, and a layer of pure geometry with
    # no attributes at all — a trench outline, a contour set — is ordinary.
    # Without this the export fails on exactly the simplest possible layer.
    return columns or ["name"]


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value)[:254]
    return str(value)[:254]


def _write_shape(writer: Any, geometry: dict[str, Any]) -> None:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")

    if kind == "Point":
        writer.point(coordinates[0], coordinates[1])
    elif kind == "MultiPoint":
        writer.multipoint([[position[0], position[1]] for position in coordinates])
    elif kind == "LineString":
        writer.line([[[position[0], position[1]] for position in coordinates]])
    elif kind == "MultiLineString":
        writer.line([[[position[0], position[1]] for position in part] for part in coordinates])
    elif kind == "Polygon":
        writer.poly(_shapefile_rings(coordinates))
    elif kind == "MultiPolygon":
        rings: list[list[list[float]]] = []
        for polygon in coordinates:
            rings.extend(_shapefile_rings(polygon))
        writer.poly(rings)


def _ring_is_clockwise(ring: list[list[float]]) -> bool:
    """Shoelace sign. Positive area means clockwise in screen coordinates."""
    total = 0.0
    for current, following in zip(ring, ring[1:], strict=False):
        total += (following[0] - current[0]) * (following[1] + current[1])
    return total > 0


def _shapefile_rings(rings: Any) -> list[list[list[float]]]:
    """Re-wind GeoJSON rings for the shapefile specification.

    The two formats disagree, and the disagreement is silent: GeoJSON winds
    exterior rings counter-clockwise (RFC 7946), the shapefile specification
    winds them clockwise. Writing GeoJSON order straight out produces a file
    whose every polygon reads as a hole with no exterior — which loads, draws
    nothing useful, and gives no error.
    """
    prepared: list[list[list[float]]] = []
    for index, ring in enumerate(rings):
        positions = [[position[0], position[1]] for position in ring]
        if len(positions) < 4:
            continue
        clockwise = _ring_is_clockwise(positions)
        # Exterior clockwise, holes counter-clockwise.
        wants_clockwise = index == 0
        if clockwise != wants_clockwise:
            positions.reverse()
        prepared.append(positions)
    return prepared


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------
#: Extension → (reader, canonical format name).
READERS = {
    ".geojson": (read_geojson, "geojson"),
    ".json": (read_geojson, "geojson"),
    ".kml": (read_kml, "kml"),
    ".kmz": (read_kml, "kml"),
    ".zip": (read_shapefile, "shapefile"),
}


def read(payload: bytes, extension: str) -> tuple[ParsedLayer, str]:
    """Parse a file by extension, returning the layer and the format name."""
    entry = READERS.get(extension.lower())
    if entry is None:
        raise GeometryError(
            f"{extension or 'That file'} is not a supported GIS format. "
            f"Upload GeoJSON (.geojson), KML (.kml/.kmz) or a zipped shapefile (.zip)."
        )
    reader, format_name = entry
    return reader(payload), format_name
