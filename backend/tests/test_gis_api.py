"""GIS layers, interchange formats and spatial search.

The property most of these tests defend is that **coordinates arrive where
they were meant to be**. A permission bug throws a 403; a projection bug
throws nothing at all — the map renders, the shapes look plausible, and the
site is in the wrong country. So the reprojection cases below are not edge
cases, they are the point.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Module, ModuleLevel, ResourceType, User, UserRole
from app.services import geo
from app.services import geoformats as formats
from tests.conftest import auth_headers, make_user

# Northern Jordan, where the rest of the fixtures live.
TRENCH = [35.85, 32.5556]
SURVEY_POLYGON = [[[35.80, 32.50], [35.90, 32.50], [35.90, 32.60], [35.80, 32.60], [35.80, 32.50]]]


def feature_collection(*features: dict) -> bytes:
    return json.dumps({"type": "FeatureCollection", "features": list(features)}).encode()


def point_feature(coordinates: list[float], **properties: object) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": coordinates},
        "properties": properties,
    }


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def project(client: TestClient, researcher: User) -> dict:
    response = client.post(
        "/api/v1/projects",
        json={"name": "GIS Test", "code": "gis-1", "is_public": True},
        headers=auth_headers(client, "researcher"),
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def site(client: TestClient, researcher: User, project: dict) -> dict:
    response = client.post(
        "/api/v1/sites",
        json={
            "project_id": project["id"],
            "name": "Tell GIS",
            "code": "TG",
            "latitude": TRENCH[1],
            "longitude": TRENCH[0],
            "is_public": True,
        },
        headers=auth_headers(client, "researcher"),
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def layer(client: TestClient, researcher: User, site: dict) -> dict:
    response = client.post(
        "/api/v1/gis/layers",
        json={
            "site_id": site["id"],
            "name": "Trench plan",
            "category": "trench",
            "is_public": True,
        },
        headers=auth_headers(client, "researcher"),
    )
    assert response.status_code == 201, response.text
    return response.json()


def import_file(
    client: TestClient,
    payload: bytes,
    filename: str,
    *,
    identifier: str = "researcher",
    **fields: object,
):
    return client.post(
        "/api/v1/gis/import",
        files={"file": (filename, payload, "application/octet-stream")},
        data={key: str(value) for key, value in fields.items()},
        headers=auth_headers(client, identifier),
    )


# --------------------------------------------------------------------------
# Layers
# --------------------------------------------------------------------------
class TestLayers:
    def test_a_layer_starts_empty(self, client: TestClient, researcher: User, layer: dict) -> None:
        assert layer["feature_count"] == 0
        assert layer["bbox"] is None

    def test_a_layer_must_hang_from_a_project_or_site(
        self, client: TestClient, researcher: User
    ) -> None:
        response = client.post(
            "/api/v1/gis/layers",
            json={"name": "Floating"},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 422

    def test_the_site_implies_the_project(
        self, client: TestClient, researcher: User, project: dict, layer: dict
    ) -> None:
        assert layer["project_id"] == project["id"]

    def test_adding_a_feature_updates_the_count_and_extent(
        self, client: TestClient, researcher: User, layer: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        created = client.post(
            f"/api/v1/gis/layers/{layer['id']}/features",
            json={
                "geometry": {"type": "Point", "coordinates": TRENCH},
                "name": "Datum",
                "properties": {"kind": "survey point"},
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        assert created.json()["geometry"]["coordinates"] == pytest.approx(TRENCH, abs=1e-6)

        refreshed = client.get(f"/api/v1/gis/layers/{layer['id']}", headers=headers).json()
        assert refreshed["feature_count"] == 1
        assert refreshed["bbox"] == pytest.approx([*TRENCH, *TRENCH], abs=1e-6)

    def test_deleting_a_feature_updates_the_count(
        self, client: TestClient, researcher: User, layer: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        feature = client.post(
            f"/api/v1/gis/layers/{layer['id']}/features",
            json={"geometry": {"type": "Point", "coordinates": TRENCH}},
            headers=headers,
        ).json()

        client.delete(f"/api/v1/gis/layers/{layer['id']}/features/{feature['id']}", headers=headers)
        refreshed = client.get(f"/api/v1/gis/layers/{layer['id']}", headers=headers).json()
        assert refreshed["feature_count"] == 0
        assert refreshed["bbox"] is None

    def test_features_come_back_as_a_geojson_feature_collection(
        self, client: TestClient, researcher: User, layer: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        client.post(
            f"/api/v1/gis/layers/{layer['id']}/features",
            json={
                "geometry": {"type": "Polygon", "coordinates": SURVEY_POLYGON},
                "name": "Trench A",
            },
            headers=headers,
        )

        body = client.get(f"/api/v1/gis/layers/{layer['id']}/features", headers=headers).json()
        assert body["type"] == "FeatureCollection"
        assert body["features"][0]["type"] == "Feature"
        assert body["features"][0]["geometry"]["type"] == "Polygon"
        assert body["features"][0]["properties"]["name"] == "Trench A"

    def test_a_feature_of_another_layer_is_not_reachable_through_this_one(
        self, client: TestClient, researcher: User, site: dict, layer: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        other = client.post(
            "/api/v1/gis/layers",
            json={"site_id": site["id"], "name": "Other"},
            headers=headers,
        ).json()
        feature = client.post(
            f"/api/v1/gis/layers/{other['id']}/features",
            json={"geometry": {"type": "Point", "coordinates": TRENCH}},
            headers=headers,
        ).json()

        response = client.patch(
            f"/api/v1/gis/layers/{layer['id']}/features/{feature['id']}",
            json={"name": "Hijacked"},
            headers=headers,
        )
        assert response.status_code == 404

    def test_a_private_layer_is_invisible_to_anonymous_callers(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        private = client.post(
            "/api/v1/gis/layers",
            json={"site_id": site["id"], "name": "Unpublished", "is_public": False},
            headers=auth_headers(client, "researcher"),
        ).json()

        assert client.get(f"/api/v1/gis/layers/{private['id']}").status_code == 404
        assert client.get(f"/api/v1/gis/layers/{private['id']}/features").status_code == 404
        assert client.get(f"/api/v1/gis/layers/{private['id']}/export").status_code == 404


# --------------------------------------------------------------------------
# Import
# --------------------------------------------------------------------------
class TestImport:
    def test_geojson_imports(self, client: TestClient, researcher: User, site: dict) -> None:
        payload = feature_collection(
            point_feature(TRENCH, name="Datum", year=2024),
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": SURVEY_POLYGON},
                "properties": {"name": "Survey area"},
            },
        )
        response = import_file(client, payload, "survey.geojson", site_id=site["id"])
        assert response.status_code == 201, response.text
        body = response.json()

        assert body["imported"] == 2
        assert body["source_format"] == "geojson"
        assert body["layer"]["geometry_kind"] == "mixed"
        assert body["layer"]["feature_count"] == 2
        assert body["reprojected_from_srid"] is None

    def test_a_single_geometry_kind_is_recorded_as_such(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        payload = feature_collection(
            point_feature([35.85, 32.55], name="A"), point_feature([35.86, 32.56], name="B")
        )
        body = import_file(client, payload, "points.geojson", site_id=site["id"]).json()
        assert body["layer"]["geometry_kind"] == "point"

    def test_kml_imports(self, client: TestClient, researcher: User, site: dict) -> None:
        kml = formats.write_kml(
            [
                {
                    "geometry": {"type": "Point", "coordinates": TRENCH},
                    "properties": {"name": "Datum", "note": "north-west corner"},
                }
            ],
            name="Survey",
        )
        response = import_file(client, kml, "survey.kml", site_id=site["id"])
        assert response.status_code == 201, response.text
        body = response.json()

        assert body["imported"] == 1
        assert body["source_format"] == "kml"

        features = client.get(
            f"/api/v1/gis/layers/{body['layer']['id']}/features",
            headers=auth_headers(client, "researcher"),
        ).json()
        assert features["features"][0]["properties"]["note"] == "north-west corner"

    def test_a_zipped_shapefile_imports(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        archive = formats.write_shapefile(
            [
                {
                    "geometry": {"type": "Point", "coordinates": TRENCH},
                    "properties": {"name": "Datum"},
                }
            ],
            name="datum",
        )
        response = import_file(client, archive, "datum.zip", site_id=site["id"])
        assert response.status_code == 201, response.text
        assert response.json()["source_format"] == "shapefile"
        assert response.json()["imported"] == 1

    def test_an_unsupported_extension_is_refused(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        response = import_file(client, b"whatever", "notes.txt", site_id=site["id"])
        assert response.status_code == 422
        assert "not a supported GIS format" in response.json()["detail"]

    def test_malformed_json_is_reported_readably(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        response = import_file(client, b"{not json at all", "broken.geojson", site_id=site["id"])
        assert response.status_code == 422
        assert "not valid JSON" in response.json()["detail"]

    def test_an_empty_collection_is_refused(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        response = import_file(
            client,
            json.dumps({"type": "FeatureCollection", "features": []}).encode(),
            "empty.geojson",
            site_id=site["id"],
        )
        assert response.status_code == 422

    def test_a_zip_that_is_not_a_shapefile_is_refused(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("readme.txt", "nothing to see")

        response = import_file(client, buffer.getvalue(), "notes.zip", site_id=site["id"])
        assert response.status_code == 422
        assert "no .shp" in response.json()["detail"]

    def test_a_shapefile_missing_its_index_says_which_file_is_missing(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        complete = formats.write_shapefile(
            [{"geometry": {"type": "Point", "coordinates": TRENCH}, "properties": {}}],
            name="partial",
        )
        buffer = io.BytesIO()
        with (
            zipfile.ZipFile(io.BytesIO(complete)) as source,
            zipfile.ZipFile(buffer, "w") as target,
        ):
            for info in source.infolist():
                if not info.filename.endswith(".shx"):
                    target.writestr(info.filename, source.read(info))

        response = import_file(client, buffer.getvalue(), "partial.zip", site_id=site["id"])
        assert response.status_code == 422
        assert ".shx" in response.json()["detail"]

    def test_importing_needs_rights_on_the_project(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        make_user(db, email="outsider@example.org", username="outsider")
        response = import_file(
            client,
            feature_collection(point_feature(TRENCH)),
            "x.geojson",
            identifier="outsider",
            site_id=site["id"],
        )
        assert response.status_code == 403


# --------------------------------------------------------------------------
# Coordinate systems — the part that silently corrupts data
# --------------------------------------------------------------------------
class TestProjections:
    #: A point in UTM zone 36N (EPSG:32636) that is the Tell GIS site. Eastings
    #: and northings, not degrees — exactly the file a total station produces.
    UTM_36N = [768_000.0, 3_604_000.0]

    def test_projected_coordinates_without_an_srid_are_refused_not_guessed(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        """The whole reason this module refuses to guess.

        These numbers are a perfectly good UTM coordinate. Read as degrees they
        are nowhere, and a platform that shrugged and stored them would put the
        site in the wrong hemisphere without raising anything.
        """
        payload = feature_collection(point_feature(self.UTM_36N, name="Datum"))
        response = import_file(client, payload, "grid.geojson", site_id=site["id"])

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "not longitude and latitude" in detail
        assert "source_srid" in detail

    def test_a_declared_srid_is_reprojected(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        payload = feature_collection(point_feature(self.UTM_36N, name="Datum"))
        response = import_file(
            client, payload, "grid.geojson", site_id=site["id"], source_srid=32636
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["reprojected_from_srid"] == 32636
        assert body["layer"]["source_crs"] == "EPSG:32636"

        features = client.get(
            f"/api/v1/gis/layers/{body['layer']['id']}/features",
            headers=auth_headers(client, "researcher"),
        ).json()
        longitude, latitude = features["features"][0]["geometry"]["coordinates"]

        # Reprojected into northern Jordan, not left as raw eastings.
        assert 35.0 < longitude < 36.5
        assert 32.0 < latitude < 33.0

    def test_a_file_that_contradicts_itself_is_refused(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        """A .prj saying WGS84 over coordinates that cannot be degrees.

        The common cause is a shapefile reprojected in a GIS whose .prj was
        never updated. Believing the declaration stores eastings as longitudes,
        which PostGIS accepts silently and nothing downstream questions — so
        the contradiction has to be caught here or not at all.
        """
        archive = formats.write_shapefile(
            [
                {
                    "geometry": {"type": "Point", "coordinates": self.UTM_36N},
                    "properties": {"name": "Total station datum"},
                }
            ],
            name="datum",
        )
        # write_shapefile always stamps a WGS84 .prj, which is exactly the lie.
        response = import_file(client, archive, "datum.zip", site_id=site["id"])

        assert response.status_code == 422
        assert "contradicts itself" in response.json()["detail"]

    def test_an_explicit_wgs84_over_projected_coordinates_is_also_refused(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        """The same contradiction typed by a person rather than a file."""
        payload = feature_collection(point_feature(self.UTM_36N))
        response = import_file(
            client, payload, "grid.geojson", site_id=site["id"], source_srid=4326
        )
        assert response.status_code == 422
        assert "contradicts itself" in response.json()["detail"]

    def test_an_unknown_srid_is_refused_with_a_usable_message(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        payload = feature_collection(point_feature(self.UTM_36N))
        response = import_file(
            client, payload, "grid.geojson", site_id=site["id"], source_srid=999_999
        )
        assert response.status_code == 422
        assert "999999" in response.json()["detail"]

    def test_degrees_are_taken_at_face_value(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        payload = feature_collection(point_feature(TRENCH))
        body = import_file(client, payload, "wgs84.geojson", site_id=site["id"]).json()
        assert body["reprojected_from_srid"] is None

    def test_a_shapefiles_projection_file_is_read(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        """Our own exports carry a .prj, and it must be understood on the way back."""
        archive = formats.write_shapefile(
            [{"geometry": {"type": "Point", "coordinates": TRENCH}, "properties": {"name": "A"}}],
            name="datum",
        )
        response = import_file(client, archive, "datum.zip", site_id=site["id"])
        assert response.status_code == 201, response.text
        assert response.json()["reprojected_from_srid"] is None

    @pytest.mark.parametrize(
        ("coordinates", "plausible"),
        [
            ([35.85, 32.55], True),
            ([-179.9, -89.9], True),
            ([768000.0, 3604000.0], False),
            ([181.0, 0.0], False),
            ([0.0, 91.0], False),
        ],
    )
    def test_degree_plausibility(self, coordinates: list[float], plausible: bool) -> None:
        assert geo.looks_like_degrees(coordinates) is plausible

    def test_kml_is_always_wgs84(self, client: TestClient, researcher: User, site: dict) -> None:
        """KML defines its own coordinate system, so no question arises."""
        kml = formats.write_kml(
            [{"geometry": {"type": "Point", "coordinates": TRENCH}, "properties": {}}]
        )
        parsed = formats.read_kml(kml)
        assert parsed.srid_hint == 4326


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------
class TestExport:
    @pytest.fixture
    def populated(self, client: TestClient, researcher: User, site: dict) -> dict:
        payload = feature_collection(
            point_feature(TRENCH, name="Datum", year=2024),
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": SURVEY_POLYGON},
                "properties": {"name": "Survey area"},
            },
        )
        return import_file(client, payload, "survey.geojson", site_id=site["id"]).json()["layer"]

    def test_geojson_export_round_trips(
        self, client: TestClient, researcher: User, populated: dict
    ) -> None:
        response = client.get(
            f"/api/v1/gis/layers/{populated['id']}/export",
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/geo+json")

        document = json.loads(response.content)
        assert document["type"] == "FeatureCollection"
        assert len(document["features"]) == 2
        assert {feature["geometry"]["type"] for feature in document["features"]} == {
            "Point",
            "Polygon",
        }

    def test_kml_export_is_parseable_kml(
        self, client: TestClient, researcher: User, populated: dict
    ) -> None:
        response = client.get(
            f"/api/v1/gis/layers/{populated['id']}/export",
            params={"format": "kml"},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 200
        assert b"<kml" in response.content

        parsed = formats.read_kml(response.content)
        assert len(parsed.features) == 2

    def test_shapefile_export_splits_by_geometry_type(
        self, client: TestClient, researcher: User, populated: dict
    ) -> None:
        """A shapefile holds one geometry type; a mixed layer is several files."""
        response = client.get(
            f"/api/v1/gis/layers/{populated['id']}/export",
            params={"format": "shapefile"},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"

        names = set(zipfile.ZipFile(io.BytesIO(response.content)).namelist())
        assert any(name.endswith("_point.shp") for name in names)
        assert any(name.endswith("_polygon.shp") for name in names)
        # Every export says what coordinate system it is in.
        assert any(name.endswith(".prj") for name in names)

    def test_an_exported_shapefile_can_be_reimported(
        self, client: TestClient, researcher: User, site: dict, populated: dict
    ) -> None:
        """The round trip that matters: our export must be our own valid input."""
        exported = client.get(
            f"/api/v1/gis/layers/{populated['id']}/export",
            params={"format": "shapefile"},
            headers=auth_headers(client, "researcher"),
        ).content

        response = import_file(client, exported, "reimport.zip", site_id=site["id"])
        assert response.status_code == 201, response.text
        assert response.json()["imported"] == 2

    def test_export_can_be_limited_to_a_box(
        self, client: TestClient, researcher: User, populated: dict
    ) -> None:
        far_away = client.get(
            f"/api/v1/gis/layers/{populated['id']}/export",
            params={"bbox": "0,0,1,1"},
            headers=auth_headers(client, "researcher"),
        )
        assert json.loads(far_away.content)["features"] == []

    def test_exports_are_downloads_not_pages(
        self, client: TestClient, researcher: User, populated: dict
    ) -> None:
        response = client.get(
            f"/api/v1/gis/layers/{populated['id']}/export",
            headers=auth_headers(client, "researcher"),
        )
        assert response.headers["content-disposition"].startswith("attachment;")
        assert response.headers["x-content-type-options"] == "nosniff"


class TestSiteExport:
    def test_sites_export_as_points(self, client: TestClient, researcher: User, site: dict) -> None:
        response = client.get(
            "/api/v1/gis/export/sites", headers=auth_headers(client, "researcher")
        )
        assert response.status_code == 200

        document = json.loads(response.content)
        names = {feature["properties"]["name"] for feature in document["features"]}
        assert "Tell GIS" in names

    def test_a_restricted_sites_location_is_blurred_in_the_export(
        self, client: TestClient, db: Session, researcher: User, project: dict
    ) -> None:
        """An export is exactly how a restricted location would otherwise escape."""
        headers = auth_headers(client, "researcher")
        client.post(
            "/api/v1/sites",
            json={
                "project_id": project["id"],
                "name": "Looted Tell",
                "code": "LT",
                "latitude": 32.123456,
                "longitude": 35.987654,
                "location_restricted": True,
                "is_public": True,
            },
            headers=headers,
        )

        document = json.loads(client.get("/api/v1/gis/export/sites").content)
        restricted = next(
            feature
            for feature in document["features"]
            if feature["properties"]["name"] == "Looted Tell"
        )
        longitude, latitude = restricted["geometry"]["coordinates"]

        assert restricted["properties"]["location_is_approximate"] is True
        assert latitude == pytest.approx(32.12, abs=1e-9)
        assert longitude == pytest.approx(35.99, abs=1e-9)

    def test_the_owner_sees_the_true_location(
        self, client: TestClient, researcher: User, project: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        client.post(
            "/api/v1/sites",
            json={
                "project_id": project["id"],
                "name": "Owner View",
                "code": "OV",
                "latitude": 32.123456,
                "longitude": 35.987654,
                "location_restricted": True,
                "is_public": True,
            },
            headers=headers,
        )

        document = json.loads(client.get("/api/v1/gis/export/sites", headers=headers).content)
        owned = next(
            feature
            for feature in document["features"]
            if feature["properties"]["name"] == "Owner View"
        )
        assert owned["properties"]["location_is_approximate"] is False
        assert owned["geometry"]["coordinates"][1] == pytest.approx(32.123456, abs=1e-6)


# --------------------------------------------------------------------------
# Spatial search
# --------------------------------------------------------------------------
class TestSpatialSearch:
    @pytest.fixture
    def populated(self, client: TestClient, researcher: User, site: dict, layer: dict) -> dict:
        headers = auth_headers(client, "researcher")
        artifact = client.post(
            "/api/v1/artifacts",
            json={
                "site_id": site["id"],
                "inventory_number": "GIS-001",
                "name": "Near find",
                "latitude": TRENCH[1],
                "longitude": TRENCH[0],
                "is_public": True,
            },
            headers=headers,
        ).json()
        far = client.post(
            "/api/v1/artifacts",
            json={
                "site_id": site["id"],
                "inventory_number": "GIS-002",
                "name": "Far find",
                "latitude": 33.9,
                "longitude": 36.9,
                "is_public": True,
            },
            headers=headers,
        ).json()
        client.post(
            f"/api/v1/gis/layers/{layer['id']}/features",
            json={"geometry": {"type": "Point", "coordinates": TRENCH}, "name": "Datum"},
            headers=headers,
        )
        return {"artifact": artifact, "far": far}

    def test_nearby_finds_what_is_close_and_not_what_is_far(
        self, client: TestClient, researcher: User, populated: dict
    ) -> None:
        body = client.get(
            "/api/v1/spatial/nearby",
            params={"lat": TRENCH[1], "lon": TRENCH[0], "radius_m": 500},
            headers=auth_headers(client, "researcher"),
        ).json()

        labels = {item["label"] for item in body["items"]}
        assert "GIS-001" in labels
        assert "Tell GIS" in labels
        assert "GIS-002" not in labels, "a find 200 km away is not nearby"

    def test_nearby_is_ordered_by_distance(
        self, client: TestClient, researcher: User, site: dict, populated: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        client.post(
            "/api/v1/artifacts",
            json={
                "site_id": site["id"],
                "inventory_number": "GIS-003",
                "name": "Middle",
                "latitude": TRENCH[1] + 0.002,
                "longitude": TRENCH[0],
                "is_public": True,
            },
            headers=headers,
        )

        body = client.get(
            "/api/v1/spatial/nearby",
            params={"lat": TRENCH[1], "lon": TRENCH[0], "radius_m": 1000},
            headers=headers,
        ).json()

        distances = [item["distance_m"] for item in body["items"] if item["distance_m"] is not None]
        assert distances == sorted(distances)

    def test_the_radius_is_metres_not_degrees(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        """0.01° of longitude here is ~940 m, so a 500 m radius must exclude it."""
        headers = auth_headers(client, "researcher")
        client.post(
            "/api/v1/artifacts",
            json={
                "site_id": site["id"],
                "inventory_number": "GIS-EDGE",
                "name": "Just outside",
                "latitude": TRENCH[1],
                "longitude": TRENCH[0] + 0.01,
                "is_public": True,
            },
            headers=headers,
        )

        tight = client.get(
            "/api/v1/spatial/nearby",
            params={"lat": TRENCH[1], "lon": TRENCH[0], "radius_m": 500, "types": "artifact"},
            headers=headers,
        ).json()
        wide = client.get(
            "/api/v1/spatial/nearby",
            params={"lat": TRENCH[1], "lon": TRENCH[0], "radius_m": 1500, "types": "artifact"},
            headers=headers,
        ).json()

        assert "GIS-EDGE" not in {item["label"] for item in tight["items"]}
        assert "GIS-EDGE" in {item["label"] for item in wide["items"]}

    def test_types_narrows_the_search(
        self, client: TestClient, researcher: User, populated: dict
    ) -> None:
        body = client.get(
            "/api/v1/spatial/nearby",
            params={"lat": TRENCH[1], "lon": TRENCH[0], "radius_m": 1000, "types": "site"},
            headers=auth_headers(client, "researcher"),
        ).json()

        assert {item["resource_type"] for item in body["items"]} == {"site"}

    def test_bbox_finds_what_is_inside_the_viewport(
        self, client: TestClient, researcher: User, populated: dict
    ) -> None:
        body = client.get(
            "/api/v1/spatial/bbox",
            params={"bbox": "35.8,32.5,35.9,32.6"},
            headers=auth_headers(client, "researcher"),
        ).json()

        labels = {item["label"] for item in body["items"]}
        assert "GIS-001" in labels
        assert "GIS-002" not in labels

    def test_a_malformed_bbox_is_reported(self, client: TestClient, researcher: User) -> None:
        response = client.get(
            "/api/v1/spatial/bbox",
            params={"bbox": "not,a,box"},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 422

    def test_an_inverted_bbox_is_refused(self, client: TestClient, researcher: User) -> None:
        response = client.get(
            "/api/v1/spatial/bbox",
            params={"bbox": "36,33,35,32"},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 422
        assert "exceeds its maximum" in response.json()["detail"]

    def test_within_a_polygon(self, client: TestClient, researcher: User, populated: dict) -> None:
        response = client.post(
            "/api/v1/spatial/within",
            json={"geometry": {"type": "Polygon", "coordinates": SURVEY_POLYGON}},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 200, response.text

        labels = {item["label"] for item in response.json()["items"]}
        assert "GIS-001" in labels
        assert "GIS-002" not in labels

    def test_searching_inside_a_point_is_refused(
        self, client: TestClient, researcher: User
    ) -> None:
        response = client.post(
            "/api/v1/spatial/within",
            json={"geometry": {"type": "Point", "coordinates": TRENCH}},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 422
        assert "not meaningful" in response.json()["detail"]

    def test_a_projected_search_polygon_is_refused_without_an_srid(
        self, client: TestClient, researcher: User
    ) -> None:
        response = client.post(
            "/api/v1/spatial/within",
            json={
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [760000.0, 3600000.0],
                            [770000.0, 3600000.0],
                            [770000.0, 3610000.0],
                            [760000.0, 3610000.0],
                            [760000.0, 3600000.0],
                        ]
                    ],
                }
            },
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 422
        assert "source_srid" in response.json()["detail"]

    def test_a_projected_search_polygon_works_with_an_srid(
        self, client: TestClient, researcher: User, populated: dict
    ) -> None:
        response = client.post(
            "/api/v1/spatial/within",
            json={
                "source_srid": 32636,
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [760000.0, 3595000.0],
                            [780000.0, 3595000.0],
                            [780000.0, 3615000.0],
                            [760000.0, 3615000.0],
                            [760000.0, 3595000.0],
                        ]
                    ],
                },
            },
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 200, response.text
        assert "GIS-001" in {item["label"] for item in response.json()["items"]}

    def test_anonymous_callers_see_only_public_records(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        client.post(
            "/api/v1/artifacts",
            json={
                "site_id": site["id"],
                "inventory_number": "GIS-SECRET",
                "name": "Unpublished",
                "latitude": TRENCH[1],
                "longitude": TRENCH[0],
                "is_public": False,
            },
            headers=auth_headers(client, "researcher"),
        )

        body = client.get(
            "/api/v1/spatial/nearby",
            params={"lat": TRENCH[1], "lon": TRENCH[0], "radius_m": 1000},
        ).json()
        assert "GIS-SECRET" not in {item["label"] for item in body["items"]}


class TestRestrictedLocationsInSpatialSearch:
    @pytest.fixture
    def restricted_site(self, client: TestClient, researcher: User, project: dict) -> dict:
        response = client.post(
            "/api/v1/sites",
            json={
                "project_id": project["id"],
                "name": "Sensitive Tell",
                "code": "ST",
                "latitude": 32.123456,
                "longitude": 35.987654,
                "location_restricted": True,
                "is_public": True,
            },
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 201, response.text
        return response.json()

    def test_coordinates_are_blurred_for_a_stranger(
        self, client: TestClient, researcher: User, restricted_site: dict
    ) -> None:
        body = client.get(
            "/api/v1/spatial/nearby",
            params={"lat": 32.123456, "lon": 35.987654, "radius_m": 5000, "types": "site"},
        ).json()

        hit = next(item for item in body["items"] if item["label"] == "Sensitive Tell")
        assert hit["is_approximate"] is True
        assert hit["latitude"] == pytest.approx(32.12, abs=1e-9)
        assert hit["longitude"] == pytest.approx(35.99, abs=1e-9)

    def test_the_distance_is_withheld_rather_than_rounded(
        self, client: TestClient, researcher: User, restricted_site: dict
    ) -> None:
        """A precise distance from a known point undoes the blurring in one
        subtraction, so it is not given at all."""
        body = client.get(
            "/api/v1/spatial/nearby",
            params={"lat": 32.123456, "lon": 35.987654, "radius_m": 5000, "types": "site"},
        ).json()

        hit = next(item for item in body["items"] if item["label"] == "Sensitive Tell")
        assert hit["distance_m"] is None

    def test_the_owner_sees_the_true_position_and_distance(
        self, client: TestClient, researcher: User, restricted_site: dict
    ) -> None:
        body = client.get(
            "/api/v1/spatial/nearby",
            params={"lat": 32.123456, "lon": 35.987654, "radius_m": 5000, "types": "site"},
            headers=auth_headers(client, "researcher"),
        ).json()

        hit = next(item for item in body["items"] if item["label"] == "Sensitive Tell")
        assert hit["is_approximate"] is False
        assert hit["latitude"] == pytest.approx(32.123456, abs=1e-6)
        assert hit["distance_m"] is not None


# --------------------------------------------------------------------------
# The format layer, directly
# --------------------------------------------------------------------------
class TestFormats:
    def test_kml_billion_laughs_is_refused(self) -> None:
        """KML is XML, and XML from a stranger is an entity-expansion attack."""
        bomb = b"""<?xml version="1.0"?>
        <!DOCTYPE kml [
          <!ENTITY a "aaaaaaaaaa">
          <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">
          <!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">
        ]>
        <kml><Document><name>&c;</name></Document></kml>"""

        with pytest.raises(geo.GeometryError):
            formats.read_kml(bomb)

    def test_an_external_entity_is_refused(self) -> None:
        """The other half of the same problem: reading /etc/passwd."""
        xxe = b"""<?xml version="1.0"?>
        <!DOCTYPE kml [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
        <kml><Document><name>&xxe;</name></Document></kml>"""

        with pytest.raises(geo.GeometryError):
            formats.read_kml(xxe)

    def test_a_zip_with_absurdly_many_members_is_refused(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for index in range(formats.MAX_ZIP_MEMBERS + 5):
                archive.writestr(f"file{index}.txt", "x")

        with pytest.raises(geo.GeometryError, match="looks like something else"):
            formats.read_shapefile(buffer.getvalue())

    def test_a_zip_bomb_is_refused_before_it_is_read(self) -> None:
        """The declared uncompressed size is checked, not the compressed one."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("big.shp", b"\0" * (formats.MAX_UNCOMPRESSED_BYTES + 1))

        with pytest.raises(geo.GeometryError, match="over the"):
            formats.read_shapefile(buffer.getvalue())

    def test_a_traversal_member_name_is_harmless(self) -> None:
        """Nothing is written to disk, so a hostile name is only an odd name."""
        source = formats.write_shapefile(
            [{"geometry": {"type": "Point", "coordinates": TRENCH}, "properties": {"n": "1"}}],
            name="ok",
        )
        buffer = io.BytesIO()
        with (
            zipfile.ZipFile(io.BytesIO(source)) as original,
            zipfile.ZipFile(buffer, "w") as hostile,
        ):
            for info in original.infolist():
                suffix = info.filename.rsplit(".", 1)[1]
                hostile.writestr(f"../../../../tmp/evil.{suffix}", original.read(info))

        parsed = formats.read_shapefile(buffer.getvalue())
        assert len(parsed.features) == 1

    def test_geometry_collections_are_accepted(self) -> None:
        geometry = {
            "type": "GeometryCollection",
            "geometries": [
                {"type": "Point", "coordinates": TRENCH},
                {"type": "LineString", "coordinates": [TRENCH, [35.9, 32.6]]},
            ],
        }
        assert geo.validate_geojson_geometry(geometry) is geometry

    @pytest.mark.parametrize(
        "geometry",
        [
            {"type": "Circle", "coordinates": [0, 0]},
            {"type": "Point"},
            {"type": "Point", "coordinates": []},
            {"type": "Polygon", "coordinates": "not an array"},
            "not an object",
        ],
    )
    def test_unusable_geometries_are_refused(self, geometry: object) -> None:
        with pytest.raises(geo.GeometryError):
            geo.validate_geojson_geometry(geometry)

    def test_shapefile_polygon_winding_is_corrected(self) -> None:
        """GeoJSON and shapefiles wind exterior rings opposite ways.

        Writing GeoJSON order straight out makes every polygon read as a hole
        with no exterior — which loads, draws nothing, and reports no error.
        """
        counter_clockwise = [[35.0, 32.0], [35.1, 32.0], [35.1, 32.1], [35.0, 32.1], [35.0, 32.0]]
        rings = formats._shapefile_rings([counter_clockwise])
        assert formats._ring_is_clockwise(rings[0]), "the exterior ring must end up clockwise"

    def test_a_polygon_hole_survives_the_shapefile_round_trip(self) -> None:
        with_hole = {
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[35.0, 32.0], [35.1, 32.0], [35.1, 32.1], [35.0, 32.1], [35.0, 32.0]],
                    [
                        [35.02, 32.02],
                        [35.02, 32.08],
                        [35.08, 32.08],
                        [35.08, 32.02],
                        [35.02, 32.02],
                    ],
                ],
            },
            "properties": {"name": "Courtyard"},
        }
        archive = formats.write_shapefile([with_hole], name="courtyard")
        parsed = formats.read_shapefile(archive)

        assert len(parsed.features) == 1
        assert len(parsed.features[0].geometry["coordinates"]) == 2, "the hole is still a hole"

    def test_long_property_names_do_not_collide_in_the_attribute_table(self) -> None:
        """DBF column names cap at ten characters, so two long keys can collide."""
        features = [
            {
                "geometry": {"type": "Point", "coordinates": TRENCH},
                "properties": {"excavation_year": 2024, "excavation_zone": "A"},
            }
        ]
        columns = formats._attribute_columns(features)
        assert len(columns) == len(set(columns)), "truncated column names collided"

    def test_a_layer_with_no_attributes_can_still_be_written(self) -> None:
        """A DBF must declare at least one field.

        A trench outline or a contour set carries pure geometry and no
        attributes at all — the simplest possible layer, and the one that
        failed to export before a fallback column was added.
        """
        bare = [{"geometry": {"type": "Point", "coordinates": TRENCH}, "properties": {}}]
        archive = formats.write_shapefile(bare, name="bare")
        assert len(formats.read_shapefile(archive).features) == 1

    def test_kml_closes_an_unclosed_ring(self) -> None:
        """KML polygons routinely omit the closing coordinate; GeoJSON requires it."""
        kml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>
          <name>Open ring</name>
          <Polygon><outerBoundaryIs><LinearRing><coordinates>
            35.0,32.0 35.1,32.0 35.1,32.1 35.0,32.1
          </coordinates></LinearRing></outerBoundaryIs></Polygon>
        </Placemark></Document></kml>"""

        parsed = formats.read_kml(kml)
        ring = parsed.features[0].geometry["coordinates"][0]
        assert ring[0] == ring[-1]


class TestGisPermissions:
    def test_a_contributor_cannot_reshape_someone_elses_layer(
        self, client: TestClient, db: Session, researcher: User, layer: dict
    ) -> None:
        make_user(db, email="digger@example.org", username="digger")

        response = client.post(
            f"/api/v1/gis/layers/{layer['id']}/features",
            json={"geometry": {"type": "Point", "coordinates": TRENCH}},
            headers=auth_headers(client, "digger"),
        )
        assert response.status_code == 403

    def test_a_user_with_no_archaeology_access_cannot_create_a_layer(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        make_user(
            db,
            email="curator@example.org",
            username="curator",
            role=UserRole.VISITOR,
            modules={Module.MUSEUM: ModuleLevel.ADMINISTRATOR},
            grant_defaults=False,
        )
        response = client.post(
            "/api/v1/gis/layers",
            json={"site_id": site["id"], "name": "Museum layer"},
            headers=auth_headers(client, "curator"),
        )
        assert response.status_code in (403, 404)

    def test_anonymous_callers_cannot_import(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        response = client.post(
            "/api/v1/gis/import",
            files={"file": ("x.geojson", feature_collection(point_feature(TRENCH)), "text/plain")},
            data={"site_id": site["id"]},
        )
        assert response.status_code == 401


def test_every_searchable_type_has_a_geometry_column() -> None:
    """A type in one map and not the other would silently never be searched."""
    from app.api.v1.endpoints import spatial

    assert set(spatial._QUERY_OF) == set(spatial._GEOMETRY_OF)
    assert set(spatial.SEARCHABLE_TYPES) <= set(ResourceType)
