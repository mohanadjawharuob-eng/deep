"""End-to-end tests for project, site, artifact and context CRUD."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import (
    Project,
    ProjectMembership,
    ProjectRole,
    ReviewStatus,
    Site,
    User,
    UserRole,
)
from tests.conftest import auth_headers, make_user

PROJECT_PAYLOAD = {
    "name": "Tell Test Excavation",
    "code": "tt-2024",
    "description": "A test excavation",
    "country": "Jordan",
    "region": "Irbid",
    "latitude": 32.5556,
    "longitude": 35.85,
    "is_public": True,
}


@pytest.fixture
def project(client: TestClient, db: Session, researcher: User) -> dict:
    response = client.post(
        "/api/v1/projects", json=PROJECT_PAYLOAD, headers=auth_headers(client, "researcher")
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def site(client: TestClient, db: Session, researcher: User, project: dict) -> dict:
    response = client.post(
        "/api/v1/sites",
        json={
            "project_id": project["id"],
            "name": "Tell Test",
            "code": "TT",
            "latitude": 32.5556,
            "longitude": 35.85,
            "date_from": -2900,
            "date_to": -2600,
            "is_public": True,
        },
        headers=auth_headers(client, "researcher"),
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestProjectCrud:
    def test_create_normalises_code_and_makes_creator_director(
        self, client: TestClient, db: Session, researcher: User, project: dict
    ) -> None:
        assert project["code"] == "TT-2024", "codes are upper-cased"
        assert project["slug"] == "tell-test-excavation"
        assert project["owner_id"] == str(researcher.id)

        membership = db.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project["id"],
                ProjectMembership.user_id == researcher.id,
            )
        )
        assert membership is not None and membership.role is ProjectRole.DIRECTOR

    def test_students_cannot_create_projects(
        self, client: TestClient, db: Session, student: User
    ) -> None:
        response = client.post(
            "/api/v1/projects", json=PROJECT_PAYLOAD, headers=auth_headers(client, "student")
        )
        assert response.status_code == 403

    def test_anonymous_cannot_create_projects(self, client: TestClient) -> None:
        assert client.post("/api/v1/projects", json=PROJECT_PAYLOAD).status_code == 401

    def test_duplicate_code_is_rejected(
        self, client: TestClient, db: Session, researcher: User, project: dict
    ) -> None:
        response = client.post(
            "/api/v1/projects",
            json={**PROJECT_PAYLOAD, "name": "Another"},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 409

    def test_invalid_code_is_rejected(
        self, client: TestClient, db: Session, researcher: User
    ) -> None:
        response = client.post(
            "/api/v1/projects",
            json={**PROJECT_PAYLOAD, "code": "has spaces!"},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 422

    def test_end_date_before_start_is_rejected(
        self, client: TestClient, db: Session, researcher: User
    ) -> None:
        response = client.post(
            "/api/v1/projects",
            json={
                **PROJECT_PAYLOAD,
                "code": "DATE-1",
                "start_date": "2024-06-01",
                "end_date": "2024-01-01",
            },
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 422

    def test_slug_collisions_get_a_counter(
        self, client: TestClient, db: Session, researcher: User, project: dict
    ) -> None:
        response = client.post(
            "/api/v1/projects",
            json={**PROJECT_PAYLOAD, "code": "TT-2025"},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 201
        assert response.json()["slug"] == "tell-test-excavation-2"

    def test_anonymous_sees_public_projects_only(
        self, client: TestClient, db: Session, researcher: User, project: dict
    ) -> None:
        client.post(
            "/api/v1/projects",
            json={**PROJECT_PAYLOAD, "code": "PRIV-1", "name": "Secret dig", "is_public": False},
            headers=auth_headers(client, "researcher"),
        )
        listing = client.get("/api/v1/projects").json()
        assert [item["code"] for item in listing["items"]] == ["TT-2024"]
        assert listing["total"] == 1

    def test_private_project_is_404_for_outsiders(
        self, client: TestClient, db: Session, researcher: User
    ) -> None:
        created = client.post(
            "/api/v1/projects",
            json={**PROJECT_PAYLOAD, "code": "PRIV-2", "is_public": False},
            headers=auth_headers(client, "researcher"),
        ).json()
        make_user(db, email="nobody@x.org", username="nobody")
        response = client.get(
            f"/api/v1/projects/{created['id']}", headers=auth_headers(client, "nobody")
        )
        assert response.status_code == 404, "existence must not be disclosed"

    def test_update_records_a_revision(
        self, client: TestClient, db: Session, researcher: User, project: dict
    ) -> None:
        response = client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"description": "Revised description", "status": "active"},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 200
        assert response.json()["status"] == "active"

        history = client.get(
            f"/api/v1/projects/{project['id']}/revisions",
            headers=auth_headers(client, "researcher"),
        ).json()
        assert history["total"] == 2, "creation plus the update"
        assert history["items"][0]["changed_fields"] == ["description", "status"]

    def test_renaming_updates_the_slug(
        self, client: TestClient, db: Session, researcher: User, project: dict
    ) -> None:
        response = client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"name": "Renamed Excavation"},
            headers=auth_headers(client, "researcher"),
        )
        assert response.json()["slug"] == "renamed-excavation"

    def test_unchanged_update_writes_no_revision(
        self, client: TestClient, db: Session, researcher: User, project: dict
    ) -> None:
        client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"name": project["name"]},
            headers=auth_headers(client, "researcher"),
        )
        history = client.get(
            f"/api/v1/projects/{project['id']}/revisions",
            headers=auth_headers(client, "researcher"),
        ).json()
        assert history["total"] == 1, "re-posting the same value is not a change"

    def test_outsider_cannot_edit(
        self, client: TestClient, db: Session, researcher: User, project: dict
    ) -> None:
        make_user(db, email="out@x.org", username="outsider")
        response = client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"name": "Hijacked"},
            headers=auth_headers(client, "outsider"),
        )
        assert response.status_code == 403

    def test_director_can_delete(
        self, client: TestClient, db: Session, researcher: User, project: dict
    ) -> None:
        response = client.delete(
            f"/api/v1/projects/{project['id']}", headers=auth_headers(client, "researcher")
        )
        assert response.status_code == 200
        assert db.get(Project, project["id"]) is None

    def test_non_director_researcher_cannot_delete(
        self, client: TestClient, db: Session, researcher: User, project: dict
    ) -> None:
        colleague = make_user(db, email="col@x.org", username="colleague", role=UserRole.RESEARCHER)
        client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": str(colleague.id), "role": "researcher"},
            headers=auth_headers(client, "researcher"),
        )
        response = client.delete(
            f"/api/v1/projects/{project['id']}", headers=auth_headers(client, "colleague")
        )
        assert response.status_code == 403


class TestMembership:
    def test_add_and_list_members(
        self, client: TestClient, db: Session, researcher: User, student: User, project: dict
    ) -> None:
        response = client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": str(student.id), "role": "student", "title": "Trench supervisor"},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 201
        assert response.json()["user"]["username"] == "student"

        members = client.get(
            f"/api/v1/projects/{project['id']}/members",
            headers=auth_headers(client, "researcher"),
        ).json()
        assert len(members) == 2

    def test_adding_a_member_notifies_them(
        self, client: TestClient, db: Session, researcher: User, student: User, project: dict
    ) -> None:
        client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": str(student.id), "role": "student"},
            headers=auth_headers(client, "researcher"),
        )
        inbox = client.get("/api/v1/notifications", headers=auth_headers(client, "student")).json()
        assert inbox["total"] == 1
        assert inbox["items"][0]["type"] == "project_invitation"

    def test_duplicate_membership_is_rejected(
        self, client: TestClient, db: Session, researcher: User, student: User, project: dict
    ) -> None:
        payload = {"user_id": str(student.id), "role": "student"}
        headers = auth_headers(client, "researcher")
        client.post(f"/api/v1/projects/{project['id']}/members", json=payload, headers=headers)
        second = client.post(
            f"/api/v1/projects/{project['id']}/members", json=payload, headers=headers
        )
        assert second.status_code == 409

    def test_cannot_remove_the_last_director(
        self, client: TestClient, db: Session, researcher: User, project: dict
    ) -> None:
        response = client.delete(
            f"/api/v1/projects/{project['id']}/members/{researcher.id}",
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 400
        assert "at least one director" in response.json()["detail"]

    def test_member_can_remove_themselves(
        self, client: TestClient, db: Session, researcher: User, student: User, project: dict
    ) -> None:
        client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": str(student.id), "role": "student"},
            headers=auth_headers(client, "researcher"),
        )
        response = client.delete(
            f"/api/v1/projects/{project['id']}/members/{student.id}",
            headers=auth_headers(client, "student"),
        )
        assert response.status_code == 200

    def test_student_cannot_manage_the_team(
        self, client: TestClient, db: Session, researcher: User, student: User, project: dict
    ) -> None:
        client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": str(student.id), "role": "student"},
            headers=auth_headers(client, "researcher"),
        )
        intruder = make_user(db, email="i@x.org", username="intruder")
        response = client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": str(intruder.id), "role": "researcher"},
            headers=auth_headers(client, "student"),
        )
        assert response.status_code == 403


class TestSiteCrud:
    def test_create_syncs_the_postgis_geometry(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        wkt = db.scalar(text("SELECT ST_AsText(geom) FROM sites WHERE id = :i"), {"i": site["id"]})
        assert wkt == "POINT(35.85 32.5556)", "geom must follow the decimal columns"

    def test_moving_a_site_moves_its_geometry(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        client.patch(
            f"/api/v1/sites/{site['id']}",
            json={"latitude": 31.0, "longitude": 36.0},
            headers=auth_headers(client, "researcher"),
        )
        wkt = db.scalar(text("SELECT ST_AsText(geom) FROM sites WHERE id = :i"), {"i": site["id"]})
        assert wkt == "POINT(36 31)"

    def test_half_a_coordinate_is_rejected(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        response = client.patch(
            f"/api/v1/sites/{site['id']}",
            json={"latitude": None},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 422
        assert "together" in response.json()["detail"]

    def test_out_of_range_coordinates_are_rejected(
        self, client: TestClient, db: Session, researcher: User, project: dict
    ) -> None:
        response = client.post(
            "/api/v1/sites",
            json={
                "project_id": project["id"],
                "name": "Impossible",
                "code": "IMP",
                "latitude": 95.0,
                "longitude": 0.0,
            },
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 422

    def test_site_codes_are_unique_per_project_not_globally(
        self, client: TestClient, db: Session, researcher: User, project: dict, site: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        duplicate = client.post(
            "/api/v1/sites",
            json={"project_id": project["id"], "name": "Other", "code": "TT"},
            headers=headers,
        )
        assert duplicate.status_code == 409

        other_project = client.post(
            "/api/v1/projects", json={**PROJECT_PAYLOAD, "code": "OTHER-1"}, headers=headers
        ).json()
        reused = client.post(
            "/api/v1/sites",
            json={"project_id": other_project["id"], "name": "Elsewhere", "code": "TT"},
            headers=headers,
        )
        assert reused.status_code == 201, "the same code in another project is fine"

    def test_non_member_cannot_add_a_site(
        self, client: TestClient, db: Session, researcher: User, project: dict
    ) -> None:
        make_user(db, email="stranger@x.org", username="stranger")
        response = client.post(
            "/api/v1/sites",
            json={"project_id": project["id"], "name": "Sneaky", "code": "SNK"},
            headers=auth_headers(client, "stranger"),
        )
        assert response.status_code == 403

    def test_bbox_filter(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        inside = client.get("/api/v1/sites?bbox=35.0,32.0,36.0,33.0").json()
        assert inside["total"] == 1
        outside = client.get("/api/v1/sites?bbox=0.0,0.0,1.0,1.0").json()
        assert outside["total"] == 0

    def test_malformed_bbox_is_rejected(self, client: TestClient) -> None:
        assert client.get("/api/v1/sites?bbox=nonsense").status_code == 422
        assert client.get("/api/v1/sites?bbox=10,10,5,5").status_code == 422

    def test_date_filter_matches_overlapping_ranges(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        # The site spans 2900–2600 BCE; a query inside that window must hit.
        assert client.get("/api/v1/sites?date_from=-2800&date_to=-2700").json()["total"] == 1
        assert client.get("/api/v1/sites?date_from=-1000&date_to=-500").json()["total"] == 0

    def test_restricted_location_is_blurred_for_outsiders(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        client.patch(
            f"/api/v1/sites/{site['id']}",
            json={"location_restricted": True},
            headers=auth_headers(client, "researcher"),
        )
        public_view = client.get(f"/api/v1/sites/{site['id']}").json()
        assert public_view["latitude"] == 32.56, "coordinate must be rounded for outsiders"

        team_view = client.get(
            f"/api/v1/sites/{site['id']}", headers=auth_headers(client, "researcher")
        ).json()
        assert team_view["latitude"] == 32.5556, "the team keeps the surveyed position"

    def test_search_matches_alternative_names(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        client.patch(
            f"/api/v1/sites/{site['id']}",
            json={"alternative_names": ["Khirbet Tayyib"]},
            headers=auth_headers(client, "researcher"),
        )
        assert client.get("/api/v1/sites?q=khirbet").json()["total"] == 1


class TestArtifactCrud:
    def test_create_and_read(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        response = client.post(
            "/api/v1/artifacts",
            json={
                "site_id": site["id"],
                "inventory_number": "TT-2024-0001",
                "name": "Cooking pot rim",
                "object_type": "Cooking pot",
                "weight_g": 212.4,
                "rim_diameter_mm": 224,
                "is_public": True,
            },
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["public_token"], "a QR token is minted on creation"
        assert body["weight_g"] == 212.4

    def test_qr_token_route_resolves(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        created = client.post(
            "/api/v1/artifacts",
            json={
                "site_id": site["id"],
                "inventory_number": "TT-2024-0002",
                "is_public": True,
            },
            headers=auth_headers(client, "researcher"),
        ).json()
        scanned = client.get(f"/api/v1/artifacts/by-token/{created['public_token']}")
        assert scanned.status_code == 200
        assert scanned.json()["id"] == created["id"]

    def test_qr_token_respects_permissions(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        created = client.post(
            "/api/v1/artifacts",
            json={
                "site_id": site["id"],
                "inventory_number": "TT-2024-0003",
                "is_public": False,
            },
            headers=auth_headers(client, "researcher"),
        ).json()
        assert (
            client.get(f"/api/v1/artifacts/by-token/{created['public_token']}").status_code == 404
        )

    def test_inventory_number_unique_per_site(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        payload = {"site_id": site["id"], "inventory_number": "DUP-1"}
        assert client.post("/api/v1/artifacts", json=payload, headers=headers).status_code == 201
        assert client.post("/api/v1/artifacts", json=payload, headers=headers).status_code == 409

    def test_context_from_another_site_is_rejected(
        self, client: TestClient, db: Session, researcher: User, project: dict, site: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        other_site = client.post(
            "/api/v1/sites",
            json={"project_id": project["id"], "name": "Second", "code": "S2"},
            headers=headers,
        ).json()
        foreign_context = client.post(
            "/api/v1/contexts",
            json={"site_id": other_site["id"], "context_number": "9001"},
            headers=headers,
        ).json()

        response = client.post(
            "/api/v1/artifacts",
            json={
                "site_id": site["id"],
                "inventory_number": "X-1",
                "context_id": foreign_context["id"],
            },
            headers=headers,
        )
        assert response.status_code == 422
        assert "different site" in response.json()["detail"]

    def test_student_submission_starts_pending(
        self, client: TestClient, db: Session, researcher: User, student: User, site: dict
    ) -> None:
        client.post(
            f"/api/v1/projects/{site['project_id']}/members",
            json={"user_id": str(student.id), "role": "student"},
            headers=auth_headers(client, "researcher"),
        )
        created = client.post(
            "/api/v1/artifacts",
            json={"site_id": site["id"], "inventory_number": "STU-1", "is_public": True},
            headers=auth_headers(client, "student"),
        )
        assert created.status_code == 201
        assert created.json()["review_status"] == "pending"

        # Not yet approved, so the public must not see it.
        assert client.get("/api/v1/artifacts").json()["total"] == 0

    def test_researcher_submission_is_approved_immediately(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        created = client.post(
            "/api/v1/artifacts",
            json={"site_id": site["id"], "inventory_number": "RES-1"},
            headers=auth_headers(client, "researcher"),
        )
        assert created.json()["review_status"] == "approved"

    def test_filters(self, client: TestClient, db: Session, researcher: User, site: dict) -> None:
        headers = auth_headers(client, "researcher")
        for number, object_type, date_from in (
            ("F-1", "Bowl", -2800),
            ("F-2", "Blade", -1200),
        ):
            client.post(
                "/api/v1/artifacts",
                json={
                    "site_id": site["id"],
                    "inventory_number": number,
                    "object_type": object_type,
                    "date_from": date_from,
                    "date_to": date_from + 100,
                    "is_public": True,
                },
                headers=headers,
            )
        assert client.get("/api/v1/artifacts?object_type=bowl").json()["total"] == 1
        assert client.get("/api/v1/artifacts?date_from=-1300&date_to=-1100").json()["total"] == 1
        assert client.get(f"/api/v1/artifacts?site_id={site['id']}").json()["total"] == 2


class TestContextCrud:
    def test_create_and_relationship_is_mirrored(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        cut = client.post(
            "/api/v1/contexts",
            json={
                "site_id": site["id"],
                "context_number": "1042",
                "context_type": "cut",
                "is_public": True,
            },
            headers=headers,
        ).json()
        fill = client.post(
            "/api/v1/contexts",
            json={
                "site_id": site["id"],
                "context_number": "1041",
                "context_type": "fill",
                "is_public": True,
            },
            headers=headers,
        ).json()

        response = client.post(
            f"/api/v1/contexts/{fill['id']}/relationships",
            json={"related_context_id": cut["id"], "relation": "fills", "certainty": "certain"},
            headers=headers,
        )
        assert response.status_code == 201
        assert response.json()[0]["relation"] == "fills"

        # The inverse edge must exist without being asked for.
        mirrored = client.get(f"/api/v1/contexts/{cut['id']}/relationships", headers=headers).json()
        assert [edge["relation"] for edge in mirrored] == ["filled_by"]

    def test_removing_a_relationship_removes_its_mirror(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        a = client.post(
            "/api/v1/contexts",
            json={"site_id": site["id"], "context_number": "2001"},
            headers=headers,
        ).json()
        b = client.post(
            "/api/v1/contexts",
            json={"site_id": site["id"], "context_number": "2002"},
            headers=headers,
        ).json()
        edges = client.post(
            f"/api/v1/contexts/{a['id']}/relationships",
            json={"related_context_id": b["id"], "relation": "above"},
            headers=headers,
        ).json()

        client.delete(f"/api/v1/contexts/{a['id']}/relationships/{edges[0]['id']}", headers=headers)
        assert client.get(f"/api/v1/contexts/{b['id']}/relationships", headers=headers).json() == []

    def test_self_relationship_is_rejected(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        context = client.post(
            "/api/v1/contexts",
            json={"site_id": site["id"], "context_number": "3001"},
            headers=headers,
        ).json()
        response = client.post(
            f"/api/v1/contexts/{context['id']}/relationships",
            json={"related_context_id": context["id"], "relation": "above"},
            headers=headers,
        )
        assert response.status_code == 422

    def test_cross_site_relationship_is_rejected(
        self, client: TestClient, db: Session, researcher: User, project: dict, site: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        other_site = client.post(
            "/api/v1/sites",
            json={"project_id": project["id"], "name": "Far", "code": "FAR"},
            headers=headers,
        ).json()
        here = client.post(
            "/api/v1/contexts",
            json={"site_id": site["id"], "context_number": "4001"},
            headers=headers,
        ).json()
        there = client.post(
            "/api/v1/contexts",
            json={"site_id": other_site["id"], "context_number": "4002"},
            headers=headers,
        ).json()

        response = client.post(
            f"/api/v1/contexts/{here['id']}/relationships",
            json={"related_context_id": there["id"], "relation": "above"},
            headers=headers,
        )
        assert response.status_code == 422

    def test_inverted_elevations_are_rejected(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        response = client.post(
            "/api/v1/contexts",
            json={
                "site_id": site["id"],
                "context_number": "5001",
                "top_elevation": 100.0,
                "bottom_elevation": 200.0,
            },
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 422

    def test_deleting_a_context_keeps_its_artifacts(
        self, client: TestClient, db: Session, researcher: User, site: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        context = client.post(
            "/api/v1/contexts",
            json={"site_id": site["id"], "context_number": "6001"},
            headers=headers,
        ).json()
        artifact = client.post(
            "/api/v1/artifacts",
            json={
                "site_id": site["id"],
                "inventory_number": "KEEP-1",
                "context_id": context["id"],
                "is_public": True,
            },
            headers=headers,
        ).json()

        assert (
            client.delete(f"/api/v1/contexts/{context['id']}", headers=headers).status_code == 200
        )

        survivor = client.get(f"/api/v1/artifacts/{artifact['id']}", headers=headers)
        assert survivor.status_code == 200, "a find must outlive its context record"
        assert survivor.json()["context_id"] is None


class TestCascades:
    def test_deleting_a_project_removes_its_contents(
        self, client: TestClient, db: Session, researcher: User, project: dict, site: dict
    ) -> None:
        headers = auth_headers(client, "researcher")
        client.post(
            "/api/v1/artifacts",
            json={"site_id": site["id"], "inventory_number": "CASC-1"},
            headers=headers,
        )
        client.delete(f"/api/v1/projects/{project['id']}", headers=headers)

        assert db.get(Site, site["id"]) is None
        assert db.scalar(select(Site).where(Site.project_id == project["id"])) is None

    def test_review_status_hides_pending_from_listings(
        self, client: TestClient, db: Session, researcher: User, student: User, site: dict
    ) -> None:
        client.post(
            f"/api/v1/projects/{site['project_id']}/members",
            json={"user_id": str(student.id), "role": "student"},
            headers=auth_headers(client, "researcher"),
        )
        client.post(
            "/api/v1/contexts",
            json={"site_id": site["id"], "context_number": "7001", "is_public": True},
            headers=auth_headers(client, "student"),
        )
        assert client.get("/api/v1/contexts").json()["total"] == 0
        reviewer_view = client.get(
            "/api/v1/contexts", headers=auth_headers(client, "researcher")
        ).json()
        assert reviewer_view["total"] == 1
        assert reviewer_view["items"][0]["review_status"] == ReviewStatus.PENDING.value
