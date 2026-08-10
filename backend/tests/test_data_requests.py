"""Asking somebody outside the platform for a file.

The feature exists because the photographs of a find are on a colleague's
laptop and that colleague will never make an account. So it opens a door in the
sign-in wall, and almost every test here is about how narrow that door is.

The invitation is a **capability, not an account**. Holding one lets you write
files to exactly one record. The tests below hold that line from both sides: a
valid link can send a file and nothing else, and an invalid one cannot be told
apart from a link that never existed.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import DataRequest, DataRequestStatus, Module, ModuleLevel, User, UserRole
from app.services import datarequests
from tests.conftest import auth_headers, make_user


@pytest.fixture
def director(db: Session) -> User:
    return make_user(db, email="dir@example.org", username="dir", role=UserRole.ADMIN)


@pytest.fixture
def outsider(db: Session) -> User:
    """Somebody with an account but nothing to do with this project."""
    return make_user(
        db,
        email="other@example.org",
        username="other",
        role=UserRole.VISITOR,
        modules={Module.MUSEUM: ModuleLevel.SUPERVISOR},
        grant_defaults=False,
    )


@pytest.fixture
def dig(client: TestClient, director: User) -> dict:
    headers = auth_headers(client, "dir")
    project = client.post(
        "/api/v1/projects", json={"name": "Tell el-Demo", "code": "TED"}, headers=headers
    ).json()
    site = client.post(
        "/api/v1/sites",
        json={"name": "North trench", "code": "TED-A", "project_id": project["id"]},
        headers=headers,
    ).json()
    return {"project": project, "site": site}


def ask(client: TestClient, site_id: str, *, identifier: str = "dir", **fields) -> dict:
    body = {
        "recipient_email": "photographer@example.org",
        "recipient_name": "A. Photographer",
        "kind": "photographs",
        "message": "The trench shots from the last week of the season, please.",
        "site_id": site_id,
        **fields,
    }
    response = client.post(
        "/api/v1/data-requests", json=body, headers=auth_headers(client, identifier)
    )
    assert response.status_code == 201, response.text
    return response.json()


def png(colour: tuple[int, int, int] = (120, 90, 60)) -> bytes:
    """A real image, because the platform validates by decoding."""
    pillow = pytest.importorskip("PIL.Image")
    buffer = io.BytesIO()
    pillow.new("RGB", (40, 30), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def token_of(url: str) -> str:
    return url.rsplit("/", 1)[-1]


# --------------------------------------------------------------------------
# Making the request
# --------------------------------------------------------------------------
class TestAsking:
    def test_a_request_names_the_record_and_returns_a_link(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        created = ask(client, dig["site"]["id"])

        # The label is resolved now and stored, so the list still reads
        # sensibly after somebody renames the site.
        assert "TED-A" in created["record_label"]
        assert created["uploads_left"] == created["max_uploads"]
        assert created["invite_url"].startswith("http")
        assert token_of(created["invite_url"])

    def test_the_link_is_shown_once_and_never_again(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """Only the hash is stored. A platform that can show you the link again
        is a platform whose database contains working links."""
        created = ask(client, dig["site"]["id"])

        again = client.get(
            f"/api/v1/data-requests/{created['id']}", headers=auth_headers(client, "dir")
        ).json()
        assert "invite_url" not in again
        assert token_of(created["invite_url"]) not in str(again)

    def test_a_request_must_be_about_something(self, client: TestClient, director: User) -> None:
        response = client.post(
            "/api/v1/data-requests",
            json={"recipient_email": "a@example.org"},
            headers=auth_headers(client, "dir"),
        )
        assert response.status_code == 422

    def test_you_cannot_ask_for_files_for_a_record_you_cannot_contribute_to(
        self, client: TestClient, director: User, outsider: User, dig: dict
    ) -> None:
        """Otherwise the door in the wall is wider than the wall: invite a
        stranger to write files into a project you have no access to."""
        response = client.post(
            "/api/v1/data-requests",
            json={"recipient_email": "a@example.org", "site_id": dig["site"]["id"]},
            headers=auth_headers(client, "other"),
        )
        assert response.status_code in (403, 404, 422), response.text

    def test_mail_failing_leaves_a_usable_request_and_says_so(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """No SMTP is configured in tests, which is the same situation as a
        site machine with no outbound mail. The link must still work, and the
        requester must not be left believing somebody was asked."""
        created = ask(client, dig["site"]["id"])

        assert created["status"] == DataRequestStatus.OPEN.value
        assert created["delivery_note"]
        assert created["sent_at"] is None

        # And the link works regardless.
        invite = client.get(f"/api/v1/data-requests/invite/{token_of(created['invite_url'])}")
        assert invite.status_code == 200, invite.text


# --------------------------------------------------------------------------
# What the stranger sees
# --------------------------------------------------------------------------
class TestTheInvitation:
    def test_it_names_the_record_and_nothing_else_about_it(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        created = ask(client, dig["site"]["id"])
        body = client.get(f"/api/v1/data-requests/invite/{token_of(created['invite_url'])}").json()

        assert body["record_label"] == created["record_label"]
        assert body["asked_for"] == "photographs"
        assert body["uploads_left"] == created["max_uploads"]
        # Nothing that would let a forwarded invitation become a window into
        # the archive: no identifiers, no description, no other recipients.
        assert dig["site"]["id"] not in str(body)
        assert dig["project"]["id"] not in str(body)
        assert "recipient_email" not in body

    def test_an_invented_token_and_a_withdrawn_one_are_indistinguishable(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        created = ask(client, dig["site"]["id"])
        token = token_of(created["invite_url"])

        client.delete(f"/api/v1/data-requests/{created['id']}", headers=auth_headers(client, "dir"))

        withdrawn = client.get(f"/api/v1/data-requests/invite/{token}")
        invented = client.get("/api/v1/data-requests/invite/not-a-real-token-at-all")

        assert withdrawn.status_code == invented.status_code == 404
        assert withdrawn.json()["detail"] == invented.json()["detail"]

    def test_an_expired_link_is_refused(
        self, client: TestClient, db: Session, director: User, dig: dict
    ) -> None:
        created = ask(client, dig["site"]["id"])
        token = token_of(created["invite_url"])

        record = db.get(DataRequest, created["id"])
        record.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        # Committed, not merely flushed. The test client rolls the session back
        # whenever a request raises, and the first assertion below is a request
        # that raises — an un-committed change would be undone by it and the
        # second assertion would then be testing a link that is live again.
        db.commit()

        assert client.get(f"/api/v1/data-requests/invite/{token}").status_code == 404
        sent = client.post(
            f"/api/v1/data-requests/invite/{token}",
            files={"file": ("a.png", png(), "image/png")},
        )
        assert sent.status_code == 404


# --------------------------------------------------------------------------
# Sending a file
# --------------------------------------------------------------------------
class TestSending:
    def test_a_photograph_arrives_attached_to_the_record_it_was_asked_for(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        created = ask(client, dig["site"]["id"])
        token = token_of(created["invite_url"])

        sent = client.post(
            f"/api/v1/data-requests/invite/{token}",
            files={"file": ("trench-a.png", png(), "image/png")},
            data={"note": "Looking north."},
        )
        assert sent.status_code == 201, sent.text
        assert sent.json()["uploads_left"] == created["max_uploads"] - 1

        listing = client.get(
            "/api/v1/photographs",
            params={"site_id": dig["site"]["id"]},
            headers=auth_headers(client, "dir"),
        ).json()
        assert listing["total"] == 1
        assert listing["items"][0]["title"] == "trench-a.png"

    def test_an_arriving_file_cannot_choose_its_own_record(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """The record is fixed when the request is made. A form field sent with
        the file must not be able to redirect it somewhere else."""
        headers = auth_headers(client, "dir")
        elsewhere = client.post(
            "/api/v1/sites",
            json={"name": "South mound", "code": "TED-B", "project_id": dig["project"]["id"]},
            headers=headers,
        ).json()

        created = ask(client, dig["site"]["id"])
        client.post(
            f"/api/v1/data-requests/invite/{token_of(created['invite_url'])}",
            files={"file": ("a.png", png(), "image/png")},
            data={"site_id": elsewhere["id"], "project_id": dig["project"]["id"]},
        )

        moved = client.get(
            "/api/v1/photographs", params={"site_id": elsewhere["id"]}, headers=headers
        ).json()
        assert moved["total"] == 0

    def test_arriving_files_wait_for_review(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """Nobody inside the institution has looked at this yet, and a file
        that came from outside is exactly what review is for."""
        created = ask(client, dig["site"]["id"])
        client.post(
            f"/api/v1/data-requests/invite/{token_of(created['invite_url'])}",
            files={"file": ("a.png", png(), "image/png")},
        )

        listing = client.get(
            "/api/v1/photographs",
            params={"site_id": dig["site"]["id"]},
            headers=auth_headers(client, "dir"),
        ).json()
        assert listing["items"][0]["review_status"] == "pending"

    def test_a_non_image_is_filed_as_a_document(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        created = ask(client, dig["site"]["id"], kind="documents")
        sent = client.post(
            f"/api/v1/data-requests/invite/{token_of(created['invite_url'])}",
            files={
                "file": ("permit.pdf", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n", "application/pdf")
            },
        )
        assert sent.status_code == 201, sent.text

        listing = client.get(
            "/api/v1/documents",
            params={"site_id": dig["site"]["id"]},
            headers=auth_headers(client, "dir"),
        ).json()
        assert listing["total"] == 1

    def test_the_link_closes_itself_when_it_is_full(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        created = ask(client, dig["site"]["id"], max_uploads=2)
        token = token_of(created["invite_url"])

        for index in range(2):
            sent = client.post(
                f"/api/v1/data-requests/invite/{token}",
                files={"file": (f"{index}.png", png((index * 40, 90, 60)), "image/png")},
            )
            assert sent.status_code == 201, sent.text

        third = client.post(
            f"/api/v1/data-requests/invite/{token}",
            files={"file": ("3.png", png((10, 10, 10)), "image/png")},
        )
        assert third.status_code == 404

        state = client.get(
            f"/api/v1/data-requests/{created['id']}", headers=auth_headers(client, "dir")
        ).json()
        assert state["status"] == DataRequestStatus.CLOSED.value
        assert state["upload_count"] == 2

    def test_the_link_grants_no_read_access(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """The one property that makes it safe to put in an e-mail. A token in
        an Authorization header is not a session, and the routes that need one
        still refuse."""
        created = ask(client, dig["site"]["id"])
        token = token_of(created["invite_url"])
        headers = {"Authorization": f"Bearer {token}"}

        for path in ("/api/v1/sites", "/api/v1/photographs", "/api/v1/auth/me"):
            assert client.get(path, headers=headers).status_code == 401, path


# --------------------------------------------------------------------------
# Watching and chasing
# --------------------------------------------------------------------------
class TestWatching:
    def test_outstanding_lists_what_is_still_being_waited_for(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        headers = auth_headers(client, "dir")
        waiting = ask(client, dig["site"]["id"])
        answered = ask(client, dig["site"]["id"], recipient_email="b@example.org")
        client.post(
            f"/api/v1/data-requests/invite/{token_of(answered['invite_url'])}",
            files={"file": ("a.png", png(), "image/png")},
        )

        listing = client.get(
            "/api/v1/data-requests", params={"outstanding": True}, headers=headers
        ).json()
        assert [item["id"] for item in listing["items"]] == [waiting["id"]]

    def test_a_request_is_not_everybody_elses_business(
        self, client: TestClient, director: User, outsider: User, dig: dict
    ) -> None:
        """It names an outside e-mail address and a sentence somebody wrote to
        a colleague."""
        created = ask(client, dig["site"]["id"])

        response = client.get(
            f"/api/v1/data-requests/{created['id']}", headers=auth_headers(client, "other")
        )
        assert response.status_code == 404

    def test_resending_replaces_the_link_rather_than_recovering_it(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        created = ask(client, dig["site"]["id"])
        first = token_of(created["invite_url"])

        again = client.post(
            f"/api/v1/data-requests/{created['id']}/resend", headers=auth_headers(client, "dir")
        )
        assert again.status_code == 200, again.text
        second = token_of(again.json()["invite_url"])

        assert second != first
        assert client.get(f"/api/v1/data-requests/invite/{first}").status_code == 404
        assert client.get(f"/api/v1/data-requests/invite/{second}").status_code == 200

    def test_a_withdrawn_request_is_kept(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """That somebody was asked and the files never came is often exactly
        the thing somebody needs to know later."""
        created = ask(client, dig["site"]["id"])
        headers = auth_headers(client, "dir")

        client.delete(f"/api/v1/data-requests/{created['id']}", headers=headers)

        state = client.get(f"/api/v1/data-requests/{created['id']}", headers=headers).json()
        assert state["status"] == DataRequestStatus.CANCELLED.value
        assert state["record_label"]


# --------------------------------------------------------------------------
# The invitation e-mail
# --------------------------------------------------------------------------
class TestTheEmail:
    def test_it_says_what_the_link_does_and_when_it_stops(
        self, client: TestClient, db: Session, director: User, dig: dict
    ) -> None:
        created = ask(client, dig["site"]["id"])
        record = db.get(DataRequest, created["id"])

        subject, body, html = datarequests.compose(
            record, "TOKEN-HERE", organisation="Department of Antiquities"
        )

        assert "photographs" in subject.lower()
        assert record.record_label in subject
        for text in (body, html):
            assert "TOKEN-HERE" in text
            assert "does not" in text  # "…does not give access to anything else"
            assert record.expires_at.strftime("%d %B %Y") in text

    def test_a_recipients_name_cannot_smuggle_markup_into_the_html(
        self, client: TestClient, db: Session, director: User, dig: dict
    ) -> None:
        created = ask(
            client,
            dig["site"]["id"],
            recipient_name="<script>alert(1)</script>",
            message="<b>bold</b> & sharp",
        )
        record = db.get(DataRequest, created["id"])

        _, _, html = datarequests.compose(record, "T", organisation="Dept")

        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "<b>bold</b>" not in html
        assert "&amp;" in html


class TestUnreadableFiles:
    def test_a_damaged_picture_is_reported_as_a_picture(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """A .png that will not decode is a damaged picture, not a document of
        an unsupported type. Telling somebody that ".png files are not
        accepted" sends them away to convert a file that was never wrong."""
        created = ask(client, dig["site"]["id"])

        sent = client.post(
            f"/api/v1/data-requests/invite/{token_of(created['invite_url'])}",
            files={"file": ("trench.png", b"\x89PNG\r\n\x1a\n truncated", "image/png")},
        )

        assert sent.status_code == 422, sent.text
        detail = sent.json()["detail"]
        assert "looks like a picture" in detail
        assert "not accepted" not in detail
