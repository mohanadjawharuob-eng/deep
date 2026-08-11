"""The social media repository.

Most of this is ordinary record-keeping. One part is not: the check that says
what a post would give away about where a site is. Publishing a findspot is how
looting starts, and the usual way it happens is invisible — a photograph going
out with the GPS tag the camera wrote into it. Those tests are the ones worth
reading.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Module, ModuleLevel, ResourceType, User, UserRole
from app.models.media import Photograph
from tests.conftest import auth_headers, make_user


@pytest.fixture
def comms(db: Session) -> User:
    """Runs the accounts. Senior in social media, absent elsewhere."""
    return make_user(
        db,
        email="comms@example.org",
        username="comms",
        role=UserRole.VISITOR,
        modules={Module.SOCIAL_MEDIA: ModuleLevel.SUPERVISOR},
        grant_defaults=False,
    )


@pytest.fixture
def drafter(db: Session) -> User:
    """Writes posts. Cannot approve their own."""
    return make_user(
        db,
        email="drafter@example.org",
        username="drafter",
        role=UserRole.VISITOR,
        modules={Module.SOCIAL_MEDIA: ModuleLevel.CONTRIBUTOR},
        grant_defaults=False,
    )


def add_account(client: TestClient, *, who: str = "comms", **fields) -> dict:
    payload = {"platform": "instagram", "handle": "telldemo_dig"} | fields
    response = client.post(
        "/api/v1/social/accounts", json=payload, headers=auth_headers(client, who)
    )
    assert response.status_code == 201, response.text
    return response.json()


def draft(client: TestClient, account_id: str, *, who: str = "comms", **fields) -> dict:
    payload = {"title": "A find from Trench 4"} | fields
    response = client.post(
        f"/api/v1/social/accounts/{account_id}/posts",
        json=payload,
        headers=auth_headers(client, who),
    )
    assert response.status_code == 201, response.text
    return response.json()


def photograph(db: Session, *, gps: bool, filename: str = "trench4.jpg") -> Photograph:
    """A photograph in the archive, with or without the camera's GPS tag."""
    photo = Photograph(
        title=filename.rsplit(".", 1)[0],
        original_filename=filename,
        file_path=f"ab/cd/{filename}",
        checksum=f"deadbeef{filename}",
        mime_type="image/jpeg",
        file_size=1024,
        latitude=32.5341 if gps else None,
        longitude=35.8512 if gps else None,
    )
    db.add(photo)
    db.flush()
    return photo


class TestAccounts:
    def test_the_at_sign_is_not_part_of_the_handle(self, client: TestClient, comms: User) -> None:
        """People paste it in; storing it makes two rows for one account."""
        account = add_account(client, handle="@telldemo_dig")

        assert account["handle"] == "telldemo_dig"

    def test_the_same_handle_twice_on_one_platform_is_refused(
        self, client: TestClient, comms: User
    ) -> None:
        add_account(client, platform="instagram", handle="digteam")

        response = client.post(
            "/api/v1/social/accounts",
            json={"platform": "instagram", "handle": "digteam"},
            headers=auth_headers(client, "comms"),
        )

        assert response.status_code == 409

    def test_the_same_handle_on_two_platforms_is_two_accounts(
        self, client: TestClient, comms: User
    ) -> None:
        add_account(client, platform="instagram", handle="digteam")

        response = client.post(
            "/api/v1/social/accounts",
            json={"platform": "bluesky", "handle": "digteam"},
            headers=auth_headers(client, "comms"),
        )

        assert response.status_code == 201, response.text

    def test_short_form_video_platforms_are_not_on_the_list(
        self, client: TestClient, comms: User
    ) -> None:
        """Deliberately excluded: an institution publishing excavation
        photography needs to know what rights it is granting, and "we are on
        every platform" is not a heritage policy."""
        response = client.post(
            "/api/v1/social/accounts",
            json={"platform": "tiktok", "handle": "digteam"},
            headers=auth_headers(client, "comms"),
        )

        assert response.status_code == 422

    def test_a_channel_with_posts_cannot_be_deleted(self, client: TestClient, comms: User) -> None:
        """An account nobody posts to any more is still where years of
        outreach lives."""
        account = add_account(client)
        draft(client, account["id"])

        response = client.delete(
            f"/api/v1/social/accounts/{account['id']}", headers=auth_headers(client, "comms")
        )

        assert response.status_code == 409
        assert "inactive" in response.json()["detail"]

    def test_an_inactive_channel_takes_no_new_posts(self, client: TestClient, comms: User) -> None:
        account = add_account(client)
        headers = auth_headers(client, "comms")
        client.patch(
            f"/api/v1/social/accounts/{account['id']}", json={"is_active": False}, headers=headers
        )

        response = client.post(
            f"/api/v1/social/accounts/{account['id']}/posts",
            json={"title": "Anything"},
            headers=headers,
        )

        assert response.status_code == 409


class TestLocationDisclosure:
    """The part that makes this archaeological rather than generic.

    Publishing a findspot is how looting starts. It rarely happens by somebody
    typing coordinates — it happens because a phone geotags every frame and
    nobody looked.
    """

    def test_a_photograph_carrying_gps_is_reported(
        self, client: TestClient, db: Session, comms: User
    ) -> None:
        account = add_account(client)
        post = draft(client, account["id"])
        photo = photograph(db, gps=True)
        headers = auth_headers(client, "comms")

        client.post(
            f"/api/v1/social/posts/{post['id']}/assets",
            json={"photograph_id": str(photo.id)},
            headers=headers,
        )
        check = client.get(
            f"/api/v1/social/posts/{post['id']}/location-check", headers=headers
        ).json()

        assert check["clear"] is False
        assert check["findings"][0]["kind"] == "photo_gps"
        assert check["findings"][0]["photograph_id"] == str(photo.id)
        assert "trench4.jpg" in check["findings"][0]["detail"]

    def test_a_photograph_without_gps_is_not(
        self, client: TestClient, db: Session, comms: User
    ) -> None:
        """A false alarm on every post teaches people to ignore the real
        one."""
        account = add_account(client)
        post = draft(client, account["id"])
        photo = photograph(db, gps=False, filename="studio.jpg")
        headers = auth_headers(client, "comms")

        client.post(
            f"/api/v1/social/posts/{post['id']}/assets",
            json={"photograph_id": str(photo.id)},
            headers=headers,
        )
        check = client.get(
            f"/api/v1/social/posts/{post['id']}/location-check", headers=headers
        ).json()

        assert check["clear"] is True

    def test_the_warning_appears_the_moment_the_image_is_attached(
        self, client: TestClient, db: Session, comms: User
    ) -> None:
        """Not only when somebody asks. A warning nobody ran is no warning."""
        account = add_account(client)
        post = draft(client, account["id"])
        photo = photograph(db, gps=True)
        headers = auth_headers(client, "comms")

        client.post(
            f"/api/v1/social/posts/{post['id']}/assets",
            json={"photograph_id": str(photo.id)},
            headers=headers,
        )
        reread = client.get(f"/api/v1/social/posts/{post['id']}", headers=headers).json()

        assert reread["location_warning"] is not None
        assert reread["location_check"]["clear"] is False

    def test_taking_the_image_off_clears_it(
        self, client: TestClient, db: Session, comms: User
    ) -> None:
        """A warning that outlives its cause is one people learn to dismiss."""
        account = add_account(client)
        post = draft(client, account["id"])
        photo = photograph(db, gps=True)
        headers = auth_headers(client, "comms")
        asset = client.post(
            f"/api/v1/social/posts/{post['id']}/assets",
            json={"photograph_id": str(photo.id)},
            headers=headers,
        ).json()

        client.delete(f"/api/v1/social/posts/{post['id']}/assets/{asset['id']}", headers=headers)

        reread = client.get(f"/api/v1/social/posts/{post['id']}", headers=headers).json()
        assert reread["location_warning"] is None

    def test_the_image_strip_says_which_one_carries_it(
        self, client: TestClient, db: Session, comms: User
    ) -> None:
        """Nine images and one warning is not actionable without this."""
        account = add_account(client)
        post = draft(client, account["id"])
        clean = photograph(db, gps=False, filename="a.jpg")
        tagged = photograph(db, gps=True, filename="b.jpg")
        headers = auth_headers(client, "comms")

        for photo in (clean, tagged):
            client.post(
                f"/api/v1/social/posts/{post['id']}/assets",
                json={"photograph_id": str(photo.id)},
                headers=headers,
            )

        assets = client.get(f"/api/v1/social/posts/{post['id']}", headers=headers).json()["assets"]
        by_name = {asset["filename"]: asset["has_gps"] for asset in assets}

        assert by_name == {"a.jpg": False, "b.jpg": True}

    def test_it_never_blocks_the_post(self, client: TestClient, db: Session, comms: User) -> None:
        """Sometimes revealing a location is exactly right — a site that is
        already a visitor attraction, a museum's own address. A platform that
        refuses is one people work around, which loses the warning for the
        cases that matter."""
        account = add_account(client)
        post = draft(client, account["id"])
        photo = photograph(db, gps=True)
        headers = auth_headers(client, "comms")
        client.post(
            f"/api/v1/social/posts/{post['id']}/assets",
            json={"photograph_id": str(photo.id)},
            headers=headers,
        )

        approved = client.post(
            f"/api/v1/social/posts/{post['id']}/approve", json={}, headers=headers
        )
        published = client.post(
            f"/api/v1/social/posts/{post['id']}/publish",
            json={"external_url": "https://example.org/p/1"},
            headers=headers,
        )

        assert approved.status_code == 200, approved.text
        assert published.status_code == 200, published.text

    def test_a_declared_disclosure_is_reported_too(self, client: TestClient, comms: User) -> None:
        """Somebody who recognised a landmark in the background knows
        something no automatic check will find."""
        account = add_account(client)
        post = draft(client, account["id"], reveals_location=True)

        check = client.get(
            f"/api/v1/social/posts/{post['id']}/location-check",
            headers=auth_headers(client, "comms"),
        ).json()

        assert check["clear"] is False
        assert check["findings"][0]["kind"] == "declared"

    def test_the_summary_counts_posts_worth_looking_at(
        self, client: TestClient, db: Session, comms: User
    ) -> None:
        account = add_account(client)
        post = draft(client, account["id"])
        photo = photograph(db, gps=True)
        headers = auth_headers(client, "comms")
        client.post(
            f"/api/v1/social/posts/{post['id']}/assets",
            json={"photograph_id": str(photo.id)},
            headers=headers,
        )

        summary = client.get("/api/v1/social/summary", headers=headers).json()

        assert summary["with_location_warnings"] == 1


class TestApproval:
    def test_approval_records_who_said_yes(self, client: TestClient, comms: User) -> None:
        """Outreach about an unpublished excavation has consequences. Somebody
        has to own the decision."""
        account = add_account(client)
        post = draft(client, account["id"])

        approved = client.post(
            f"/api/v1/social/posts/{post['id']}/approve",
            json={"note": "Checked with the permit office"},
            headers=auth_headers(client, "comms"),
        ).json()

        assert approved["status"] == "approved"
        assert approved["approved_by_id"] == str(comms.id)
        assert approved["approved_at"] is not None
        assert approved["approval_note"] == "Checked with the permit office"

    def test_it_cannot_be_set_on_the_form(self, client: TestClient, comms: User) -> None:
        """A status somebody can type is a status with nobody behind it."""
        account = add_account(client)
        post = draft(client, account["id"])

        response = client.patch(
            f"/api/v1/social/posts/{post['id']}",
            json={"status": "approved"},
            headers=auth_headers(client, "comms"),
        )

        assert response.status_code == 422

    def test_a_contributor_cannot_approve(
        self, client: TestClient, comms: User, drafter: User
    ) -> None:
        account = add_account(client)
        post = draft(client, account["id"])

        response = client.post(
            f"/api/v1/social/posts/{post['id']}/approve",
            json={},
            headers=auth_headers(client, "drafter"),
        )

        assert response.status_code == 403

    def test_editing_an_approved_post_withdraws_the_approval(
        self, client: TestClient, comms: User
    ) -> None:
        """Approval is of a particular text. Letting it be rewritten
        afterwards makes the approval meaningless, and does so silently."""
        account = add_account(client)
        post = draft(client, account["id"])
        headers = auth_headers(client, "comms")
        client.post(f"/api/v1/social/posts/{post['id']}/approve", json={}, headers=headers)

        edited = client.patch(
            f"/api/v1/social/posts/{post['id']}",
            json={"body": "Actually, here is where we found it."},
            headers=headers,
        ).json()

        assert edited["status"] == "needs_approval"
        assert edited["approved_by_id"] is None
        assert "edited after approval" in edited["approval_note"]

    def test_a_harmless_edit_does_not(self, client: TestClient, comms: User) -> None:
        """Rescheduling an approved post is not rewriting it, and forcing
        re-approval for it teaches people that approval is noise."""
        account = add_account(client)
        post = draft(client, account["id"])
        headers = auth_headers(client, "comms")
        client.post(f"/api/v1/social/posts/{post['id']}/approve", json={}, headers=headers)

        edited = client.patch(
            f"/api/v1/social/posts/{post['id']}",
            json={"scheduled_for": (datetime.now(UTC) + timedelta(days=2)).isoformat()},
            headers=headers,
        ).json()

        assert edited["status"] == "approved"


class TestPublishing:
    def test_publishing_records_where_it_went(self, client: TestClient, comms: User) -> None:
        account = add_account(client)
        post = draft(client, account["id"])

        published = client.post(
            f"/api/v1/social/posts/{post['id']}/publish",
            json={"external_url": "https://example.org/p/abc", "external_id": "abc"},
            headers=auth_headers(client, "comms"),
        ).json()

        assert published["status"] == "published"
        assert published["published_at"] is not None
        assert published["external_url"] == "https://example.org/p/abc"

    def test_it_cannot_be_set_on_the_form_either(self, client: TestClient, comms: User) -> None:
        account = add_account(client)
        post = draft(client, account["id"])

        response = client.patch(
            f"/api/v1/social/posts/{post['id']}",
            json={"status": "published"},
            headers=auth_headers(client, "comms"),
        )

        assert response.status_code == 422

    def test_a_published_post_cannot_be_deleted(self, client: TestClient, comms: User) -> None:
        """ "Why was that taken down" is a question that gets asked, and a
        deleted row cannot answer it."""
        account = add_account(client)
        post = draft(client, account["id"])
        headers = auth_headers(client, "comms")
        client.post(f"/api/v1/social/posts/{post['id']}/publish", json={}, headers=headers)

        response = client.delete(f"/api/v1/social/posts/{post['id']}", headers=headers)

        assert response.status_code == 409
        assert "Withdraw it instead" in response.json()["detail"]

    def test_a_withdrawn_post_is_not_revived(self, client: TestClient, comms: User) -> None:
        account = add_account(client)
        post = draft(client, account["id"])
        headers = auth_headers(client, "comms")
        client.patch(
            f"/api/v1/social/posts/{post['id']}", json={"status": "withdrawn"}, headers=headers
        )

        response = client.post(
            f"/api/v1/social/posts/{post['id']}/publish", json={}, headers=headers
        )

        assert response.status_code == 409


class TestCoverage:
    def test_a_record_can_be_asked_what_has_been_said_about_it(
        self, client: TestClient, comms: User
    ) -> None:
        """The question asked before every press enquiry."""
        import uuid as _uuid

        account = add_account(client)
        subject = _uuid.uuid4()
        headers = auth_headers(client, "comms")
        post = draft(
            client,
            account["id"],
            title="The bronze fibula",
            resource_type="artifact",
            resource_id=str(subject),
        )
        client.post(
            f"/api/v1/social/posts/{post['id']}/publish",
            json={"external_url": "https://example.org/p/2"},
            headers=headers,
        )

        found = client.get(
            "/api/v1/social/coverage",
            params={"resource_type": "artifact", "resource_id": str(subject)},
            headers=headers,
        ).json()

        assert len(found) == 1
        assert found[0]["title"] == "The bronze fibula"
        assert found[0]["platform"] == "instagram"

    def test_half_a_subject_is_refused(self, client: TestClient, comms: User) -> None:
        """A type with no id points at nothing; an id with no type cannot be
        looked up."""
        account = add_account(client)

        response = client.post(
            f"/api/v1/social/accounts/{account['id']}/posts",
            json={"title": "Dangling", "resource_type": "artifact"},
            headers=auth_headers(client, "comms"),
        )

        assert response.status_code == 422


class TestEngagement:
    def test_a_reading_with_no_numbers_records_nothing(
        self, client: TestClient, comms: User
    ) -> None:
        account = add_account(client)
        post = draft(client, account["id"])

        response = client.post(
            f"/api/v1/social/posts/{post['id']}/metrics",
            json={"source": "the dashboard"},
            headers=auth_headers(client, "comms"),
        )

        assert response.status_code == 422

    def test_two_readings_for_one_moment_are_refused(self, client: TestClient, comms: User) -> None:
        """A double entry makes every chart wrong in a way that looks like
        real growth."""
        account = add_account(client)
        post = draft(client, account["id"])
        headers = auth_headers(client, "comms")
        when = datetime.now(UTC).isoformat()
        client.post(
            f"/api/v1/social/posts/{post['id']}/metrics",
            json={"recorded_at": when, "likes": 10},
            headers=headers,
        )

        again = client.post(
            f"/api/v1/social/posts/{post['id']}/metrics",
            json={"recorded_at": when, "likes": 12},
            headers=headers,
        )

        assert again.status_code == 409

    def test_the_change_since_the_last_reading_is_reported(
        self, client: TestClient, comms: User
    ) -> None:
        """A single number cannot say whether a post kept growing or stopped
        after a day, which is the only question anybody has."""
        account = add_account(client)
        post = draft(client, account["id"])
        headers = auth_headers(client, "comms")
        first = datetime.now(UTC) - timedelta(days=2)
        client.post(
            f"/api/v1/social/posts/{post['id']}/metrics",
            json={"recorded_at": first.isoformat(), "likes": 40, "comments": 5},
            headers=headers,
        )
        client.post(
            f"/api/v1/social/posts/{post['id']}/metrics",
            json={"recorded_at": datetime.now(UTC).isoformat(), "likes": 90, "comments": 12},
            headers=headers,
        )

        detail = client.get(f"/api/v1/social/posts/{post['id']}", headers=headers).json()

        assert detail["engagement"]["interactions"] == 102
        assert detail["engagement"]["change"] == 57
        assert detail["engagement"]["readings"] == 2

    def test_a_figure_the_platform_does_not_report_stays_missing(
        self, client: TestClient, comms: User
    ) -> None:
        """A zero meaning "this platform does not tell us" is a zero that
        ruins an average."""
        account = add_account(client)
        post = draft(client, account["id"])
        headers = auth_headers(client, "comms")

        client.post(
            f"/api/v1/social/posts/{post['id']}/metrics",
            json={"likes": 40},
            headers=headers,
        )

        detail = client.get(f"/api/v1/social/posts/{post['id']}", headers=headers).json()
        assert detail["engagement"]["impressions"] is None
        assert detail["engagement"]["interactions"] == 40


class TestVisibility:
    def test_the_repository_is_closed_to_people_outside_it(
        self, client: TestClient, comms: User, db: Session
    ) -> None:
        make_user(
            db,
            email="nobody@example.org",
            username="nobody",
            role=UserRole.VISITOR,
            grant_defaults=False,
        )
        add_account(client)

        response = client.get("/api/v1/social/accounts", headers=auth_headers(client, "nobody"))

        assert response.json()["total"] == 0

    def test_the_subject_is_resolved_to_something_readable(
        self, client: TestClient, db: Session, comms: User
    ) -> None:
        """A card showing a UUID has told the reader nothing."""
        account = add_account(client)
        photo = photograph(db, gps=False, filename="the-pot.jpg")
        post = draft(
            client,
            account["id"],
            resource_type="photograph",
            resource_id=str(photo.id),
        )

        detail = client.get(
            f"/api/v1/social/posts/{post['id']}", headers=auth_headers(client, "comms")
        ).json()

        assert detail["subject_label"] is not None

    def test_a_subject_that_has_since_been_deleted_reads_as_missing(
        self, client: TestClient, comms: User
    ) -> None:
        """A reference to something gone is a fact worth seeing, not hiding."""
        import uuid as _uuid

        account = add_account(client)
        post = draft(
            client,
            account["id"],
            resource_type=ResourceType.ARTIFACT.value,
            resource_id=str(_uuid.uuid4()),
        )

        detail = client.get(
            f"/api/v1/social/posts/{post['id']}", headers=auth_headers(client, "comms")
        ).json()

        assert detail["subject_label"] is None


class TestReview:
    """Getting a post right, which is mostly not a yes or a no.

    Approval is one bit. "The find number is wrong", "wait until the permit is
    signed", "lovely, but crop the trowel out" are the substance of a real
    review, and with nowhere to put them they get said in a corridor and lost.
    """

    def test_anybody_who_can_see_the_module_can_leave_a_note(
        self, client: TestClient, comms: User, drafter: User
    ) -> None:
        account = add_account(client)
        post = draft(client, account["id"])

        response = client.post(
            f"/api/v1/social/posts/{post['id']}/notes",
            json={"body": "The find number is TD-114, not TD-141."},
            headers=auth_headers(client, "drafter"),
        )
        assert response.status_code == 201, response.text
        assert response.json()["author_label"] == "Drafter"
        assert response.json()["decision"] is None

    def test_the_thread_comes_back_with_the_post(
        self, client: TestClient, comms: User, drafter: User
    ) -> None:
        account = add_account(client)
        post = draft(client, account["id"])
        for who, text in (("drafter", "Number is wrong"), ("comms", "Fixed, thanks")):
            client.post(
                f"/api/v1/social/posts/{post['id']}/notes",
                json={"body": text},
                headers=auth_headers(client, who),
            )

        detail = client.get(
            f"/api/v1/social/posts/{post['id']}", headers=auth_headers(client, "comms")
        ).json()
        assert [note["body"] for note in detail["notes_thread"]] == [
            "Number is wrong",
            "Fixed, thanks",
        ]

    def test_sending_back_returns_it_to_draft_with_the_reason(
        self, client: TestClient, comms: User
    ) -> None:
        account = add_account(client)
        post = draft(client, account["id"])
        client.post(
            f"/api/v1/social/posts/{post['id']}/approve",
            json={},
            headers=auth_headers(client, "comms"),
        )

        sent_back = client.post(
            f"/api/v1/social/posts/{post['id']}/send-back",
            json={"note": "Wait until the permit is signed."},
            headers=auth_headers(client, "comms"),
        )
        assert sent_back.status_code == 200, sent_back.text
        body = sent_back.json()
        assert body["status"] == "draft"
        assert body["approved_by_id"] is None
        assert body["notes_thread"][-1]["decision"] == "sent_back"

    def test_a_reason_is_required_to_send_one_back(
        self, client: TestClient, comms: User
    ) -> None:
        # "Not yet" with nothing attached is a dead end for whoever wrote it.
        account = add_account(client)
        post = draft(client, account["id"])
        response = client.post(
            f"/api/v1/social/posts/{post['id']}/send-back",
            json={"note": ""},
            headers=auth_headers(client, "comms"),
        )
        assert response.status_code == 422

    def test_a_published_post_is_withdrawn_not_sent_back(
        self, client: TestClient, comms: User
    ) -> None:
        account = add_account(client)
        post = draft(client, account["id"])
        client.post(
            f"/api/v1/social/posts/{post['id']}/approve",
            json={},
            headers=auth_headers(client, "comms"),
        )
        client.post(
            f"/api/v1/social/posts/{post['id']}/publish",
            json={"external_url": "https://example.org/p/1"},
            headers=auth_headers(client, "comms"),
        )

        response = client.post(
            f"/api/v1/social/posts/{post['id']}/send-back",
            json={"note": "Too late"},
            headers=auth_headers(client, "comms"),
        )
        assert response.status_code == 409

    def test_approving_with_a_note_puts_it_in_the_thread(
        self, client: TestClient, comms: User
    ) -> None:
        account = add_account(client)
        post = draft(client, account["id"])
        approved = client.post(
            f"/api/v1/social/posts/{post['id']}/approve",
            json={"note": "Checked with the permit office"},
            headers=auth_headers(client, "comms"),
        ).json()

        assert approved["notes_thread"][-1]["decision"] == "approved"
        assert approved["notes_thread"][-1]["body"] == "Checked with the permit office"


class TestTellingThePublisher:
    """An approval that nobody is told about is an approval that does nothing.

    The platform publishes nothing itself, on purpose - it holds no API keys.
    So the approval has to reach a person, or the post sits in a database
    exactly as it used to sit in a drawer.
    """

    def test_approving_mails_whoever_will_put_it_up(
        self, client: TestClient, db: Session, comms: User, monkeypatch
    ) -> None:
        from app.services import mail

        editor = make_user(
            db,
            email="poster@example.org",
            username="poster",
            role=UserRole.VISITOR,
            modules={Module.SOCIAL_MEDIA: ModuleLevel.EDITOR},
            grant_defaults=False,
        )
        sent: list[tuple] = []
        monkeypatch.setattr(
            mail, "send", lambda to, subject, body, **rest: sent.append((to, subject, body))
        )

        account = add_account(client)
        post = draft(client, account["id"], title="A jar from Trench 4")
        client.post(
            f"/api/v1/social/posts/{post['id']}/approve",
            json={},
            headers=auth_headers(client, "comms"),
        )

        assert len(sent) == 1
        recipients, subject, body = sent[0]
        assert recipients == [editor.email]
        assert "A jar from Trench 4" in subject
        assert "does not post anything itself" in body

    def test_the_approver_is_not_told_what_they_just_did(
        self, client: TestClient, db: Session, comms: User, monkeypatch
    ) -> None:
        from app.services import mail

        sent: list[tuple] = []
        monkeypatch.setattr(
            mail, "send", lambda to, subject, body, **rest: sent.append((to, subject, body))
        )

        account = add_account(client)
        post = draft(client, account["id"])
        client.post(
            f"/api/v1/social/posts/{post['id']}/approve",
            json={},
            headers=auth_headers(client, "comms"),
        )

        # comms is a supervisor, so they would otherwise qualify.
        assert sent == []


class TestComposers:
    """Each channel wants a post written its own way, and says so."""

    def test_instagram_needs_a_picture_and_has_no_link(self, client: TestClient) -> None:
        composers = client.get("/api/v1/social/composers").json()
        instagram = next(item for item in composers if item["platform"] == "instagram")

        assert instagram["needs_image"] is True
        assert instagram["allows_link"] is False
        assert instagram["text_label"] == "Caption"
        assert instagram["text_limit"] == 2200

    def test_facebook_takes_a_link_and_needs_no_picture(self, client: TestClient) -> None:
        composers = client.get("/api/v1/social/composers").json()
        facebook = next(item for item in composers if item["platform"] == "facebook")

        assert facebook["needs_image"] is False
        assert facebook["allows_link"] is True
