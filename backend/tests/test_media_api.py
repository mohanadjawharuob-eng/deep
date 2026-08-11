"""End-to-end tests for photographs, documents, 3D models and QR labels.

The images used here are generated rather than checked in, so the suite has no
binary fixtures and every property being asserted — dimensions, EXIF, GPS — is
visible in the test that depends on it.
"""

from __future__ import annotations

import io
import struct

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Photograph, ReviewStatus, User
from app.services import images
from tests.conftest import auth_headers, make_user


# --------------------------------------------------------------------------
# Image builders
# --------------------------------------------------------------------------
def make_image(
    width: int = 1200,
    height: int = 800,
    image_format: str = "JPEG",
    colour: tuple[int, int, int] = (120, 90, 60),
) -> bytes:
    image = Image.new("RGB", (width, height), colour)
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


#: Pointer tags for the two nested IFDs. Pillow only serialises a sub-IFD when
#: its pointer tag is assigned on the parent — mutating the dict that
#: ``get_ifd()`` returns writes nothing to the file.
_EXIF_IFD_POINTER = 0x8769
_GPS_IFD_POINTER = 0x8825


def make_image_with_exif(
    *,
    make: str = "NIKON CORPORATION",
    model: str = "NIKON D850",
    taken: str = "2024:05:04 09:13:22",
    latitude: tuple[float, float, float] = (32.0, 33.0, 20.0),
    longitude: tuple[float, float, float] = (35.0, 51.0, 0.0),
    latitude_ref: str = "N",
    longitude_ref: str = "E",
    altitude: float = 512.0,
    altitude_ref: int = 0,
) -> bytes:
    """A JPEG carrying camera identification, a timestamp and a GPS fix.

    32°33'20"N 35°51'0"E is in northern Jordan — a plausible trench, and far
    enough from zero that a sign error or a swapped pair would be obvious.
    """
    from PIL import ExifTags

    image = Image.new("RGB", (640, 480), (200, 180, 140))
    exif = image.getexif()

    tags = {name: tag for tag, name in ExifTags.TAGS.items()}
    exif[tags["Make"]] = make
    exif[tags["Model"]] = model
    exif[tags["DateTime"]] = taken
    exif[_EXIF_IFD_POINTER] = {tags["DateTimeOriginal"]: taken}

    gps_tags = {name: tag for tag, name in ExifTags.GPSTAGS.items()}
    exif[_GPS_IFD_POINTER] = {
        gps_tags["GPSLatitudeRef"]: latitude_ref,
        gps_tags["GPSLatitude"]: latitude,
        gps_tags["GPSLongitudeRef"]: longitude_ref,
        gps_tags["GPSLongitude"]: longitude,
        gps_tags["GPSAltitude"]: altitude,
        gps_tags["GPSAltitudeRef"]: altitude_ref,
    }

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def project(client: TestClient, researcher: User) -> dict:
    response = client.post(
        "/api/v1/projects",
        json={
            "name": "Media Test Project",
            "code": "media-1",
            "country": "Jordan",
            "is_public": True,
        },
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
            "name": "Tell Media",
            "code": "TM",
            "latitude": 32.5556,
            "longitude": 35.85,
            "is_public": True,
        },
        headers=auth_headers(client, "researcher"),
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def artifact(client: TestClient, researcher: User, site: dict) -> dict:
    response = client.post(
        "/api/v1/artifacts",
        json={
            "site_id": site["id"],
            "inventory_number": "TM-2024-001",
            "name": "Storage jar rim",
            "is_public": True,
        },
        headers=auth_headers(client, "researcher"),
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload_photo(
    client: TestClient,
    *,
    data: bytes | None = None,
    filename: str = "trench.jpg",
    content_type: str = "image/jpeg",
    identifier: str = "researcher",
    **fields: object,
) -> object:
    return client.post(
        "/api/v1/photographs",
        files={"file": (filename, data if data is not None else make_image(), content_type)},
        data={key: str(value) for key, value in fields.items()},
        headers=auth_headers(client, identifier),
    )


# --------------------------------------------------------------------------
# Photograph upload
# --------------------------------------------------------------------------
class TestPhotographUpload:
    def test_upload_records_dimensions_and_generates_thumbnails(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        response = upload_photo(client, artifact_id=artifact["id"], title="Rim sherd in situ")
        assert response.status_code == 201, response.text
        body = response.json()

        assert body["width"] == 1200 and body["height"] == 800
        assert body["mime_type"] == "image/jpeg"
        assert body["thumbnail_sizes"] == sorted(images.thumbnail_sizes())
        assert body["file_size"] > 0
        assert len(body["checksum"]) == 64

    def test_parents_are_filled_in_from_the_deepest_link(
        self, client: TestClient, researcher: User, project: dict, site: dict, artifact: dict
    ) -> None:
        body = upload_photo(client, artifact_id=artifact["id"]).json()

        # Only the artifact was named; the site and project come from it, which
        # is what lets a project-level gallery be one indexed query.
        assert body["artifact_id"] == artifact["id"]
        assert body["site_id"] == site["id"]
        assert body["project_id"] == project["id"]

    def test_format_is_decided_by_decoding_not_by_the_name_or_content_type(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        # A PNG claiming to be a GIF called .jpg. Both claims are attacker
        # controlled, so both are ignored.
        response = upload_photo(
            client,
            data=make_image(image_format="PNG"),
            filename="lying.jpg",
            content_type="image/gif",
            artifact_id=artifact["id"],
        )
        assert response.status_code == 201, response.text
        assert response.json()["mime_type"] == "image/png"

    def test_a_non_image_is_refused(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        response = upload_photo(
            client, data=b"This is a text file, not a photograph", artifact_id=artifact["id"]
        )
        assert response.status_code == 422
        assert "not an image" in response.json()["detail"].lower()

    def test_an_empty_file_is_refused(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        assert upload_photo(client, data=b"", artifact_id=artifact["id"]).status_code == 422

    def test_an_unattached_upload_is_refused(self, client: TestClient, researcher: User) -> None:
        response = upload_photo(client)
        assert response.status_code == 422
        assert "attach" in response.json()["detail"].lower()

    def test_anonymous_uploads_are_refused(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        response = client.post(
            "/api/v1/photographs",
            files={"file": ("x.jpg", make_image(), "image/jpeg")},
            data={"artifact_id": artifact["id"]},
        )
        assert response.status_code == 401

    def test_a_non_member_cannot_upload_to_someone_elses_project(
        self, client: TestClient, db: Session, researcher: User, artifact: dict
    ) -> None:
        make_user(db, email="outsider@example.org", username="outsider")
        response = upload_photo(client, identifier="outsider", artifact_id=artifact["id"])
        assert response.status_code == 403

    def test_identical_bytes_are_stored_once(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        data = make_image(colour=(11, 22, 33))
        first = upload_photo(client, data=data, artifact_id=artifact["id"]).json()
        second = upload_photo(
            client, data=data, filename="copy.jpg", artifact_id=artifact["id"]
        ).json()

        # Two records, one copy of the bytes — storage is content-addressed.
        assert first["id"] != second["id"]
        assert first["checksum"] == second["checksum"]

    def test_a_students_upload_waits_for_approval(
        self, client: TestClient, db: Session, researcher: User, artifact: dict, project: dict
    ) -> None:
        student = make_user(db, email="digger@example.org", username="digger")
        joined = client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": str(student.id), "role": "student"},
            headers=auth_headers(client, "researcher"),
        )
        assert joined.status_code == 201, joined.text

        response = upload_photo(client, identifier="digger", artifact_id=artifact["id"])
        assert response.status_code == 201, response.text
        assert response.json()["review_status"] == ReviewStatus.PENDING.value

    def test_upload_is_written_to_the_activity_log(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        photo = upload_photo(client, artifact_id=artifact["id"], title="Logged shot").json()
        feed = client.get(
            "/api/v1/activity", params={"limit": 20}, headers=auth_headers(client, "researcher")
        ).json()

        entries = [item for item in feed["items"] if item["resource_id"] == photo["id"]]
        assert entries and entries[0]["action"] == "upload"


# --------------------------------------------------------------------------
# EXIF
# --------------------------------------------------------------------------
class TestExif:
    def test_camera_time_and_position_are_read_from_the_file(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        body = upload_photo(client, data=make_image_with_exif(), artifact_id=artifact["id"]).json()

        assert body["camera_make"] == "NIKON CORPORATION"
        assert body["camera_model"] == "NIKON D850"
        assert body["taken_at"].startswith("2024-05-04T09:13:22")
        assert body["latitude"] == pytest.approx(32.5556, abs=1e-3)
        assert body["longitude"] == pytest.approx(35.85, abs=1e-3)
        assert body["altitude"] == pytest.approx(512, abs=1)
        assert body["exif"]["Make"] == "NIKON CORPORATION"

    def test_southern_and_western_references_are_signed(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        data = make_image_with_exif(latitude_ref="S", longitude_ref="W")
        body = upload_photo(client, data=data, artifact_id=artifact["id"]).json()

        assert body["latitude"] == pytest.approx(-32.5556, abs=1e-3)
        assert body["longitude"] == pytest.approx(-35.85, abs=1e-3)

    def test_a_typed_coordinate_beats_the_cameras(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        body = upload_photo(
            client,
            data=make_image_with_exif(),
            artifact_id=artifact["id"],
            latitude=31.0,
            longitude=36.0,
        ).json()

        assert body["latitude"] == pytest.approx(31.0)
        assert body["longitude"] == pytest.approx(36.0)

    def test_an_altitude_below_datum_stays_negative(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        """GPSAltitudeRef arrives as a raw byte, not the integer it represents."""
        data = make_image_with_exif(altitude=395.0, altitude_ref=1)
        body = upload_photo(client, data=data, artifact_id=artifact["id"]).json()
        assert body["altitude"] == pytest.approx(-395.0, abs=1)

    def test_an_image_without_exif_is_still_accepted(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        body = upload_photo(client, artifact_id=artifact["id"]).json()
        assert body["camera_make"] is None
        assert body["taken_at"] is None
        assert body["latitude"] is None

    def test_an_unrecognised_hemisphere_does_not_fail_the_upload(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        # A camera bug should cost the coordinates, not the photograph. An
        # unknown reference is read as positive rather than refused, which is
        # what every EXIF reader does.
        data = make_image_with_exif(latitude_ref="?", longitude_ref="?")
        response = upload_photo(client, data=data, artifact_id=artifact["id"])

        assert response.status_code == 201, response.text
        assert response.json()["latitude"] == pytest.approx(32.5556, abs=1e-3)

    @pytest.mark.parametrize(
        "dms",
        [("not", "a", "number"), (32.0, 33.0), None, (), ("32", None, "20")],
    )
    def test_unusable_coordinates_are_dropped_not_guessed(self, dms: object) -> None:
        from app.services.images import _degrees

        assert _degrees(dms, "N") is None

    def test_a_coordinate_outside_the_globe_is_dropped(self) -> None:
        from app.services.images import _degrees

        assert _degrees((999.0, 0.0, 0.0), "N") is None


# --------------------------------------------------------------------------
# Serving files and thumbnails
# --------------------------------------------------------------------------
class TestPhotographFiles:
    def test_original_is_returned_byte_for_byte(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        data = make_image(colour=(1, 2, 3))
        photo = upload_photo(client, data=data, artifact_id=artifact["id"]).json()

        response = client.get(
            f"/api/v1/photographs/{photo['id']}/file", headers=auth_headers(client, "researcher")
        )
        assert response.status_code == 200
        assert response.content == data
        assert response.headers["content-type"].startswith("image/jpeg")
        assert response.headers["x-content-type-options"] == "nosniff"

    def test_thumbnail_is_a_jpeg_no_larger_than_requested(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        photo = upload_photo(client, artifact_id=artifact["id"]).json()
        smallest = min(images.thumbnail_sizes())

        response = client.get(
            f"/api/v1/photographs/{photo['id']}/thumbnail",
            params={"size": smallest},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 200
        with Image.open(io.BytesIO(response.content)) as thumb:
            assert thumb.format == "JPEG"
            assert max(thumb.size) <= smallest
            # 1200x800 scaled to fit a square keeps its aspect ratio.
            assert thumb.size[0] > thumb.size[1]

    def test_thumbnail_carries_no_gps(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        """A thumbnail of a restricted site must not leak where it is."""
        photo = upload_photo(client, data=make_image_with_exif(), artifact_id=artifact["id"]).json()
        assert photo["latitude"] is not None, "the original does carry a position"

        response = client.get(
            f"/api/v1/photographs/{photo['id']}/thumbnail",
            headers=auth_headers(client, "researcher"),
        )
        with Image.open(io.BytesIO(response.content)) as thumb:
            assert not dict(thumb.getexif())

    def test_a_request_larger_than_any_thumbnail_gets_the_largest(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        photo = upload_photo(client, artifact_id=artifact["id"]).json()
        largest = max(images.thumbnail_sizes())

        response = client.get(
            f"/api/v1/photographs/{photo['id']}/thumbnail",
            params={"size": 4096},
            headers=auth_headers(client, "researcher"),
        )
        with Image.open(io.BytesIO(response.content)) as thumb:
            assert max(thumb.size) <= largest

    def test_portrait_orientation_is_honoured(self, client: TestClient) -> None:
        """A phone photograph is landscape bytes plus an orientation tag."""
        from PIL import ExifTags

        image = Image.new("RGB", (400, 200), (90, 90, 90))
        exif = image.getexif()
        exif[next(tag for tag, name in ExifTags.TAGS.items() if name == "Orientation")] = 6
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", exif=exif)

        thumbnail = images.make_thumbnail(buffer.getvalue(), 100)
        with Image.open(io.BytesIO(thumbnail)) as thumb:
            assert thumb.size[1] > thumb.size[0], "orientation 6 means rotate to portrait"

    def test_transparency_is_flattened_onto_white(self) -> None:
        image = Image.new("RGBA", (50, 50), (255, 0, 0, 0))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")

        thumbnail = images.make_thumbnail(buffer.getvalue(), 20)
        with Image.open(io.BytesIO(thumbnail)) as thumb:
            assert thumb.mode == "RGB"
            assert thumb.convert("RGB").getpixel((10, 10)) == (255, 255, 255)

    def test_a_missing_stored_file_is_reported_not_crashed(
        self, client: TestClient, db: Session, researcher: User, artifact: dict
    ) -> None:
        photo = upload_photo(client, artifact_id=artifact["id"]).json()
        row = db.get(Photograph, photo["id"])
        row.file_path = "photographs/00/00/nothing-here.jpg"
        row.thumbnails = None
        db.add(row)
        db.flush()

        response = client.get(
            f"/api/v1/photographs/{photo['id']}/file", headers=auth_headers(client, "researcher")
        )
        assert response.status_code == 404
        assert "restore" in response.json()["detail"].lower()


# --------------------------------------------------------------------------
# Visibility
# --------------------------------------------------------------------------
class TestPhotographVisibility:
    def test_a_private_photograph_is_invisible_to_anonymous_callers(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        photo = upload_photo(client, artifact_id=artifact["id"], is_public=False).json()

        assert client.get(f"/api/v1/photographs/{photo['id']}").status_code == 404
        assert client.get(f"/api/v1/photographs/{photo['id']}/file").status_code == 404
        assert client.get(f"/api/v1/photographs/{photo['id']}/thumbnail").status_code == 404

        listing = client.get("/api/v1/photographs").json()
        assert photo["id"] not in {item["id"] for item in listing["items"]}

    def test_a_public_photograph_is_visible_to_anonymous_callers(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        photo = upload_photo(client, artifact_id=artifact["id"], is_public=True).json()

        assert client.get(f"/api/v1/photographs/{photo['id']}").status_code == 200
        assert client.get(f"/api/v1/photographs/{photo['id']}/file").status_code == 200

    def test_an_outsider_cannot_edit_or_delete(
        self, client: TestClient, db: Session, researcher: User, artifact: dict
    ) -> None:
        make_user(db, email="passerby@example.org", username="passerby")
        photo = upload_photo(client, artifact_id=artifact["id"], is_public=True).json()

        patch = client.patch(
            f"/api/v1/photographs/{photo['id']}",
            json={"title": "Mine now"},
            headers=auth_headers(client, "passerby"),
        )
        assert patch.status_code == 403

        delete = client.delete(
            f"/api/v1/photographs/{photo['id']}", headers=auth_headers(client, "passerby")
        )
        assert delete.status_code == 403


# --------------------------------------------------------------------------
# Editing
# --------------------------------------------------------------------------
class TestPhotographEditing:
    def test_only_one_cover_survives_per_parent(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        first = upload_photo(
            client, data=make_image(colour=(1, 1, 1)), artifact_id=artifact["id"], is_cover=True
        ).json()
        second = upload_photo(
            client, data=make_image(colour=(2, 2, 2)), artifact_id=artifact["id"], is_cover=True
        ).json()

        assert second["is_cover"] is True
        refreshed = client.get(
            f"/api/v1/photographs/{first['id']}", headers=auth_headers(client, "researcher")
        ).json()
        assert refreshed["is_cover"] is False

    def test_covers_only_filters_the_listing(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        upload_photo(client, data=make_image(colour=(3, 3, 3)), artifact_id=artifact["id"])
        cover = upload_photo(
            client, data=make_image(colour=(4, 4, 4)), artifact_id=artifact["id"], is_cover=True
        ).json()

        listing = client.get(
            "/api/v1/photographs",
            params={"artifact_id": artifact["id"], "covers_only": True},
            headers=auth_headers(client, "researcher"),
        ).json()
        assert [item["id"] for item in listing["items"]] == [cover["id"]]

    def test_editing_records_a_revision(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        photo = upload_photo(client, artifact_id=artifact["id"], title="Before").json()
        client.patch(
            f"/api/v1/photographs/{photo['id']}",
            json={"title": "After", "shot_type": "detail"},
            headers=auth_headers(client, "researcher"),
        )

        history = client.get(
            f"/api/v1/photographs/{photo['id']}/revisions",
            headers=auth_headers(client, "researcher"),
        )
        assert history.status_code == 200, history.text
        assert history.json()["total"] >= 1

        current = client.get(
            f"/api/v1/photographs/{photo['id']}", headers=auth_headers(client, "researcher")
        ).json()
        assert current["title"] == "After" and current["shot_type"] == "detail"

    def test_deleting_removes_the_record_but_keeps_the_bytes(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        data = make_image(colour=(9, 9, 9))
        first = upload_photo(client, data=data, artifact_id=artifact["id"]).json()
        second = upload_photo(
            client, data=data, filename="same.jpg", artifact_id=artifact["id"]
        ).json()

        assert (
            client.delete(
                f"/api/v1/photographs/{first['id']}", headers=auth_headers(client, "researcher")
            ).status_code
            == 200
        )
        # The second record shares those bytes; deleting the first must not
        # have taken them away.
        assert (
            client.get(
                f"/api/v1/photographs/{second['id']}/file",
                headers=auth_headers(client, "researcher"),
            ).status_code
            == 200
        )


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------
PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
DOCX_BYTES = b"PK\x03\x04" + b"\x00" * 60
OLE_BYTES = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 60


def upload_document(
    client: TestClient,
    *,
    data: bytes = PDF_BYTES,
    filename: str = "report.pdf",
    content_type: str = "application/pdf",
    identifier: str = "researcher",
    **fields: object,
) -> object:
    return client.post(
        "/api/v1/documents",
        files={"file": (filename, data, content_type)},
        data={key: str(value) for key, value in fields.items()},
        headers=auth_headers(client, identifier),
    )


class TestDocuments:
    def test_a_pdf_uploads_and_is_typed_from_its_name(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        response = upload_document(client, site_id=site["id"])
        assert response.status_code == 201, response.text
        body = response.json()

        assert body["mime_type"] == "application/pdf"
        assert body["document_type"] == "report", "'report.pdf' looks like a report"
        assert body["site_id"] == site["id"]

    def test_contents_must_match_the_extension(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        response = upload_document(client, data=b"I am definitely not a PDF", site_id=site["id"])
        assert response.status_code == 422
        assert "not a pdf" in response.json()["detail"].lower()

    @pytest.mark.parametrize(
        ("filename", "data"),
        [
            ("payload.zip", b"PK\x03\x04rest"),
            ("page.html", b"<html><script>alert(1)</script></html>"),
            ("shell.exe", b"MZ\x90\x00"),
            ("map.svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"),
        ],
    )
    def test_dangerous_types_are_refused(
        self, client: TestClient, researcher: User, site: dict, filename: str, data: bytes
    ) -> None:
        response = upload_document(client, data=data, filename=filename, site_id=site["id"])
        assert response.status_code == 422
        assert "not accepted" in response.json()["detail"].lower()

    def test_a_file_without_an_extension_is_refused(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        response = upload_document(client, filename="mystery", site_id=site["id"])
        assert response.status_code == 422
        assert "extension" in response.json()["detail"].lower()

    def test_a_text_file_pretending_to_be_binary_is_refused(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        response = upload_document(
            client,
            data=b"\x00\x01\x02binary\x00",
            filename="notes.txt",
            content_type="text/plain",
            site_id=site["id"],
        )
        assert response.status_code == 422
        assert "does not contain text" in response.json()["detail"].lower()

    def test_office_and_opendocument_containers_are_accepted(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        for filename, data in (
            ("survey.docx", DOCX_BYTES),
            ("finds.xlsx", DOCX_BYTES),
            ("legacy.doc", OLE_BYTES),
        ):
            response = upload_document(client, data=data, filename=filename, site_id=site["id"])
            assert response.status_code == 201, f"{filename}: {response.text}"

    def test_text_is_extracted_and_becomes_searchable(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        body = upload_document(
            client,
            data=b"Context 1042 produced a bronze fibula near the north baulk.",
            filename="field-notes.txt",
            content_type="text/plain",
            site_id=site["id"],
        ).json()
        assert body["has_extracted_text"] is True

        found = client.get(
            "/api/v1/documents",
            params={"q": "fibula"},
            headers=auth_headers(client, "researcher"),
        ).json()
        assert body["id"] in {item["id"] for item in found["items"]}

    def test_a_pdfs_text_is_not_claimed_to_be_extracted(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        # Honest about what search can see: PDF extraction is a later milestone.
        body = upload_document(client, site_id=site["id"]).json()
        assert body["has_extracted_text"] is False

    def test_documents_are_always_served_as_downloads(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        document = upload_document(client, site_id=site["id"]).json()
        response = client.get(
            f"/api/v1/documents/{document['id']}/file",
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 200
        assert response.headers["content-disposition"].startswith("attachment;")
        assert response.headers["x-content-type-options"] == "nosniff"

    def test_a_hostile_filename_cannot_escape_the_disposition_header(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        document = upload_document(
            client, filename="../../etc/passwd.pdf", site_id=site["id"]
        ).json()
        response = client.get(
            f"/api/v1/documents/{document['id']}/file",
            headers=auth_headers(client, "researcher"),
        )
        disposition = response.headers["content-disposition"]
        assert ".." not in disposition and "/" not in disposition

    def test_a_private_document_is_invisible_to_anonymous_callers(
        self, client: TestClient, researcher: User, site: dict
    ) -> None:
        document = upload_document(client, site_id=site["id"], is_public=False).json()
        assert client.get(f"/api/v1/documents/{document['id']}").status_code == 404
        assert client.get(f"/api/v1/documents/{document['id']}/file").status_code == 404


# --------------------------------------------------------------------------
# 3D models
# --------------------------------------------------------------------------
class TestModels3D:
    @pytest.mark.parametrize(
        "url",
        [
            # The current form: a title slug ending in the model id.
            "https://sketchfab.com/3d-models/storage-jar-rim-" + "a" * 32,
            # The older bare form, and with a trailing slash.
            "https://sketchfab.com/models/" + "a" * 32,
            "https://www.sketchfab.com/models/" + "a" * 32 + "/",
        ],
    )
    def test_a_sketchfab_link_gets_an_embed_url(
        self, client: TestClient, researcher: User, artifact: dict, url: str
    ) -> None:
        response = client.post(
            "/api/v1/models3d",
            json={
                "artifact_id": artifact["id"],
                "title": "Jar rim photogrammetry",
                "external_url": url,
            },
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 201, response.text
        assert response.json()["embed_url"] == f"https://sketchfab.com/models/{'a' * 32}/embed"

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/viewer/model",
            "https://sketchfab.com/not-a-model-page",
            "https://evil.sketchfab.com.attacker.test/3d-models/" + "a" * 32,
        ],
    )
    def test_unrecognised_links_are_linked_not_framed(
        self, client: TestClient, researcher: User, artifact: dict, url: str
    ) -> None:
        response = client.post(
            "/api/v1/models3d",
            json={"artifact_id": artifact["id"], "title": "Elsewhere", "external_url": url},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 201, response.text
        assert response.json()["embed_url"] is None

    @pytest.mark.parametrize(
        "url", ["javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "file:///etc"]
    )
    def test_non_http_schemes_are_refused(
        self, client: TestClient, researcher: User, artifact: dict, url: str
    ) -> None:
        response = client.post(
            "/api/v1/models3d",
            json={"artifact_id": artifact["id"], "title": "Bad", "external_url": url},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 422

    def test_a_model_needs_a_source(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        response = client.post(
            "/api/v1/models3d",
            json={"artifact_id": artifact["id"], "title": "Nothing attached"},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 422

    def test_a_mesh_uploads_and_downloads(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        # A minimal binary glTF header: magic, version 2, total length.
        glb = b"glTF" + struct.pack("<II", 2, 20) + b"\x00" * 8

        response = client.post(
            "/api/v1/models3d/upload",
            files={"file": ("rim.glb", glb, "model/gltf-binary")},
            data={"artifact_id": artifact["id"], "title": "Decimated rim"},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["has_file"] is True and body["format"] == "glb"

        download = client.get(
            f"/api/v1/models3d/{body['id']}/file", headers=auth_headers(client, "researcher")
        )
        assert download.status_code == 200
        assert download.content == glb
        assert download.headers["content-disposition"].startswith("attachment;")

    def test_an_unknown_mesh_format_is_refused(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        response = client.post(
            "/api/v1/models3d/upload",
            files={"file": ("model.blend", b"BLENDER-v300", "application/octet-stream")},
            data={"artifact_id": artifact["id"]},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 422
        assert "mesh format" in response.json()["detail"].lower()

    def test_downloading_a_linked_model_says_where_it_lives(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        model = client.post(
            "/api/v1/models3d",
            json={
                "artifact_id": artifact["id"],
                "title": "Hosted elsewhere",
                "external_url": "https://repository.example.org/model",
            },
            headers=auth_headers(client, "researcher"),
        ).json()

        response = client.get(
            f"/api/v1/models3d/{model['id']}/file", headers=auth_headers(client, "researcher")
        )
        assert response.status_code == 404
        assert "external_url" in response.json()["detail"]

    def test_changing_the_link_recomputes_the_embed(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        model = client.post(
            "/api/v1/models3d",
            json={
                "artifact_id": artifact["id"],
                "title": "Rim",
                "external_url": "https://sketchfab.com/3d-models/rim-" + "b" * 32,
            },
            headers=auth_headers(client, "researcher"),
        ).json()
        assert model["embed_url"] is not None

        updated = client.patch(
            f"/api/v1/models3d/{model['id']}",
            json={"external_url": "https://example.org/somewhere-else"},
            headers=auth_headers(client, "researcher"),
        ).json()
        assert updated["embed_url"] is None


# --------------------------------------------------------------------------
# QR codes and labels
# --------------------------------------------------------------------------
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def decode_qr(png: bytes) -> str:
    """Read a QR code back, the way a phone camera would.

    Skips rather than fails when the decoder is absent, so the suite still runs
    for anyone who installed only the runtime requirements.
    """
    cv2 = pytest.importorskip("cv2", reason="opencv-python-headless is a dev-only dependency")
    numpy = pytest.importorskip("numpy")

    image = Image.open(io.BytesIO(png)).convert("L")

    # Upscale before decoding. OpenCV's detector is marginal on a code at the
    # size a label is printed at, and fails on *some* payloads and not others —
    # which showed up as a test that passed or failed depending on the random
    # token in the URL. What is under test is the payload, not OpenCV's
    # threshold, so give it a generous image. Nearest-neighbour keeps the
    # modules square rather than blurring their edges.
    if min(image.size) < 600:
        factor = -(-600 // min(image.size))
        image = image.resize(
            (image.width * factor, image.height * factor), Image.Resampling.NEAREST
        )

    decoded, *_ = cv2.QRCodeDetector().detectAndDecode(numpy.array(image))
    return decoded


class TestLabels:
    @pytest.mark.parametrize("kind", ["artifacts", "sites", "projects"])
    def test_every_labelled_record_has_a_token_and_a_url(
        self,
        client: TestClient,
        researcher: User,
        project: dict,
        site: dict,
        artifact: dict,
        kind: str,
    ) -> None:
        record = {"artifacts": artifact, "sites": site, "projects": project}[kind]

        response = client.get(
            f"/api/v1/{kind}/{record['id']}/label", headers=auth_headers(client, "researcher")
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert len(body["public_token"]) == 32
        assert body["public_token"] in body["url"]
        # The scan opens a page, not JSON.
        assert "/api/" not in body["url"]

    @pytest.mark.parametrize("kind", ["artifacts", "sites", "projects"])
    def test_the_qr_image_is_a_png(
        self,
        client: TestClient,
        researcher: User,
        project: dict,
        site: dict,
        artifact: dict,
        kind: str,
    ) -> None:
        record = {"artifacts": artifact, "sites": site, "projects": project}[kind]

        response = client.get(
            f"/api/v1/{kind}/{record['id']}/qr.png", headers=auth_headers(client, "researcher")
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content.startswith(PNG_MAGIC)
        with Image.open(io.BytesIO(response.content)) as code:
            assert code.size[0] == code.size[1], "a QR code is square"

    @pytest.mark.parametrize("kind", ["artifacts", "sites", "projects"])
    def test_a_scan_of_the_printed_code_returns_the_records_url(
        self,
        client: TestClient,
        researcher: User,
        project: dict,
        site: dict,
        artifact: dict,
        kind: str,
    ) -> None:
        """The point of the feature: the image has to actually scan."""
        record = {"artifacts": artifact, "sites": site, "projects": project}[kind]
        headers = auth_headers(client, "researcher")

        expected = client.get(f"/api/v1/{kind}/{record['id']}/label", headers=headers).json()["url"]
        png = client.get(f"/api/v1/{kind}/{record['id']}/qr.png", headers=headers).content

        assert decode_qr(png) == expected

    def test_the_smallest_printable_code_still_scans(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        """A label on a finds bag is small; the densest code must survive it."""
        headers = auth_headers(client, "researcher")
        expected = client.get(f"/api/v1/artifacts/{artifact['id']}/label", headers=headers).json()

        png = client.get(
            f"/api/v1/artifacts/{artifact['id']}/qr.png",
            params={"size": 2, "for_label": False},
            headers=headers,
        ).content

        assert decode_qr(png) == expected["url"]

    def test_a_larger_module_size_gives_a_larger_image(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        small = client.get(
            f"/api/v1/artifacts/{artifact['id']}/qr.png",
            params={"size": 4},
            headers=auth_headers(client, "researcher"),
        )
        large = client.get(
            f"/api/v1/artifacts/{artifact['id']}/qr.png",
            params={"size": 16},
            headers=auth_headers(client, "researcher"),
        )
        with Image.open(io.BytesIO(small.content)) as a, Image.open(io.BytesIO(large.content)) as b:
            assert b.size[0] > a.size[0]

    def test_scanning_a_label_resolves_the_record(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        label = client.get(
            f"/api/v1/artifacts/{artifact['id']}/label", headers=auth_headers(client, "researcher")
        ).json()

        response = client.get(
            f"/api/v1/scan/artifacts/{label['public_token']}",
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 200
        assert response.json()["id"] == artifact["id"]

    def test_an_unknown_token_is_not_found(self, client: TestClient) -> None:
        assert client.get(f"/api/v1/scan/artifacts/{'0' * 32}").status_code == 404

    def test_scanning_reveals_nothing_the_scanner_could_not_already_see(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        private = client.post(
            "/api/v1/artifacts",
            json={
                "site_id": site["id"],
                "inventory_number": "TM-2024-SECRET",
                "name": "Unpublished find",
                "is_public": False,
            },
            headers=auth_headers(client, "researcher"),
        ).json()

        label = client.get(
            f"/api/v1/artifacts/{private['id']}/label", headers=auth_headers(client, "researcher")
        ).json()

        # The owner can scan it; an anonymous holder of the same token cannot.
        assert client.get(f"/api/v1/scan/artifacts/{label['public_token']}").status_code == 404
        assert client.get(f"/api/v1/artifacts/{private['id']}/qr.png").status_code == 404
        assert client.get(f"/api/v1/artifacts/{private['id']}/label").status_code == 404

    def test_labels_are_not_offered_for_records_that_have_none(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        response = client.get(
            f"/api/v1/photographs/{artifact['id']}/label",
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 404

    def test_tokens_are_distinct_across_records(
        self, client: TestClient, researcher: User, project: dict, site: dict, artifact: dict
    ) -> None:
        tokens = set()
        for kind, record in (
            ("projects", project),
            ("sites", site),
            ("artifacts", artifact),
        ):
            body = client.get(
                f"/api/v1/{kind}/{record['id']}/label", headers=auth_headers(client, "researcher")
            ).json()
            tokens.add(body["public_token"])
        assert len(tokens) == 3

    def test_a_renamed_record_keeps_its_token(
        self, client: TestClient, researcher: User, artifact: dict
    ) -> None:
        """The whole point of a token: the printed label outlives the name."""
        before = client.get(
            f"/api/v1/artifacts/{artifact['id']}/label", headers=auth_headers(client, "researcher")
        ).json()["public_token"]

        client.patch(
            f"/api/v1/artifacts/{artifact['id']}",
            json={"name": "Reidentified as a bowl rim", "inventory_number": "TM-2024-999"},
            headers=auth_headers(client, "researcher"),
        )

        after = client.get(
            f"/api/v1/artifacts/{artifact['id']}/label", headers=auth_headers(client, "researcher")
        ).json()["public_token"]
        assert after == before


# --------------------------------------------------------------------------
# Storage internals
# --------------------------------------------------------------------------
class TestStorage:
    def test_a_path_escaping_the_root_is_refused(self) -> None:
        from app.services.storage import StorageError, storage

        for hostile in ("../../etc/passwd", "/etc/passwd", "photographs/../../../etc/passwd"):
            with pytest.raises(StorageError):
                storage.absolute_path(hostile)

    def test_a_filename_is_never_used_to_build_a_path(self) -> None:
        from app.services.storage import CATEGORY_DOCUMENTS, storage

        stored = storage.save_bytes(b"contents", category=CATEGORY_DOCUMENTS, extension=".txt")
        # Content-addressed: the name of the file is its digest, and nothing a
        # client sent appears in the path at all.
        assert stored.path.startswith(f"{CATEGORY_DOCUMENTS}/")
        assert stored.checksum in stored.path
        assert stored.path.endswith(".txt")

    def test_storing_the_same_bytes_twice_writes_once(self) -> None:
        from app.services.storage import CATEGORY_DOCUMENTS, storage

        first = storage.save_bytes(b"identical", category=CATEGORY_DOCUMENTS, extension=".txt")
        second = storage.save_bytes(b"identical", category=CATEGORY_DOCUMENTS, extension=".txt")

        assert first.path == second.path
        assert second.deduplicated is True

    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            # Only the last component survives, so no traversal remains.
            ("../../etc/passwd", "passwd"),
            ("C:\\Users\\dig\\photo.jpg", "photo.jpg"),
            ("report final.pdf", "report_final.pdf"),
            ('quote".pdf', "quote_.pdf"),
            ("...", "download"),
            ("", "download"),
            (None, "download"),
        ],
    )
    def test_filenames_are_reduced_to_something_safe_to_echo(
        self, given: str | None, expected: str
    ) -> None:
        from app.services.storage import safe_filename

        assert safe_filename(given, "download") == expected

    def test_deleting_a_shared_file_leaves_the_bytes_alone(self) -> None:
        from app.services.storage import CATEGORY_DOCUMENTS, storage

        stored = storage.save_bytes(b"shared bytes", category=CATEGORY_DOCUMENTS, extension=".txt")
        assert storage.delete(stored.path) is False
        assert storage.exists(stored.path) is True

        assert storage.delete(stored.path, shared=False) is True
        assert storage.exists(stored.path) is False


class TestImageService:
    def test_a_decompression_bomb_is_refused(self) -> None:
        """A small file that claims enormous dimensions."""
        with pytest.raises(images.ImageError):
            images.inspect(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    def test_an_oversized_upload_is_refused_while_reading(self) -> None:
        stream = io.BytesIO(b"x" * (3 * 1024 * 1024))
        with pytest.raises(images.ImageError, match="larger than"):
            images.read_upload(stream, max_bytes=1024 * 1024)

    def test_an_svg_is_not_an_image(self) -> None:
        svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
        with pytest.raises(images.ImageError):
            images.inspect(svg)


class TestSeedMedia:
    """The demonstration project's images are drawn at seed time.

    They go through the same validation and thumbnail path as a real upload, so
    a change that breaks uploads breaks seeding too — and a broken seed means a
    new deployment first sees the platform with an empty, apparently faulty
    gallery.
    """

    def test_the_placeholder_is_a_valid_image(self) -> None:
        from scripts.seed import _placeholder_image

        facts = images.inspect(_placeholder_image("Context 1042", "North-facing section"))
        assert facts.format == "JPEG"
        assert facts.width > 0 and facts.height > 0

    def test_the_placeholder_thumbnails_cleanly(self) -> None:
        from scripts.seed import _placeholder_image

        data = _placeholder_image("Tell el-Demo", "Site overview")
        for size in images.thumbnail_sizes():
            with Image.open(io.BytesIO(images.make_thumbnail(data, size))) as thumb:
                assert max(thumb.size) <= size

    def test_the_placeholder_carries_a_visible_disclaimer(self) -> None:
        """It must never be mistakable for real excavation material.

        Checks the drawn pixels rather than the source: the warning is only
        useful if it actually reaches the image.
        """
        from scripts.seed import _placeholder_image

        with Image.open(io.BytesIO(_placeholder_image("A site", "A caption"))) as card:
            footer = card.convert("RGB").crop((0, card.height - 175, card.width, card.height - 110))
            reddish = [
                pixel
                for pixel in footer.getdata()
                if pixel[0] > pixel[1] + 40 and pixel[0] > pixel[2] + 40
            ]

        assert reddish, "the 'PLACEHOLDER' warning was not drawn onto the image"


def test_every_photograph_row_keeps_its_thumbnail_map(
    client: TestClient, db: Session, researcher: User, artifact: dict
) -> None:
    """The map on the row must name files that actually exist."""
    from app.services.storage import storage

    upload_photo(client, artifact_id=artifact["id"])
    rows = db.scalars(select(Photograph)).all()
    assert rows

    for row in rows:
        for size, path in (row.thumbnails or {}).items():
            assert storage.exists(path), f"thumbnail {size} is recorded but missing"


# --------------------------------------------------------------------------
# The museum half of the platform
# --------------------------------------------------------------------------
@pytest.fixture
def curator(db: Session) -> User:
    from app.models import Module, ModuleLevel, UserRole

    return make_user(
        db,
        email="curator@example.org",
        username="curator",
        role=UserRole.VISITOR,
        modules={Module.MUSEUM: ModuleLevel.SUPERVISOR},
        grant_defaults=False,
    )


@pytest.fixture
def outsider(db: Session) -> User:
    from app.models import UserRole

    return make_user(
        db,
        email="nobody@example.org",
        username="outsider",
        role=UserRole.VISITOR,
        grant_defaults=False,
    )


@pytest.fixture
def museum_collection(client: TestClient, curator: User) -> dict:
    response = client.post(
        "/api/v1/museum/collections",
        json={"name": "Ceramics", "code": "cer", "accession_prefix": "NM"},
        headers=auth_headers(client, "curator"),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _object(client: TestClient, collection: dict, title: str) -> dict:
    response = client.post(
        "/api/v1/museum/objects",
        json={"title": title, "collection_id": collection["id"]},
        headers=auth_headers(client, "curator"),
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def museum_object(client: TestClient, curator: User, museum_collection: dict) -> dict:
    return _object(client, museum_collection, "Dish")


@pytest.fixture
def other_object(client: TestClient, curator: User, museum_collection: dict) -> dict:
    return _object(client, museum_collection, "Lamp")


class TestMuseumObjectMedia:
    """An accessioned object can carry a photograph.

    It could not, until now, and the reason was structural rather than
    deliberate: every media record hung from an excavation record, and an
    accessioned object is not one. The catalogue screen showed a photograph
    panel that was reading *every* photograph in the platform, because the
    filter it passed did not exist and was silently ignored - so an object
    with none showed somebody else's site.
    """

    def test_a_photograph_can_be_attached_to_an_object(
        self, client: TestClient, curator: User, museum_object: dict
    ) -> None:
        response = client.post(
            "/api/v1/photographs",
            files={"file": ("dish.png", make_image(80, 60, "PNG"), "image/png")},
            data={"title": "The dish, from above", "museum_object_id": museum_object["id"]},
            headers=auth_headers(client, "curator"),
        )
        assert response.status_code == 201, response.text
        assert response.json()["museum_object_id"] == museum_object["id"]

    def test_the_filter_shows_only_that_objects_photographs(
        self, client: TestClient, curator: User, museum_object: dict, other_object: dict
    ) -> None:
        for target, name in ((museum_object, "mine.png"), (other_object, "theirs.png")):
            client.post(
                "/api/v1/photographs",
                files={"file": (name, make_image(80, 60, "PNG"), "image/png")},
                data={"title": name, "museum_object_id": target["id"]},
                headers=auth_headers(client, "curator"),
            )

        listing = client.get(
            "/api/v1/photographs",
            params={"museum_object_id": museum_object["id"]},
            headers=auth_headers(client, "curator"),
        ).json()

        assert listing["total"] == 1
        assert listing["items"][0]["title"] == "mine.png"

    def test_an_object_with_no_photographs_shows_none(
        self, client: TestClient, curator: User, museum_object: dict, other_object: dict
    ) -> None:
        """The bug that started this: an unrecognised filter used to be
        ignored, so a panel asking for one object's pictures was handed the
        whole platform's."""
        client.post(
            "/api/v1/photographs",
            files={"file": ("theirs.png", make_image(80, 60, "PNG"), "image/png")},
            data={"title": "theirs", "museum_object_id": other_object["id"]},
            headers=auth_headers(client, "curator"),
        )

        listing = client.get(
            "/api/v1/photographs",
            params={"museum_object_id": museum_object["id"]},
            headers=auth_headers(client, "curator"),
        ).json()

        assert listing["total"] == 0

    def test_it_needs_museum_permission_not_a_project(
        self, client: TestClient, curator: User, outsider: User, museum_object: dict
    ) -> None:
        """An object may have been donated in 1890 and have no project above
        it, so the check cannot be a project one."""
        response = client.post(
            "/api/v1/photographs",
            files={"file": ("x.png", make_image(80, 60, "PNG"), "image/png")},
            data={"museum_object_id": museum_object["id"]},
            headers=auth_headers(client, "outsider"),
        )
        assert response.status_code in (403, 404), response.text
