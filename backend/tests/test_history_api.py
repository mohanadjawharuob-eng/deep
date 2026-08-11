"""Version history, restore, the review workflow and the activity feed."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import ActivityAction, ActivityLog, User
from tests.conftest import auth_headers, make_user


@pytest.fixture
def project(client: TestClient, db: Session, researcher: User) -> dict:
    return client.post(
        "/api/v1/projects",
        json={"name": "History Project", "code": "HIST-1", "is_public": True},
        headers=auth_headers(client, "researcher"),
    ).json()


@pytest.fixture
def site(client: TestClient, db: Session, researcher: User, project: dict) -> dict:
    return client.post(
        "/api/v1/sites",
        json={
            "project_id": project["id"],
            "name": "Original Name",
            "code": "ORIG",
            "latitude": 10.0,
            "longitude": 20.0,
            "notes": "First note",
            "is_public": True,
        },
        headers=auth_headers(client, "researcher"),
    ).json()


@pytest.fixture
def student_member(client: TestClient, db: Session, researcher: User, project: dict) -> User:
    student = make_user(db, email="s@x.org", username="digger")
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"user_id": str(student.id), "role": "student"},
        headers=auth_headers(client, "researcher"),
    )
    return student


class TestRevisions:
    def test_creation_is_version_one(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        history = client.get(f"/api/v1/sites/{site['id']}/revisions").json()
        assert history["total"] == 1
        assert history["items"][0]["version"] == 1
        assert history["items"][0]["change_summary"] == "Created"

    def test_each_update_adds_a_version_of_the_previous_state(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        client.patch(f"/api/v1/sites/{site['id']}", json={"name": "Second"}, headers=headers)
        client.patch(f"/api/v1/sites/{site['id']}", json={"name": "Third"}, headers=headers)

        history = client.get(f"/api/v1/sites/{site['id']}/revisions").json()
        assert [item["version"] for item in history["items"]] == [3, 2, 1]

        # Version 2 holds the state as it was *before* the second edit.
        version_two = client.get(f"/api/v1/sites/{site['id']}/revisions/2").json()
        assert version_two["data"]["name"] == "Original Name"

        version_three = client.get(f"/api/v1/sites/{site['id']}/revisions/3").json()
        assert version_three["data"]["name"] == "Second"

    def test_snapshot_captures_every_column_except_geometry(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        data = client.get(f"/api/v1/sites/{site['id']}/revisions/1").json()["data"]
        assert data["latitude"] == 10.0 and data["longitude"] == 20.0
        assert "geom" not in data, "geometry is derived, not versioned"
        assert data["code"] == "ORIG"

    def test_restore_returns_the_record_to_an_earlier_state(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        client.patch(
            f"/api/v1/sites/{site['id']}",
            json={"name": "Renamed", "notes": "Changed note"},
            headers=headers,
        )

        response = client.post(f"/api/v1/sites/{site['id']}/revisions/1/restore", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body["changed_fields"]) == {"name", "notes"}

        current = client.get(f"/api/v1/sites/{site['id']}").json()
        assert current["name"] == "Original Name"
        assert current["notes"] == "First note"

    def test_restore_is_itself_reversible(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        client.patch(f"/api/v1/sites/{site['id']}", json={"name": "Renamed"}, headers=headers)
        client.post(f"/api/v1/sites/{site['id']}/revisions/1/restore", headers=headers)

        history = client.get(f"/api/v1/sites/{site['id']}/revisions").json()
        restore_entry = history["items"][0]
        assert restore_entry["is_restore"] is True

        # The state discarded by the restore is still there to go back to.
        assert (
            client.get(f"/api/v1/sites/{site['id']}/revisions/{restore_entry['version']}").json()[
                "data"
            ]["name"]
            == "Renamed"
        )

    def test_restoring_coordinates_moves_the_geometry_back(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        client.patch(
            f"/api/v1/sites/{site['id']}",
            json={"latitude": 44.0, "longitude": 55.0},
            headers=headers,
        )
        assert (
            db.scalar(text("SELECT ST_AsText(geom) FROM sites WHERE id = :i"), {"i": site["id"]})
            == "POINT(55 44)"
        )

        client.post(f"/api/v1/sites/{site['id']}/revisions/1/restore", headers=headers)
        assert (
            db.scalar(text("SELECT ST_AsText(geom) FROM sites WHERE id = :i"), {"i": site["id"]})
            == "POINT(20 10)"
        ), "geometry must follow a restored coordinate"

    def test_restoring_an_unchanged_version_says_so(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        response = client.post(
            f"/api/v1/sites/{site['id']}/revisions/1/restore",
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 200
        assert response.json()["changed_fields"] == []
        assert "nothing changed" in response.json()["detail"]

    def test_restore_requires_edit_rights(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        make_user(db, email="reader@x.org", username="reader")
        response = client.post(
            f"/api/v1/sites/{site['id']}/revisions/1/restore",
            headers=auth_headers(client, "reader"),
        )
        assert response.status_code == 403

    def test_missing_version_is_404(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        assert client.get(f"/api/v1/sites/{site['id']}/revisions/99").status_code == 404

    def test_unknown_record_type_is_rejected(self, client: TestClient, site: dict) -> None:
        response = client.get(f"/api/v1/widgets/{site['id']}/revisions")
        assert response.status_code == 404
        assert "Unknown record type" in response.json()["detail"]

    def test_history_of_an_invisible_record_is_hidden(
        self, client: TestClient, db: Session, researcher: User, project: dict
    ) -> None:
        private_site = client.post(
            "/api/v1/sites",
            json={"project_id": project["id"], "name": "Hidden", "code": "HID"},
            headers=auth_headers(client, "researcher"),
        ).json()
        assert client.get(f"/api/v1/sites/{private_site['id']}/revisions").status_code == 404

    def test_deleting_a_record_keeps_its_history(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        from app.models import Revision

        headers = auth_headers(client, "researcher")
        client.delete(f"/api/v1/sites/{site['id']}", headers=headers)

        remaining = db.scalars(select(Revision).where(Revision.resource_id == site["id"])).all()
        assert len(remaining) == 2, "creation plus the final pre-deletion snapshot"
        assert remaining[-1].change_summary == "Deleted"


class TestReviewWorkflow:
    def test_student_record_appears_in_the_pending_queue(
        self, client: TestClient, db: Session, researcher: User, student_member: User, site: dict
    ) -> None:
        client.post(
            "/api/v1/artifacts",
            json={"site_id": site["id"], "inventory_number": "REV-1", "is_public": True},
            headers=auth_headers(client, "digger"),
        )
        pending = client.get("/api/v1/pending", headers=auth_headers(client, "researcher")).json()
        assert [item["label"] for item in pending] == ["REV-1"]

    def test_approval_publishes_the_record_and_notifies_the_author(
        self, client: TestClient, db: Session, researcher: User, student_member: User, site: dict
    ) -> None:
        created = client.post(
            "/api/v1/artifacts",
            json={"site_id": site["id"], "inventory_number": "REV-2", "is_public": True},
            headers=auth_headers(client, "digger"),
        ).json()

        assert client.get("/api/v1/artifacts").json()["total"] == 0

        response = client.post(
            f"/api/v1/artifacts/{created['id']}/approve",
            json={"note": "Looks right"},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 200
        assert client.get("/api/v1/artifacts").json()["total"] == 1

        inbox = client.get("/api/v1/notifications", headers=auth_headers(client, "digger")).json()
        # Membership rather than position: PostgreSQL's now() is the
        # transaction timestamp, so notifications raised in one test share a
        # created_at and their relative order is not defined.
        assert "record_approved" in {item["type"] for item in inbox["items"]}

    def test_rejection_requires_a_note(
        self, client: TestClient, db: Session, researcher: User, student_member: User, site: dict
    ) -> None:
        created = client.post(
            "/api/v1/artifacts",
            json={"site_id": site["id"], "inventory_number": "REV-3"},
            headers=auth_headers(client, "digger"),
        ).json()
        response = client.post(
            f"/api/v1/artifacts/{created['id']}/reject",
            json={},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 422

    def test_rejected_record_can_be_resubmitted(
        self, client: TestClient, db: Session, researcher: User, student_member: User, site: dict
    ) -> None:
        created = client.post(
            "/api/v1/artifacts",
            json={"site_id": site["id"], "inventory_number": "REV-4"},
            headers=auth_headers(client, "digger"),
        ).json()
        client.post(
            f"/api/v1/artifacts/{created['id']}/reject",
            json={"note": "Weight is missing"},
            headers=auth_headers(client, "researcher"),
        )

        resubmit = client.post(
            f"/api/v1/artifacts/{created['id']}/submit", headers=auth_headers(client, "digger")
        )
        assert resubmit.status_code == 200
        assert (
            client.get(
                f"/api/v1/artifacts/{created['id']}", headers=auth_headers(client, "digger")
            ).json()["review_status"]
            == "pending"
        )

    def test_students_cannot_approve_their_own_work(
        self, client: TestClient, db: Session, researcher: User, student_member: User, site: dict
    ) -> None:
        created = client.post(
            "/api/v1/artifacts",
            json={"site_id": site["id"], "inventory_number": "REV-5"},
            headers=auth_headers(client, "digger"),
        ).json()
        response = client.post(
            f"/api/v1/artifacts/{created['id']}/approve",
            json={},
            headers=auth_headers(client, "digger"),
        )
        assert response.status_code == 403

    def test_outside_researcher_cannot_approve(
        self, client: TestClient, db: Session, researcher: User, student_member: User, site: dict
    ) -> None:
        from app.models import UserRole

        make_user(db, email="far@x.org", username="faraway", role=UserRole.RESEARCHER)
        created = client.post(
            "/api/v1/artifacts",
            json={"site_id": site["id"], "inventory_number": "REV-6"},
            headers=auth_headers(client, "digger"),
        ).json()
        response = client.post(
            f"/api/v1/artifacts/{created['id']}/approve",
            json={},
            headers=auth_headers(client, "faraway"),
        )
        # Not visible to them at all, so 404 rather than 403.
        assert response.status_code == 404

    def test_approving_twice_is_a_conflict(
        self, client: TestClient, db: Session, researcher: User, student_member: User, site: dict
    ) -> None:
        created = client.post(
            "/api/v1/artifacts",
            json={"site_id": site["id"], "inventory_number": "REV-7"},
            headers=auth_headers(client, "digger"),
        ).json()
        headers = auth_headers(client, "researcher")
        client.post(f"/api/v1/artifacts/{created['id']}/approve", json={}, headers=headers)
        again = client.post(f"/api/v1/artifacts/{created['id']}/approve", json={}, headers=headers)
        assert again.status_code == 409

    def test_submission_notifies_the_projects_reviewers(
        self, client: TestClient, db: Session, researcher: User, student_member: User, site: dict
    ) -> None:
        created = client.post(
            "/api/v1/artifacts",
            json={"site_id": site["id"], "inventory_number": "REV-8"},
            headers=auth_headers(client, "digger"),
        ).json()
        client.post(
            f"/api/v1/artifacts/{created['id']}/reject",
            json={"note": "Redo"},
            headers=auth_headers(client, "researcher"),
        )
        client.post(
            f"/api/v1/artifacts/{created['id']}/submit", headers=auth_headers(client, "digger")
        )

        inbox = client.get(
            "/api/v1/notifications", headers=auth_headers(client, "researcher")
        ).json()
        assert any(item["type"] == "record_submitted" for item in inbox["items"])


class TestActivityFeed:
    def test_creation_and_update_are_logged(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        client.patch(
            f"/api/v1/sites/{site['id']}",
            json={"name": "Updated"},
            headers=auth_headers(client, "researcher"),
        )
        feed = client.get(
            f"/api/v1/sites/{site['id']}/activity", headers=auth_headers(client, "researcher")
        ).json()
        actions = [item["action"] for item in feed["items"]]
        assert actions == ["update", "create"]
        assert feed["items"][0]["changes"]["name"]["new"] == "Updated"

    def test_feed_is_scoped_to_the_users_projects(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        outsider = make_user(db, email="nosy@x.org", username="nosy")
        feed = client.get("/api/v1/activity", headers=auth_headers(client, "nosy")).json()
        # Their own sign-in is there; the other project's work is not.
        assert all(
            item["user_id"] == str(outsider.id) for item in feed["items"]
        ), "activity in projects you are not on must stay private"

    def test_members_see_their_projects_activity(
        self, client: TestClient, db: Session, researcher: User, student_member: User, site: dict
    ) -> None:
        feed = client.get("/api/v1/activity", headers=auth_headers(client, "digger")).json()
        assert any(item["resource_label"] == "Original Name" for item in feed["items"])

    def test_admin_sees_everything(
        self, client: TestClient, db: Session, admin: User, researcher: User, site: dict
    ) -> None:
        feed = client.get("/api/v1/activity", headers=auth_headers(client, "admin")).json()
        assert feed["total"] >= 3

    def test_filters(
        self, client: TestClient, db: Session, researcher: User, project: dict, site: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        by_project = client.get(
            f"/api/v1/activity?project_id={project['id']}", headers=headers
        ).json()
        assert by_project["total"] >= 2

        by_action = client.get("/api/v1/activity?action=create", headers=headers).json()
        assert all(item["action"] == "create" for item in by_action["items"])

        by_type = client.get("/api/v1/activity?resource_type=site", headers=headers).json()
        assert all(item["resource_type"] == "site" for item in by_type["items"])

    def test_activity_survives_the_records_deletion(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        client.delete(f"/api/v1/sites/{site['id']}", headers=headers)

        entry = db.scalar(
            select(ActivityLog).where(
                ActivityLog.resource_id == site["id"],
                ActivityLog.action == ActivityAction.DELETE,
            )
        )
        assert entry is not None
        assert entry.resource_label == "Original Name", "the label outlives the row"
        assert entry.project_id is not None, "and still points at its project"


class TestRestoreBoundaries:
    """A restore replaces content. It must not replay workflow state."""

    def test_restore_does_not_un_approve_a_record(
        self, client: TestClient, db: Session, researcher: User, student_member: User, site: dict
    ) -> None:
        created = client.post(
            "/api/v1/artifacts",
            json={"site_id": site["id"], "inventory_number": "WF-1", "name": "Lamp"},
            headers=auth_headers(client, "digger"),
        ).json()
        assert created["review_status"] == "pending"

        reviewer = auth_headers(client, "researcher")
        client.post(f"/api/v1/artifacts/{created['id']}/approve", json={}, headers=reviewer)
        client.patch(
            f"/api/v1/artifacts/{created['id']}",
            json={"name": "Renamed lamp"},
            headers=reviewer,
        )

        # Version 1 was captured while the record was still pending.
        client.post(f"/api/v1/artifacts/{created['id']}/revisions/1/restore", headers=reviewer)

        current = client.get(f"/api/v1/artifacts/{created['id']}", headers=reviewer).json()
        assert current["name"] == "Lamp", "content should be rolled back"
        assert current["review_status"] == "approved", (
            "an approval must survive a content restore, or a rollback would "
            "silently pull the record out of public listings"
        )

    def test_restore_keeps_the_qr_token(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        created = client.post(
            "/api/v1/artifacts",
            json={"site_id": site["id"], "inventory_number": "WF-2"},
            headers=headers,
        ).json()
        client.patch(f"/api/v1/artifacts/{created['id']}", json={"name": "Edited"}, headers=headers)
        client.post(f"/api/v1/artifacts/{created['id']}/revisions/1/restore", headers=headers)

        after = client.get(f"/api/v1/artifacts/{created['id']}", headers=headers).json()
        assert after["public_token"] == created["public_token"], "a printed label must keep working"
