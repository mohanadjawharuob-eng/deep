"""Global search: results, filters and — most importantly — permissions."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from tests.conftest import auth_headers, make_user


@pytest.fixture
def world(client: TestClient, db: Session, researcher: User) -> dict:
    """A public project with content, plus a private one that must stay hidden."""
    headers = auth_headers(client, "researcher")

    public_project = client.post(
        "/api/v1/projects",
        json={
            "name": "Caesarea Maritima Survey",
            "code": "CAES-1",
            "institution": "University of Haifa",
            "country": "Israel",
            "principal_investigator": "Dana Levi",
            "is_public": True,
        },
        headers=headers,
    ).json()

    private_project = client.post(
        "/api/v1/projects",
        json={"name": "Confidential Dig", "code": "SECRET-1", "is_public": False},
        headers=headers,
    ).json()

    public_site = client.post(
        "/api/v1/sites",
        json={
            "project_id": public_project["id"],
            "name": "Caesarea Harbour",
            "code": "CH",
            "alternative_names": ["Qisarya"],
            "country": "Israel",
            "latitude": 32.5,
            "longitude": 34.9,
            "date_from": -100,
            "date_to": 400,
            "is_public": True,
        },
        headers=headers,
    ).json()

    private_site = client.post(
        "/api/v1/sites",
        json={
            "project_id": private_project["id"],
            "name": "Caesarea Secret Trench",
            "code": "CST",
            "is_public": False,
        },
        headers=headers,
    ).json()

    artifact = client.post(
        "/api/v1/artifacts",
        json={
            "site_id": public_site["id"],
            "inventory_number": "CH-2024-0001",
            "name": "Herodian amphora",
            "object_type": "Amphora",
            "description": "Wine amphora from the harbour fill",
            "date_from": -30,
            "date_to": 70,
            "is_public": True,
        },
        headers=headers,
    ).json()

    context = client.post(
        "/api/v1/contexts",
        json={
            "site_id": public_site["id"],
            "context_number": "H-101",
            "description": "Harbour silt deposit",
            "excavated_by": "Dana Levi",
            "is_public": True,
        },
        headers=headers,
    ).json()

    return {
        "public_project": public_project,
        "private_project": private_project,
        "public_site": public_site,
        "private_site": private_site,
        "artifact": artifact,
        "context": context,
    }


class TestSearchBasics:
    def test_requires_a_term_or_filter(self, client: TestClient) -> None:
        response = client.get("/api/v1/search")
        assert response.status_code == 422
        assert "at least one filter" in response.json()["detail"]

    def test_finds_across_every_type(self, client: TestClient, world: dict) -> None:
        results = client.get("/api/v1/search?q=caesarea").json()
        assert results["counts"]["project"] == 1
        assert results["counts"]["site"] == 1
        types = {item["resource_type"] for item in results["items"]}
        assert types == {"project", "site"}

    def test_matches_artifact_fields(self, client: TestClient, world: dict) -> None:
        assert client.get("/api/v1/search?q=amphora").json()["counts"]["artifact"] == 1
        assert client.get("/api/v1/search?q=CH-2024").json()["counts"]["artifact"] == 1
        assert client.get("/api/v1/search?q=harbour+fill").json()["counts"]["artifact"] == 1

    def test_matches_site_alternative_names(self, client: TestClient, world: dict) -> None:
        assert client.get("/api/v1/search?q=qisarya").json()["counts"]["site"] == 1

    def test_matches_context_description(self, client: TestClient, world: dict) -> None:
        results = client.get("/api/v1/search?q=silt").json()
        assert results["counts"]["context"] == 1
        assert results["items"][0]["title"] == "H-101"

    def test_type_restriction(self, client: TestClient, world: dict) -> None:
        results = client.get("/api/v1/search?q=caesarea&types=site").json()
        assert set(results["counts"]) == {"site"}

    def test_no_match_is_an_empty_result_not_an_error(
        self, client: TestClient, world: dict
    ) -> None:
        results = client.get("/api/v1/search?q=zzzznotfound").json()
        assert results["total"] == 0
        assert results["items"] == []


class TestSearchFilters:
    def test_date_range_overlap(self, client: TestClient, world: dict) -> None:
        # The amphora is dated 30 BCE – 70 CE; the site 100 BCE – 400 CE.
        inside = client.get("/api/v1/search?date_from=0&date_to=50").json()
        assert inside["counts"].get("artifact") == 1
        assert inside["counts"].get("site") == 1

        outside = client.get("/api/v1/search?date_from=-5000&date_to=-4000").json()
        assert outside["counts"].get("artifact", 0) == 0

    def test_country_filter(self, client: TestClient, world: dict) -> None:
        assert client.get("/api/v1/search?country=Israel").json()["counts"]["site"] == 1
        assert client.get("/api/v1/search?country=Peru").json()["counts"].get("site", 0) == 0

    def test_institution_filter_reaches_sites_through_their_project(
        self, client: TestClient, world: dict
    ) -> None:
        results = client.get("/api/v1/search?institution=Haifa").json()
        assert results["counts"]["project"] == 1
        assert results["counts"]["site"] == 1

    def test_researcher_filter(self, client: TestClient, world: dict) -> None:
        results = client.get("/api/v1/search?researcher=Dana").json()
        assert results["counts"]["project"] == 1
        assert results["counts"]["context"] == 1

    def test_bbox_filter(self, client: TestClient, world: dict) -> None:
        assert client.get("/api/v1/search?bbox=34,32,35,33").json()["counts"]["site"] == 1
        assert client.get("/api/v1/search?bbox=0,0,1,1").json()["counts"].get("site", 0) == 0

    def test_project_scoping(self, client: TestClient, world: dict) -> None:
        results = client.get(
            f"/api/v1/search?project_id={world['public_project']['id']}&q=a"
        ).json()
        assert results["counts"]["site"] == 1
        assert results["counts"]["artifact"] == 1

    def test_malformed_bbox_is_rejected(self, client: TestClient) -> None:
        assert client.get("/api/v1/search?bbox=1,2,3").status_code == 422


class TestSearchPermissions:
    def test_anonymous_never_sees_private_records(self, client: TestClient, world: dict) -> None:
        results = client.get("/api/v1/search?q=caesarea").json()
        titles = {item["title"] for item in results["items"]}
        assert "Caesarea Secret Trench" not in titles
        assert "Confidential Dig" not in titles

    def test_outsider_never_sees_private_records(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        make_user(db, email="curious@x.org", username="curious")
        results = client.get(
            "/api/v1/search?q=caesarea", headers=auth_headers(client, "curious")
        ).json()
        titles = {item["title"] for item in results["items"]}
        assert "Caesarea Secret Trench" not in titles

    def test_the_team_does_see_their_private_records(
        self, client: TestClient, world: dict, researcher: User
    ) -> None:
        results = client.get(
            "/api/v1/search?q=caesarea", headers=auth_headers(client, "researcher")
        ).json()
        titles = {item["title"] for item in results["items"]}
        assert "Caesarea Secret Trench" in titles

    def test_pending_records_are_not_searchable_by_the_public(
        self, client: TestClient, db: Session, world: dict, researcher: User
    ) -> None:
        student = make_user(db, email="s2@x.org", username="digger2")
        client.post(
            f"/api/v1/projects/{world['public_project']['id']}/members",
            json={"user_id": str(student.id), "role": "student"},
            headers=auth_headers(client, "researcher"),
        )
        client.post(
            "/api/v1/artifacts",
            json={
                "site_id": world["public_site"]["id"],
                "inventory_number": "PENDING-1",
                "name": "Unreviewed lamp",
                "is_public": True,
            },
            headers=auth_headers(client, "digger2"),
        )
        assert client.get("/api/v1/search?q=unreviewed").json()["total"] == 0
        reviewer = client.get(
            "/api/v1/search?q=unreviewed", headers=auth_headers(client, "researcher")
        ).json()
        assert reviewer["total"] == 1

    def test_restricted_coordinates_are_blurred_in_search_too(
        self, client: TestClient, world: dict, researcher: User
    ) -> None:
        client.patch(
            f"/api/v1/sites/{world['public_site']['id']}",
            json={"location_restricted": True},
            headers=auth_headers(client, "researcher"),
        )
        hit = next(
            item
            for item in client.get("/api/v1/search?q=harbour&types=site").json()["items"]
            if item["resource_type"] == "site"
        )
        assert hit["latitude"] == 32.5, "search must not leak an exact restricted position"


class TestSuggest:
    def test_suggests_sites_and_projects(self, client: TestClient, world: dict) -> None:
        suggestions = client.get("/api/v1/search/suggest?q=caes").json()
        labels = {item["label"] for item in suggestions}
        assert "Caesarea Maritima Survey" in labels
        assert "Confidential Dig" not in labels

    def test_suggests_vocabulary_terms(self, client: TestClient, db: Session) -> None:
        from app.models import Material

        db.add(Material(name="Obsidian", slug="obsidian", group="stone"))
        db.flush()
        suggestions = client.get("/api/v1/search/suggest?q=obsid").json()
        assert any(item["kind"] == "material" for item in suggestions)

    def test_short_queries_are_rejected(self, client: TestClient) -> None:
        assert client.get("/api/v1/search/suggest?q=a").status_code == 422
