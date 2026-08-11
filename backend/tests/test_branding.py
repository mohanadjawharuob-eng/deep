"""The institution's mark, and each person's photograph.

Two properties are worth defending here and the rest is plumbing.

**An upload is decided by decoding it, not by what it is called.** A logo is
served inline, from the API's own origin, to every visitor including the ones
who are not signed in. If the uploader gets to choose the media type by naming
the file, then an SVG — which is a document that can carry script — becomes a
script running on this origin with the session in reach.

**Setting the name at the top of every page is not a personal preference.**
Reading it is public, because the sign-in page has to draw it; writing it is an
administrator's job.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User, UserRole
from tests.conftest import auth_headers, make_user


def png(size: tuple[int, int] = (64, 64), colour: str = "#8b3a1f") -> bytes:
    from PIL import Image

    stream = io.BytesIO()
    Image.new("RGB", size, colour).save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def admin(db: Session) -> User:
    return make_user(db, email="admin2@example.org", username="admin2", role=UserRole.ADMIN)


@pytest.fixture
def student(db: Session) -> User:
    return make_user(db, email="stu@example.org", username="stu", role=UserRole.STUDENT)


def upload_logo(client: TestClient, data: bytes, name: str = "logo.png", identifier="admin2"):
    return client.post(
        "/api/v1/branding/logo",
        files={"file": (name, data, "image/png")},
        headers=auth_headers(client, identifier),
    )


class TestTheInstitutionsName:
    def test_it_reads_without_an_account(self, client: TestClient) -> None:
        """The sign-in page has nobody signed in and still has to draw it."""
        response = client.get("/api/v1/branding")
        assert response.status_code == 200, response.text
        assert response.json()["display_name"] == "Stratum"

    def test_an_administrator_sets_it(self, client: TestClient, admin: User) -> None:
        response = client.put(
            "/api/v1/branding",
            json={"organisation_name": "Department of Antiquities", "tagline": "Field records"},
            headers=auth_headers(client, "admin2"),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["organisation_name"] == "Department of Antiquities"
        assert body["display_name"] == "Department of Antiquities"

        # And everybody sees it, including a visitor who is not signed in.
        assert client.get("/api/v1/branding").json()["tagline"] == "Field records"

    def test_a_student_cannot(self, client: TestClient, student: User) -> None:
        response = client.put(
            "/api/v1/branding",
            json={"organisation_name": "Mine now"},
            headers=auth_headers(client, "stu"),
        )
        assert response.status_code == 403

    def test_an_empty_string_clears_it(self, client: TestClient, admin: User) -> None:
        headers = auth_headers(client, "admin2")
        client.put("/api/v1/branding", json={"organisation_name": "Temporary"}, headers=headers)
        body = client.put(
            "/api/v1/branding", json={"organisation_name": ""}, headers=headers
        ).json()

        assert body["organisation_name"] is None
        assert body["display_name"] == "Stratum"

    def test_a_field_that_is_not_sent_is_not_touched(self, client: TestClient, admin: User) -> None:
        """Otherwise editing the tagline silently deletes the name."""
        headers = auth_headers(client, "admin2")
        client.put(
            "/api/v1/branding",
            json={"organisation_name": "Museum", "tagline": "Since 1892"},
            headers=headers,
        )
        body = client.put(
            "/api/v1/branding", json={"tagline": "Since 1893"}, headers=headers
        ).json()

        assert body["organisation_name"] == "Museum"
        assert body["tagline"] == "Since 1893"


class TestTheLogo:
    def test_it_is_uploaded_and_served(self, client: TestClient, admin: User) -> None:
        body = upload_logo(client, png()).json()
        assert body["logo_url"] is not None

        image = client.get(body["logo_url"].split("?")[0])
        assert image.status_code == 200
        assert image.headers["content-type"].startswith("image/")

    def test_the_url_changes_when_the_logo_does(self, client: TestClient, admin: User) -> None:
        """A logo that changes at an address that does not is a logo half the
        staff keep seeing the old version of for a week."""
        first = upload_logo(client, png(colour="#8b3a1f")).json()["logo_url"]
        second = upload_logo(client, png(colour="#2f5d50")).json()["logo_url"]

        assert first != second

    def test_the_same_image_twice_keeps_the_same_url(self, client: TestClient, admin: User) -> None:
        """Content-addressed storage: re-uploading the identical file is a no-op."""
        data = png()
        assert (
            upload_logo(client, data).json()["logo_url"]
            == upload_logo(client, data).json()["logo_url"]
        )

    def test_an_svg_named_as_a_png_is_refused(self, client: TestClient, admin: User) -> None:
        """The one that matters.

        The logo is served inline from this origin to everybody, signed in or
        not. If the uploader's chosen filename decided the media type, an SVG —
        a document that can carry script — would run here.
        """
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        response = upload_logo(client, svg, name="logo.png")

        assert response.status_code == 422
        assert "image" in response.json()["detail"].lower()

    def test_something_that_is_not_an_image_at_all_is_refused(
        self, client: TestClient, admin: User
    ) -> None:
        response = upload_logo(client, b"not an image at all", name="logo.png")
        assert response.status_code == 422

    def test_a_student_cannot_upload_one(self, client: TestClient, student: User) -> None:
        assert upload_logo(client, png(), identifier="stu").status_code == 403

    def test_removing_it_falls_back_to_the_platforms_own_mark(
        self, client: TestClient, admin: User
    ) -> None:
        upload_logo(client, png())
        body = client.delete("/api/v1/branding/logo", headers=auth_headers(client, "admin2")).json()

        assert body["logo_url"] is None
        assert client.get("/api/v1/branding/logo").status_code == 404


class TestAvatars:
    def test_somebody_sets_their_own(self, client: TestClient, student: User) -> None:
        response = client.post(
            "/api/v1/users/me/avatar",
            files={"file": ("me.png", png(), "image/png")},
            headers=auth_headers(client, "stu"),
        )
        assert response.status_code == 200, response.text
        assert response.json()["avatar_url"] == f"/api/v1/users/{student.id}/avatar"

        served = client.get(
            f"/api/v1/users/{student.id}/avatar", headers=auth_headers(client, "stu")
        )
        assert served.status_code == 200

    def test_it_needs_an_account_to_see(self, client: TestClient, student: User) -> None:
        client.post(
            "/api/v1/users/me/avatar",
            files={"file": ("me.png", png(), "image/png")},
            headers=auth_headers(client, "stu"),
        )
        assert client.get(f"/api/v1/users/{student.id}/avatar").status_code == 401

    def test_nobody_may_set_somebody_elses(
        self, client: TestClient, student: User, admin: User
    ) -> None:
        response = client.post(
            "/api/v1/users/me/avatar",
            files={"file": ("me.png", png(), "image/png")},
            data={"user_id": str(admin.id)},
            headers=auth_headers(client, "stu"),
        )
        assert response.status_code == 403

    def test_an_administrator_may(self, client: TestClient, student: User, admin: User) -> None:
        """The person who cannot work out how to upload a photograph is the
        person who asks the administrator to do it."""
        response = client.post(
            "/api/v1/users/me/avatar",
            files={"file": ("them.png", png(), "image/png")},
            data={"user_id": str(student.id)},
            headers=auth_headers(client, "admin2"),
        )
        assert response.status_code == 200, response.text
        assert response.json()["user_id"] == str(student.id)

    def test_removing_it(self, client: TestClient, student: User) -> None:
        headers = auth_headers(client, "stu")
        client.post(
            "/api/v1/users/me/avatar",
            files={"file": ("me.png", png(), "image/png")},
            headers=headers,
        )
        assert (
            client.delete("/api/v1/users/me/avatar", headers=headers).json()["avatar_url"] is None
        )
        assert client.get(f"/api/v1/users/{student.id}/avatar", headers=headers).status_code == 404

    def test_a_file_that_is_not_an_image_is_refused(
        self, client: TestClient, student: User
    ) -> None:
        response = client.post(
            "/api/v1/users/me/avatar",
            files={"file": ("cv.pdf", b"%PDF-1.4 not really", "application/pdf")},
            headers=auth_headers(client, "stu"),
        )
        assert response.status_code == 422
