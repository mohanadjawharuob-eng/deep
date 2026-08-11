"""The museum collection module.

The property most of these defend is that **an institution's own numbering
survives contact with the platform**. A collection that cannot record
``1974.1a-bis`` because the software wants ``NM.1974.0001`` is a collection
that stays in its spreadsheet, so the awkward cases below are the important
ones.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Material, Module, ModuleLevel, MuseumObject, User, UserRole
from app.services import accession
from tests.conftest import auth_headers, make_user


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def curator(db: Session) -> User:
    """A collections manager: senior in the museum, absent from archaeology."""
    return make_user(
        db,
        email="curator@example.org",
        username="curator",
        role=UserRole.VISITOR,
        modules={Module.MUSEUM: ModuleLevel.SUPERVISOR},
        grant_defaults=False,
    )


@pytest.fixture
def cataloguer(db: Session) -> User:
    return make_user(
        db,
        email="cataloguer@example.org",
        username="cataloguer",
        role=UserRole.VISITOR,
        modules={Module.MUSEUM: ModuleLevel.CONTRIBUTOR},
        grant_defaults=False,
    )


@pytest.fixture
def collection(client: TestClient, curator: User) -> dict:
    response = client.post(
        "/api/v1/museum/collections",
        json={
            "name": "Archaeological Collection",
            "code": "arch",
            "accession_pattern": "{prefix}.{year}.{seq:04d}",
            "accession_prefix": "NM",
            "institution": "National Museum",
        },
        headers=auth_headers(client, "curator"),
    )
    assert response.status_code == 201, response.text
    return response.json()


def catalogue(client: TestClient, collection_id: str, *, identifier: str = "curator", **fields):
    body = {"collection_id": collection_id, "title": "Storage jar", **fields}
    return client.post(
        "/api/v1/museum/objects", json=body, headers=auth_headers(client, identifier)
    )


# --------------------------------------------------------------------------
# Collections and numbering
# --------------------------------------------------------------------------
class TestCollections:
    def test_a_collection_declares_its_own_numbering(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        assert collection["code"] == "ARCH"
        assert collection["accession_pattern"] == "{prefix}.{year}.{seq:04d}"
        assert collection["next_accession_number"].startswith("NM.")
        assert collection["next_accession_number"].endswith(".0001")

    def test_a_pattern_that_cannot_work_is_refused(self, client: TestClient, curator: User) -> None:
        response = client.post(
            "/api/v1/museum/collections",
            json={"name": "Broken", "code": "BRK", "accession_pattern": "{prefix}.{year}"},
            headers=auth_headers(client, "curator"),
        )
        assert response.status_code == 422
        assert "{seq}" in response.json()["detail"]

    def test_an_unknown_placeholder_is_named(self, client: TestClient, curator: User) -> None:
        response = client.post(
            "/api/v1/museum/collections",
            json={"name": "Broken", "code": "BRK2", "accession_pattern": "{museum}-{seq}"},
            headers=auth_headers(client, "curator"),
        )
        assert response.status_code == 422
        assert "{museum}" in response.json()["detail"]

    def test_duplicate_codes_are_refused(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        response = client.post(
            "/api/v1/museum/collections",
            json={"name": "Another", "code": "ARCH"},
            headers=auth_headers(client, "curator"),
        )
        assert response.status_code == 409

    def test_configuring_numbering_is_a_supervisors_job(
        self, client: TestClient, cataloguer: User
    ) -> None:
        response = client.post(
            "/api/v1/museum/collections",
            json={"name": "Mine", "code": "MINE"},
            headers=auth_headers(client, "cataloguer"),
        )
        assert response.status_code == 403


class TestAccessionNumbering:
    def test_numbers_are_issued_in_sequence(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        numbers = [
            catalogue(client, collection["id"], title=f"Object {index}").json()["accession_number"]
            for index in range(3)
        ]
        year = date.today().year
        assert numbers == [f"NM.{year}.0001", f"NM.{year}.0002", f"NM.{year}.0003"]

    def test_a_number_typed_by_hand_is_honoured(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        year = date.today().year
        body = catalogue(client, collection["id"], accession_number=f"NM.{year}.0500").json()

        assert body["accession_number"] == f"NM.{year}.0500"
        assert body["number_is_legacy"] is False
        assert body["accession_warning"] is None

    def test_the_sequence_continues_past_a_number_typed_by_hand(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        """The stored counter is advisory and must be reconciled with reality."""
        year = date.today().year
        catalogue(client, collection["id"], accession_number=f"NM.{year}.0500")

        following = catalogue(client, collection["id"], title="Next").json()
        assert following["accession_number"] == f"NM.{year}.0501"

    def test_a_legacy_number_is_recorded_and_flagged(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        """The case that decides whether a collection can be migrated at all."""
        response = catalogue(client, collection["id"], accession_number="1974.1a-bis")
        assert response.status_code == 201, response.text
        body = response.json()

        assert body["accession_number"] == "1974.1a-bis"
        assert body["number_is_legacy"] is True
        assert "legacy" in body["accession_warning"]

    def test_a_legacy_number_does_not_disturb_the_sequence(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        catalogue(client, collection["id"], accession_number="1974.1a-bis")
        following = catalogue(client, collection["id"], title="Next").json()

        year = date.today().year
        assert following["accession_number"] == f"NM.{year}.0001"

    def test_a_collection_may_insist_on_its_pattern(
        self, client: TestClient, curator: User
    ) -> None:
        strict = client.post(
            "/api/v1/museum/collections",
            json={
                "name": "Strict",
                "code": "STRICT",
                "accession_pattern": "{prefix}.{seq:04d}",
                "accession_prefix": "S",
                "enforce_pattern": True,
            },
            headers=auth_headers(client, "curator"),
        ).json()

        response = catalogue(client, strict["id"], accession_number="whatever")
        assert response.status_code == 422
        assert "requires numbers to follow its pattern" in response.json()["detail"]

    def test_a_duplicate_number_within_a_collection_is_refused(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        catalogue(client, collection["id"], accession_number="NM.2024.9999")
        response = catalogue(client, collection["id"], accession_number="NM.2024.9999")

        assert response.status_code == 422
        assert "already used" in response.json()["detail"]

    def test_the_same_number_may_exist_in_two_collections(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        """Two museums both have a 1974.1, and so may two of our collections."""
        other = client.post(
            "/api/v1/museum/collections",
            json={"name": "Ethnography", "code": "ETH"},
            headers=auth_headers(client, "curator"),
        ).json()

        assert catalogue(client, collection["id"], accession_number="1974.1").status_code == 201
        assert catalogue(client, other["id"], accession_number="1974.1").status_code == 201

    def test_the_preview_shows_the_next_number_without_issuing_it(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        headers = auth_headers(client, "curator")
        first = client.get(
            f"/api/v1/museum/collections/{collection['id']}/next-number", headers=headers
        ).json()
        second = client.get(
            f"/api/v1/museum/collections/{collection['id']}/next-number", headers=headers
        ).json()

        assert first["next_accession_number"] == second["next_accession_number"]

    def test_the_preview_judges_a_candidate(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        headers = auth_headers(client, "curator")
        catalogue(client, collection["id"], accession_number="NM.2024.0777")

        taken = client.get(
            f"/api/v1/museum/collections/{collection['id']}/next-number",
            params={"candidate": "NM.2024.0777"},
            headers=headers,
        ).json()
        assert taken["candidate_is_available"] is False

        odd = client.get(
            f"/api/v1/museum/collections/{collection['id']}/next-number",
            params={"candidate": "1974.1a"},
            headers=headers,
        ).json()
        assert odd["candidate_matches_pattern"] is False
        assert odd["candidate_is_available"] is True

    @pytest.mark.parametrize(
        ("pattern", "prefix", "expected"),
        [
            ("{prefix}.{year}.{seq:04d}", "NM", "NM.2024.0007"),
            ("{code}-{yy}/{seq}", None, "ARCH-24/7"),
            ("{seq:06d}", None, "000007"),
            ("AN{year}.{seq:03d}", None, "AN2024.007"),
        ],
    )
    def test_patterns_render_and_match_themselves(
        self, pattern: str, prefix: str | None, expected: str
    ) -> None:
        accession.validate_pattern(pattern)
        rendered = accession.render(pattern, prefix=prefix, code="ARCH", year=2024, sequence=7)
        assert rendered == expected
        assert accession.pattern_to_regex(pattern).match(rendered)


# --------------------------------------------------------------------------
# Objects
# --------------------------------------------------------------------------
class TestObjects:
    def test_cataloguing_records_the_whole_form(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        response = catalogue(
            client,
            collection["id"],
            title="Everted-rim cooking pot",
            description="Handmade, heavily sooted",
            object_type="Cooking pot",
            culture="Early Bronze Age Levantine",
            date_from=-3000,
            date_to=-2700,
            materials=["Ceramic"],
            height_mm=182.5,
            diameter_mm=214.0,
            weight_g=1340.0,
            acquisition_method="excavation",
            acquisition_source="Tell el-Demo 2024 season",
            provenance="Excavated 2024, Trench A, context 1042.",
            credit_line="Institute of Archaeology, 2024 excavation",
        )
        assert response.status_code == 201, response.text
        body = response.json()

        assert body["date_from"] == -3000
        assert body["materials"] == ["Ceramic"]
        assert body["height_mm"] == pytest.approx(182.5)
        assert body["acquisition_method"] == "excavation"
        assert body["provenance"].startswith("Excavated 2024")

    def test_an_impossible_date_range_is_refused(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        response = catalogue(client, collection["id"], date_from=-2000, date_to=-3000)
        assert response.status_code == 422

    def test_an_object_can_be_found_by_its_number(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        created = catalogue(client, collection["id"], accession_number="NM.2024.0042").json()

        found = client.get(
            "/api/v1/museum/objects/by-number/NM.2024.0042",
            headers=auth_headers(client, "curator"),
        )
        assert found.status_code == 200
        assert found.json()["id"] == created["id"]

    def test_an_ambiguous_number_asks_which_collection(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        other = client.post(
            "/api/v1/museum/collections",
            json={"name": "Ethnography", "code": "ETH2"},
            headers=auth_headers(client, "curator"),
        ).json()
        catalogue(client, collection["id"], accession_number="1974.1")
        catalogue(client, other["id"], accession_number="1974.1")

        response = client.get(
            "/api/v1/museum/objects/by-number/1974.1", headers=auth_headers(client, "curator")
        )
        assert response.status_code == 409
        assert "collection_id" in response.json()["detail"]

    def test_search_matches_numbers_and_words(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        headers = auth_headers(client, "curator")
        catalogue(client, collection["id"], title="Bronze fibula", maker="Unknown workshop")
        catalogue(client, collection["id"], title="Flint blade")

        found = client.get("/api/v1/museum/objects", params={"q": "fibula"}, headers=headers).json()
        assert [item["title"] for item in found["items"]] == ["Bronze fibula"]

    def test_the_former_number_is_searchable(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        catalogue(client, collection["id"], former_number="OLD-1893-77")

        found = client.get(
            "/api/v1/museum/objects",
            params={"q": "1893"},
            headers=auth_headers(client, "curator"),
        ).json()
        assert found["total"] == 1

    def test_identity_cannot_be_changed_by_a_field_edit(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        """Renumbering is an audited operation, not a form field."""
        obj = catalogue(client, collection["id"]).json()

        client.patch(
            f"/api/v1/museum/objects/{obj['id']}",
            json={"accession_number": "SOMETHING.ELSE", "title": "Renamed"},
            headers=auth_headers(client, "curator"),
        )
        after = client.get(
            f"/api/v1/museum/objects/{obj['id']}", headers=auth_headers(client, "curator")
        ).json()

        assert after["accession_number"] == obj["accession_number"]
        assert after["title"] == "Renamed"


class TestArtifactLink:
    @pytest.fixture
    def artifact(self, client: TestClient, db: Session, curator: User) -> dict:
        """An excavated find, made by somebody who works in archaeology."""
        make_user(db, email="digger@example.org", username="digger", role=UserRole.RESEARCHER)
        headers = auth_headers(client, "digger")
        project = client.post(
            "/api/v1/projects",
            json={"name": "Museum Link", "code": "ml-1", "is_public": True},
            headers=headers,
        ).json()
        site = client.post(
            "/api/v1/sites",
            json={
                "project_id": project["id"],
                "name": "Tell Link",
                "code": "TL",
                "is_public": True,
            },
            headers=headers,
        ).json()
        return client.post(
            "/api/v1/artifacts",
            json={
                "site_id": site["id"],
                "inventory_number": "ML-2024-001",
                "name": "Cooking pot",
                "is_public": True,
            },
            headers=headers,
        ).json()

    def test_an_object_can_point_at_its_excavation_record(
        self, client: TestClient, curator: User, collection: dict, artifact: dict
    ) -> None:
        response = catalogue(client, collection["id"], artifact_id=artifact["id"])
        assert response.status_code == 201, response.text
        assert response.json()["artifact_id"] == artifact["id"]

    def test_most_objects_have_no_excavation_record(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        """A donation or purchase has nothing to link to, and that is normal."""
        body = catalogue(client, collection["id"], acquisition_method="donation").json()
        assert body["artifact_id"] is None

    def test_two_objects_cannot_claim_the_same_find(
        self, client: TestClient, curator: User, collection: dict, artifact: dict
    ) -> None:
        """Otherwise "what happened to this artifact" has two answers."""
        catalogue(client, collection["id"], artifact_id=artifact["id"])
        response = catalogue(client, collection["id"], artifact_id=artifact["id"])

        assert response.status_code == 409
        assert "already catalogued" in response.json()["detail"]

    def test_a_link_to_a_nonexistent_artifact_is_refused(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        import uuid as uuid_module

        response = catalogue(client, collection["id"], artifact_id=str(uuid_module.uuid4()))
        assert response.status_code == 422

    def test_filtering_by_whether_there_is_a_link(
        self, client: TestClient, curator: User, collection: dict, artifact: dict
    ) -> None:
        headers = auth_headers(client, "curator")
        catalogue(client, collection["id"], title="From the ground", artifact_id=artifact["id"])
        catalogue(client, collection["id"], title="A donation")

        excavated = client.get(
            "/api/v1/museum/objects", params={"has_artifact": True}, headers=headers
        ).json()
        assert [item["title"] for item in excavated["items"]] == ["From the ground"]


# --------------------------------------------------------------------------
# Valuations are not public
# --------------------------------------------------------------------------
class TestValuationVisibility:
    def test_a_valuation_is_withheld_from_anyone_who_cannot_edit(
        self, client: TestClient, db: Session, curator: User, collection: dict
    ) -> None:
        """A valuation on a record anyone can read is an invitation."""
        obj = catalogue(
            client,
            collection["id"],
            is_public=True,
            valuation_amount=45000,
            valuation_currency="EUR",
            insurance_reference="POL-2024-88",
        ).json()
        assert obj["valuation_amount"] == pytest.approx(45000)

        public = client.get(f"/api/v1/museum/objects/{obj['id']}").json()
        assert public["valuation_amount"] is None
        assert public["insurance_reference"] is None

    def test_a_museum_viewer_who_cannot_edit_also_sees_no_valuation(
        self, client: TestClient, db: Session, curator: User, collection: dict
    ) -> None:
        make_user(
            db,
            email="visitor2@example.org",
            username="viewer.only",
            role=UserRole.VISITOR,
            modules={Module.MUSEUM: ModuleLevel.VIEWER},
            grant_defaults=False,
        )
        obj = catalogue(client, collection["id"], valuation_amount=1000).json()

        seen = client.get(
            f"/api/v1/museum/objects/{obj['id']}", headers=auth_headers(client, "viewer.only")
        ).json()
        assert seen["valuation_amount"] is None


# --------------------------------------------------------------------------
# Conservation
# --------------------------------------------------------------------------
class TestConservation:
    def test_a_treatment_is_appended_and_updates_the_condition(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        headers = auth_headers(client, "curator")
        obj = catalogue(client, collection["id"], condition="poor").json()

        response = client.post(
            f"/api/v1/museum/objects/{obj['id']}/conservation",
            json={
                "treatment_type": "consolidation",
                "performed_on": "2024-06-10",
                "conservator": "A. Rossi",
                "condition_before": "poor",
                "condition_after": "fair",
                "description": "Surface consolidation with Paraloid B72 in acetone.",
                "materials_used": "Paraloid B72, 5% in acetone",
                "next_review_on": "2025-06-10",
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text

        after = client.get(f"/api/v1/museum/objects/{obj['id']}", headers=headers).json()
        assert after["condition"] == "fair"
        assert after["last_checked_on"] == "2024-06-10"
        assert after["treatment_count"] == 1

    def test_the_history_reads_oldest_first(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        headers = auth_headers(client, "curator")
        obj = catalogue(client, collection["id"]).json()

        for when, kind in (
            ("2024-06-10", "cleaning"),
            ("2023-01-05", "examination"),
            ("2024-11-02", "mounting"),
        ):
            client.post(
                f"/api/v1/museum/objects/{obj['id']}/conservation",
                json={"treatment_type": kind, "performed_on": when, "description": kind},
                headers=headers,
            )

        history = client.get(
            f"/api/v1/museum/objects/{obj['id']}/conservation", headers=headers
        ).json()
        assert [row["performed_on"] for row in history] == [
            "2023-01-05",
            "2024-06-10",
            "2024-11-02",
        ]

    def test_a_historical_treatment_need_not_change_the_current_condition(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        headers = auth_headers(client, "curator")
        obj = catalogue(client, collection["id"], condition="good").json()

        client.post(
            f"/api/v1/museum/objects/{obj['id']}/conservation",
            json={
                "performed_on": "1998-03-01",
                "description": "Catalogued from an old card.",
                "condition_after": "poor",
                "update_object_condition": False,
            },
            headers=headers,
        )
        after = client.get(f"/api/v1/museum/objects/{obj['id']}", headers=headers).json()
        assert after["condition"] == "good"

    def test_the_review_list_is_what_a_conservator_works_from(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        headers = auth_headers(client, "curator")
        obj = catalogue(client, collection["id"]).json()

        overdue = (date.today() - timedelta(days=30)).isoformat()
        future = (date.today() + timedelta(days=365)).isoformat()
        for review in (overdue, future):
            client.post(
                f"/api/v1/museum/objects/{obj['id']}/conservation",
                json={
                    "performed_on": "2024-01-01",
                    "description": "Check",
                    "next_review_on": review,
                },
                headers=headers,
            )

        due = client.get("/api/v1/museum/conservation/due", headers=headers).json()
        assert due["total"] == 1
        assert due["items"][0]["next_review_on"] == overdue


# --------------------------------------------------------------------------
# Exhibitions and loans
# --------------------------------------------------------------------------
class TestExhibitions:
    def test_an_object_can_be_shown_with_its_own_label(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        headers = auth_headers(client, "curator")
        obj = catalogue(client, collection["id"], title="Cooking pot").json()
        exhibition = client.post(
            "/api/v1/museum/exhibitions",
            json={"title": "Kitchens of the Bronze Age", "opens_on": "2025-03-01"},
            headers=headers,
        ).json()

        added = client.post(
            f"/api/v1/museum/exhibitions/{exhibition['id']}/items",
            json={
                "museum_object_id": obj["id"],
                "label_text": "Cooking pot, used daily and thrown away.",
                "case_number": "4",
            },
            headers=headers,
        )
        assert added.status_code == 201, added.text
        assert added.json()["accession_number"] == obj["accession_number"]

        shown_in = client.get(
            f"/api/v1/museum/objects/{obj['id']}/exhibitions", headers=headers
        ).json()
        assert [row["title"] for row in shown_in] == ["Kitchens of the Bronze Age"]

    def test_an_object_cannot_be_added_to_one_exhibition_twice(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        headers = auth_headers(client, "curator")
        obj = catalogue(client, collection["id"]).json()
        exhibition = client.post(
            "/api/v1/museum/exhibitions", json={"title": "Show"}, headers=headers
        ).json()

        body = {"museum_object_id": obj["id"]}
        client.post(
            f"/api/v1/museum/exhibitions/{exhibition['id']}/items", json=body, headers=headers
        )
        again = client.post(
            f"/api/v1/museum/exhibitions/{exhibition['id']}/items", json=body, headers=headers
        )
        assert again.status_code == 409

    def test_a_closing_date_before_the_opening_is_refused(
        self, client: TestClient, curator: User
    ) -> None:
        response = client.post(
            "/api/v1/museum/exhibitions",
            json={"title": "Impossible", "opens_on": "2025-06-01", "closes_on": "2025-01-01"},
            headers=auth_headers(client, "curator"),
        )
        assert response.status_code == 422


class TestLoans:
    """Loans are built although the institution does not currently lend.

    Loan paperwork becomes urgent with three weeks' notice; adding the table
    then would mean a migration in the middle of it.
    """

    def test_an_outgoing_loan_moves_its_objects_status(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        headers = auth_headers(client, "curator")
        obj = catalogue(client, collection["id"]).json()
        loan = client.post(
            "/api/v1/museum/loans",
            json={
                "reference": "OUT-2025-01",
                "direction": "outgoing",
                "counterparty": "British Museum",
                "starts_on": "2025-03-01",
                "ends_on": "2025-09-01",
            },
            headers=headers,
        ).json()
        client.post(
            f"/api/v1/museum/loans/{loan['id']}/items",
            json={"museum_object_id": obj["id"], "condition_out": "good"},
            headers=headers,
        )

        client.patch(
            f"/api/v1/museum/loans/{loan['id']}", json={"status": "on_loan"}, headers=headers
        )
        assert (
            client.get(f"/api/v1/museum/objects/{obj['id']}", headers=headers).json()["status"]
            == "on_loan"
        )

        client.patch(
            f"/api/v1/museum/loans/{loan['id']}", json={"status": "returned"}, headers=headers
        )
        assert (
            client.get(f"/api/v1/museum/objects/{obj['id']}", headers=headers).json()["status"]
            == "accessioned"
        )

    def test_an_incoming_loan_describes_somebody_elses_object(
        self, client: TestClient, curator: User
    ) -> None:
        """It is not ours, so it has no accession number here."""
        headers = auth_headers(client, "curator")
        loan = client.post(
            "/api/v1/museum/loans",
            json={"reference": "IN-2025-01", "direction": "incoming", "counterparty": "Louvre"},
            headers=headers,
        ).json()

        added = client.post(
            f"/api/v1/museum/loans/{loan['id']}/items",
            json={"external_description": "Attic red-figure kylix, inv. G 104"},
            headers=headers,
        )
        assert added.status_code == 201, added.text
        assert added.json()["museum_object_id"] is None

    def test_a_loan_item_must_identify_something(self, client: TestClient, curator: User) -> None:
        headers = auth_headers(client, "curator")
        loan = client.post(
            "/api/v1/museum/loans",
            json={"reference": "IN-2025-02", "direction": "incoming", "counterparty": "X"},
            headers=headers,
        ).json()

        response = client.post(f"/api/v1/museum/loans/{loan['id']}/items", json={}, headers=headers)
        assert response.status_code == 422

    def test_a_duplicate_reference_is_refused(self, client: TestClient, curator: User) -> None:
        headers = auth_headers(client, "curator")
        body = {"reference": "OUT-2025-09", "direction": "outgoing", "counterparty": "A"}
        assert client.post("/api/v1/museum/loans", json=body, headers=headers).status_code == 201
        assert client.post("/api/v1/museum/loans", json=body, headers=headers).status_code == 409


# --------------------------------------------------------------------------
# Environmental monitoring
# --------------------------------------------------------------------------
class TestEnvironment:
    @pytest.fixture
    def store(self, client: TestClient, db: Session, curator: User) -> dict:
        """A room with target conditions, made by somebody who may reshape the store."""
        make_user(db, email="keeper@example.org", username="keeper", role=UserRole.RESEARCHER)
        headers = auth_headers(client, "keeper")
        building = client.post(
            "/api/v1/storage/locations",
            json={"kind": "building", "name": "Main Store", "code": "MS"},
            headers=headers,
        ).json()
        return client.post(
            "/api/v1/storage/locations",
            json={
                "kind": "room",
                "name": "Metals Store",
                "code": "MET",
                "parent_id": building["id"],
                "target_temperature_c": 18.0,
                "target_humidity_percent": 40.0,
            },
            headers=headers,
        ).json()

    def test_readings_are_logged_against_a_location(
        self, client: TestClient, curator: User, store: dict
    ) -> None:
        headers = auth_headers(client, "curator")
        response = client.post(
            "/api/v1/museum/readings",
            json={
                "location_id": store["id"],
                "temperature_c": 18.4,
                "relative_humidity": 41.0,
                "source": "Logger A",
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        assert response.json()["temperature_c"] == pytest.approx(18.4)

    def test_a_reading_with_no_measurement_is_refused(
        self, client: TestClient, curator: User, store: dict
    ) -> None:
        response = client.post(
            "/api/v1/museum/readings",
            json={"location_id": store["id"], "note": "forgot the meter"},
            headers=auth_headers(client, "curator"),
        )
        assert response.status_code == 422

    def test_conditions_are_judged_against_the_locations_target(
        self, client: TestClient, curator: User, store: dict
    ) -> None:
        """A target with no readings proves nothing; readings with no target
        cannot be judged. The summary puts the two together."""
        headers = auth_headers(client, "curator")
        base = datetime(2024, 6, 1, tzinfo=UTC)

        # Target is 18 °C / 40 %. Two of these are well outside tolerance.
        for index, (temperature, humidity) in enumerate(
            [(18.2, 41.0), (17.5, 39.0), (24.0, 62.0), (18.9, 42.0), (25.5, 65.0)]
        ):
            client.post(
                "/api/v1/museum/readings",
                json={
                    "location_id": store["id"],
                    "recorded_at": (base + timedelta(hours=index)).isoformat(),
                    "temperature_c": temperature,
                    "relative_humidity": humidity,
                },
                headers=headers,
            )

        summary = client.get(
            f"/api/v1/museum/locations/{store['id']}/conditions", headers=headers
        ).json()

        assert summary["reading_count"] == 5
        assert summary["target_temperature_c"] == pytest.approx(18.0)
        assert summary["max_temperature_c"] == pytest.approx(25.5)
        assert summary["temperature_excursions"] == 2
        assert summary["humidity_excursions"] == 2

    def test_a_location_with_no_target_reports_no_excursions(
        self, client: TestClient, db: Session, curator: User
    ) -> None:
        make_user(db, email="keeper2@example.org", username="keeper2", role=UserRole.RESEARCHER)
        room = client.post(
            "/api/v1/storage/locations",
            json={"kind": "room", "name": "Untargeted", "code": "UNT"},
            headers=auth_headers(client, "keeper2"),
        ).json()

        headers = auth_headers(client, "curator")
        client.post(
            "/api/v1/museum/readings",
            json={"location_id": room["id"], "temperature_c": 35.0},
            headers=headers,
        )
        summary = client.get(
            f"/api/v1/museum/locations/{room['id']}/conditions", headers=headers
        ).json()

        assert summary["reading_count"] == 1
        assert summary["temperature_excursions"] == 0


# --------------------------------------------------------------------------
# The form layout
# --------------------------------------------------------------------------
class TestFormLayout:
    def test_the_layout_describes_a_cataloguing_card(
        self, client: TestClient, curator: User
    ) -> None:
        response = client.get(
            "/api/v1/forms/layouts/museum_object", headers=auth_headers(client, "curator")
        )
        assert response.status_code == 200, response.text
        layout = response.json()

        assert layout["record_type"] == "museum_object"
        assert layout["key_field"] == "accession_number"
        assert [tab["key"] for tab in layout["tabs"]][0] == "identification"
        assert any(portal["key"] == "conservation" for portal in layout["portals"])

    def test_value_lists_come_from_the_database(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        """A period added this morning is in the dropdown this afternoon."""
        layout = client.get(
            "/api/v1/forms/layouts/museum_object", headers=auth_headers(client, "curator")
        ).json()
        options = layout["value_list_options"]

        assert any(
            entry["label"].startswith("ARCH") for entry in options["collection"]
        ), "the collection just created should be selectable"
        assert {entry["value"] for entry in options["acquisition_method"]} >= {
            "excavation",
            "donation",
            "purchase",
        }

    def test_every_field_on_the_layout_exists_on_the_record(
        self, client: TestClient, curator: User
    ) -> None:
        """A layout naming a field the model does not have is a form that
        cannot be saved, and the importer would offer the same dead column."""
        from app.services import forms

        layout = forms.museum_object_layout()
        columns = {column.key for column in MuseumObject.__table__.columns}
        # ``is_public`` comes from a mixin and is on the table too.
        for name in forms.field_index(layout):
            assert name in columns, f"{name} is on the form but not on the record"

    def test_the_flat_field_list_matches_the_layout(
        self, client: TestClient, curator: User
    ) -> None:
        headers = auth_headers(client, "curator")
        layout = client.get("/api/v1/forms/layouts/museum_object", headers=headers).json()
        flat = client.get("/api/v1/forms/layouts/museum_object/fields", headers=headers).json()

        in_layout = {
            field["name"]
            for tab in layout["tabs"]
            for group in tab["groups"]
            for field in group["fields"]
        }
        assert {field["name"] for field in flat} == in_layout

    def test_an_unknown_layout_says_what_is_available(
        self, client: TestClient, curator: User
    ) -> None:
        response = client.get(
            "/api/v1/forms/layouts/spaceship", headers=auth_headers(client, "curator")
        )
        assert response.status_code == 404
        assert "museum_object" in response.json()["detail"]


# --------------------------------------------------------------------------
# Module permissions
# --------------------------------------------------------------------------
class TestMuseumPermissions:
    def test_archaeology_access_alone_does_not_open_the_collection(
        self, client: TestClient, db: Session, curator: User, collection: dict
    ) -> None:
        """The separation the module model exists for."""
        make_user(db, email="fielder@example.org", username="fielder", role=UserRole.RESEARCHER)
        response = catalogue(client, collection["id"], identifier="fielder")
        assert response.status_code == 403

    def test_a_contributor_may_catalogue_but_not_configure(
        self, client: TestClient, cataloguer: User, curator: User, collection: dict
    ) -> None:
        assert catalogue(client, collection["id"], identifier="cataloguer").status_code == 201

        response = client.patch(
            f"/api/v1/museum/collections/{collection['id']}",
            json={"accession_pattern": "{seq}"},
            headers=auth_headers(client, "cataloguer"),
        )
        assert response.status_code == 403

    def test_a_contributor_cannot_edit_a_colleagues_record(
        self, client: TestClient, cataloguer: User, curator: User, collection: dict
    ) -> None:
        obj = catalogue(client, collection["id"], identifier="curator").json()

        response = client.patch(
            f"/api/v1/museum/objects/{obj['id']}",
            json={"title": "Mine now"},
            headers=auth_headers(client, "cataloguer"),
        )
        assert response.status_code == 403

    def test_a_contributors_own_record_is_theirs_to_correct(
        self, client: TestClient, cataloguer: User, curator: User, collection: dict
    ) -> None:
        obj = catalogue(client, collection["id"], identifier="cataloguer").json()

        response = client.patch(
            f"/api/v1/museum/objects/{obj['id']}",
            json={"title": "Corrected"},
            headers=auth_headers(client, "cataloguer"),
        )
        assert response.status_code == 200

    def test_deleting_needs_a_supervisor(
        self, client: TestClient, cataloguer: User, curator: User, collection: dict
    ) -> None:
        obj = catalogue(client, collection["id"], identifier="cataloguer").json()

        assert (
            client.delete(
                f"/api/v1/museum/objects/{obj['id']}", headers=auth_headers(client, "cataloguer")
            ).status_code
            == 403
        )
        assert (
            client.delete(
                f"/api/v1/museum/objects/{obj['id']}", headers=auth_headers(client, "curator")
            ).status_code
            == 200
        )

    def test_the_public_sees_only_published_objects(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        public = catalogue(client, collection["id"], title="On the website", is_public=True).json()
        private = catalogue(client, collection["id"], title="In the store").json()

        listing = client.get("/api/v1/museum/objects").json()
        titles = {item["title"] for item in listing["items"]}
        assert "On the website" in titles
        assert "In the store" not in titles
        assert client.get(f"/api/v1/museum/objects/{private['id']}").status_code == 404
        assert client.get(f"/api/v1/museum/objects/{public['id']}").status_code == 200


def test_an_object_catalogued_into_a_location_starts_its_movement_register(
    client: TestClient, db: Session, curator: User, collection: dict
) -> None:
    """The register should begin where the object did, not at its first move."""
    make_user(db, email="keeper3@example.org", username="keeper3", role=UserRole.RESEARCHER)
    shelf = client.post(
        "/api/v1/storage/locations",
        json={"kind": "shelf", "name": "Shelf A", "code": "A"},
        headers=auth_headers(client, "keeper3"),
    ).json()

    obj = catalogue(client, collection["id"], storage_location_id=shelf["id"]).json()

    from app.models.enums import ResourceType
    from app.services import storage_locations as tree

    history = tree.history(db, ResourceType.MUSEUM_OBJECT, __import__("uuid").UUID(obj["id"]))
    assert len(history) == 1
    assert history[0].reason.value == "accession"
    assert history[0].to_path.endswith("Shelf A")


class TestObjectsInTheStore:
    """A museum object lives in the same store as a find and moves the same way.

    This was silently untrue for a while: the object's own catalogue card
    advertises a location history, but museum objects were never registered as
    storable, so every one of those requests answered 404 and no object could
    be moved at all.
    """

    @pytest.fixture
    def shelf(self, client: TestClient, db: Session) -> dict:
        make_user(db, email="keeper4@example.org", username="keeper4", role=UserRole.RESEARCHER)
        return client.post(
            "/api/v1/storage/locations",
            json={"kind": "shelf", "name": "Shelf C", "code": "C"},
            headers=auth_headers(client, "keeper4"),
        ).json()

    def test_an_object_can_be_moved_through_the_register(
        self, client: TestClient, curator: User, collection: dict, shelf: dict
    ) -> None:
        obj = catalogue(client, collection["id"]).json()

        moved = client.post(
            f"/api/v1/storage/museum_objects/{obj['id']}/move",
            json={"to_location_id": shelf["id"], "reason": "accession"},
            headers=auth_headers(client, "curator"),
        )
        assert moved.status_code == 201, moved.text
        assert moved.json()["to_path"].endswith("Shelf C")

        history = client.get(
            f"/api/v1/storage/museum_objects/{obj['id']}/movements",
            headers=auth_headers(client, "curator"),
        )
        assert history.status_code == 200
        assert len(history.json()) == 1

    def test_the_location_history_the_catalogue_card_promises_resolves(
        self, client: TestClient, curator: User, collection: dict, shelf: dict
    ) -> None:
        """The form layout names this endpoint; it must be a real one."""
        layout = client.get("/api/v1/forms/layouts/museum_object").json()
        portal = next(p for p in layout["portals"] if p["key"] == "movements")

        obj = catalogue(client, collection["id"], storage_location_id=shelf["id"]).json()
        url = portal["endpoint"].replace("{id}", obj["id"])

        response = client.get(url, headers=auth_headers(client, "curator"))
        assert response.status_code == 200, response.text
        assert response.json()[0]["to_path"].endswith("Shelf C")

    def test_a_locations_contents_span_finds_and_objects(
        self, client: TestClient, curator: User, collection: dict, shelf: dict
    ) -> None:
        catalogue(client, collection["id"], storage_location_id=shelf["id"], title="Storage jar")

        contents = client.get(
            f"/api/v1/storage/locations/{shelf['id']}/contents",
            headers=auth_headers(client, "curator"),
        )
        assert contents.status_code == 200, contents.text
        items = contents.json()["items"]
        assert [item["kind"] for item in items] == ["museum_objects"]
        assert items[0]["label"] == "Storage jar"

    def test_moving_an_object_needs_museum_access_not_archaeology(
        self, client: TestClient, db: Session, curator: User, collection: dict, shelf: dict
    ) -> None:
        """The find policy would ask which project team the user is on, which
        answers nothing about a museum object."""
        obj = catalogue(client, collection["id"]).json()
        make_user(
            db,
            email="fielder@example.org",
            username="fielder",
            role=UserRole.RESEARCHER,  # senior in archaeology, nothing in the museum
        )

        refused = client.post(
            f"/api/v1/storage/museum_objects/{obj['id']}/move",
            json={"to_location_id": shelf["id"], "reason": "accession"},
            headers=auth_headers(client, "fielder"),
        )
        assert refused.status_code == 403


class TestObjectLabels:
    """An object's label, which the catalogue card offers to print.

    Museum objects carry a ``public_token`` like every other labelled record,
    but were not registered as labellable — so the card's "Print label" panel
    pointed at a route that answered 404 for every object in the collection.
    """

    def test_an_object_has_a_printable_qr_code(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        obj = catalogue(client, collection["id"]).json()

        response = client.get(
            f"/api/v1/museum/objects/{obj['id']}/qr.png",
            headers=auth_headers(client, "curator"),
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "image/png"
        assert response.content.startswith(b"\x89PNG\r\n\x1a\n")

    def test_the_code_encodes_the_objects_own_address(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        """A label that opens the wrong record is worse than no label."""
        cv2 = pytest.importorskip("cv2", reason="opencv-python-headless is a dev-only dependency")
        numpy = pytest.importorskip("numpy")
        from PIL import Image

        obj = catalogue(client, collection["id"]).json()
        detail = client.get(
            f"/api/v1/museum/objects/{obj['id']}", headers=auth_headers(client, "curator")
        ).json()

        png = client.get(
            f"/api/v1/museum/objects/{obj['id']}/qr.png?size=12",
            headers=auth_headers(client, "curator"),
        ).content

        image = Image.open(io.BytesIO(png)).convert("L")
        if min(image.size) < 600:
            factor = -(-600 // min(image.size))
            image = image.resize(
                (image.width * factor, image.height * factor), Image.Resampling.NEAREST
            )
        decoded, *_ = cv2.QRCodeDetector().detectAndDecode(numpy.array(image))

        assert decoded.endswith(f"/o/{detail['public_token']}")

    def test_a_scanned_label_resolves_to_the_object(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        obj = catalogue(client, collection["id"], title="Oil lamp").json()
        detail = client.get(
            f"/api/v1/museum/objects/{obj['id']}", headers=auth_headers(client, "curator")
        ).json()

        response = client.get(
            f"/api/v1/scan/museum-objects/{detail['public_token']}",
            headers=auth_headers(client, "curator"),
        )
        assert response.status_code == 200, response.text
        assert response.json()["id"] == obj["id"]

    def test_a_scan_reveals_nothing_the_scanner_could_not_already_see(
        self, client: TestClient, db: Session, curator: User, collection: dict
    ) -> None:
        """Scanning a label found in a corridor must not be a way in."""
        obj = catalogue(client, collection["id"]).json()
        detail = client.get(
            f"/api/v1/museum/objects/{obj['id']}", headers=auth_headers(client, "curator")
        ).json()

        assert (
            client.get(f"/api/v1/scan/museum-objects/{detail['public_token']}").status_code == 404
        )


class TestGridEndpoint:
    """The whole-record search behind the spreadsheet view."""

    def test_it_carries_the_fields_the_summary_leaves_out(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        """The grid lets a cataloguer put any field on screen as a column.
        Served from the summary, a field the summary omits would come back
        absent and be drawn as an empty cell — indistinguishable from a field
        nobody has filled in."""
        catalogue(
            client,
            collection["id"],
            title="Fibula",
            maker="Unknown",
            culture="Roman",
            materials=["bronze"],
        )

        row = client.get(
            "/api/v1/museum/objects/grid", headers=auth_headers(client, "curator")
        ).json()["items"][0]

        assert row["maker"] == "Unknown"
        assert row["culture"] == "Roman"
        assert row["materials"] == ["bronze"]

    def test_it_is_not_read_as_an_object_id(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        """`/objects/grid` and `/objects/{id}` share a prefix."""
        response = client.get(
            "/api/v1/museum/objects/grid", headers=auth_headers(client, "curator")
        )

        assert response.status_code == 200, response.text
        assert "items" in response.json()

    def test_it_filters_the_same_way_the_list_does(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        """Both run the same search. Two catalogues that disagree about what a
        filter means is two catalogues."""
        catalogue(client, collection["id"], title="Bronze fibula", culture="Roman")
        catalogue(client, collection["id"], title="Cooking pot", culture="Nabataean")

        headers = auth_headers(client, "curator")
        listed = client.get("/api/v1/museum/objects?q=Nabataean", headers=headers).json()
        gridded = client.get("/api/v1/museum/objects/grid?q=Nabataean", headers=headers).json()

        assert gridded["total"] == listed["total"] == 1
        assert [row["id"] for row in gridded["items"]] == [row["id"] for row in listed["items"]]

    def test_the_export_and_the_grid_agree_about_a_search(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        """Exporting is "give me what I am looking at", which stops being true
        the moment the export runs a narrower search than the screen."""
        catalogue(client, collection["id"], title="Bowl", culture="Nabataean")
        catalogue(client, collection["id"], title="Lamp", culture="Roman")

        headers = auth_headers(client, "curator")
        gridded = client.get("/api/v1/museum/objects/grid?q=Nabataean", headers=headers).json()
        exported = client.get(
            "/api/v1/museum/objects/export.csv?q=Nabataean&columns=title", headers=headers
        ).content.decode("utf-8-sig")

        assert gridded["total"] == 1
        assert "Bowl" in exported
        assert "Lamp" not in exported

    def test_a_row_the_schema_cannot_describe_names_itself(
        self, client: TestClient, curator: User, db: Session, collection: dict
    ) -> None:
        """One bad row must not turn the whole page into "Internal Server Error".

        The grid asks for every field of every record on the page, so it is the
        first screen to meet a record the schema cannot describe. The columns
        the database itself constrains cannot go wrong; the JSON one can, because
        JSONB accepts any JSON document and the schema wants an object. A list
        arrives there from a migration, a script, or a hand-written UPDATE.

        Unguarded, that raises inside the response model and the page fails with
        nothing to act on — no row, no field, and the ninety-nine sound records
        on the page are unreachable too.

        So the row is shown with the unreadable field emptied and *named*. A
        blank cell means "nobody filled this in"; this means something else,
        and the grid has to be able to tell them apart.
        """
        catalogue(client, collection["id"], title="Sound record")
        broken = catalogue(client, collection["id"], title="Broken record").json()

        stored = db.get(MuseumObject, uuid.UUID(broken["id"]))
        assert stored is not None
        stored.metadata_json = ["not", "an", "object"]  # type: ignore[assignment]
        db.flush()

        response = client.get(
            "/api/v1/museum/objects/grid", headers=auth_headers(client, "curator")
        )

        assert response.status_code == 200, response.text
        rows = {row["title"]: row for row in response.json()["items"]}

        # Both records are on the page. The sound one is untouched.
        assert set(rows) == {"Sound record", "Broken record"}
        assert rows["Sound record"]["unreadable_fields"] is None

        # The broken one is readable except for the field that is not, and it
        # says which field that is.
        assert rows["Broken record"]["unreadable_fields"] == ["metadata_json"]
        assert rows["Broken record"]["accession_number"] == stored.accession_number
        assert rows["Broken record"]["metadata_json"] is None


class TestCsvExport:
    """Downloading the catalogue as a spreadsheet.

    The round trip matters more than the download: what comes out should be
    correctable in Excel and importable back through `/imports`, which means
    it has to carry labels a person recognises rather than the identifiers the
    database stores.
    """

    def test_the_export_is_not_swallowed_by_the_object_route(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        """`/objects/export.csv` and `/objects/{id}` share a prefix, and FastAPI
        matches in declaration order — so the literal path has to win."""
        response = client.get(
            "/api/v1/museum/objects/export.csv", headers=auth_headers(client, "curator")
        )

        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")

    def test_excel_on_windows_can_read_the_diacritics(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        """Without a byte-order mark Excel reads UTF-8 as its legacy encoding
        and turns every site name into mojibake — which is most of them."""
        catalogue(client, collection["id"], title="Ḥorvat ʿUza sherd")

        response = client.get(
            "/api/v1/museum/objects/export.csv", headers=auth_headers(client, "curator")
        )

        assert response.content.startswith(b"\xef\xbb\xbf")
        assert "Ḥorvat ʿUza sherd" in response.content.decode("utf-8-sig")

    def test_columns_are_chosen_and_ordered_by_the_caller(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        catalogue(client, collection["id"], title="Cooking pot", object_type="Pot")

        response = client.get(
            "/api/v1/museum/objects/export.csv?columns=title,accession_number",
            headers=auth_headers(client, "curator"),
        )
        header = response.content.decode("utf-8-sig").splitlines()[0]

        assert header == "Object name,Inventory no."

    def test_values_come_out_as_labels_not_identifiers(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        """A column of UUIDs is not a spreadsheet anybody can correct."""
        catalogue(client, collection["id"], title="Bowl")

        response = client.get(
            "/api/v1/museum/objects/export.csv?columns=collection_id,condition",
            headers=auth_headers(client, "curator"),
        )
        rows = response.content.decode("utf-8-sig").splitlines()

        assert "ARCH" in rows[1]
        assert "-" not in rows[1].split(",")[0] or "ARCH" in rows[1]

    def test_a_list_field_is_readable_and_re_importable(
        self, client: TestClient, curator: User, collection: dict
    ) -> None:
        """`bronze; iron` is what the importer splits back apart."""
        catalogue(client, collection["id"], title="Fibula", materials=["bronze", "iron"])

        response = client.get(
            "/api/v1/museum/objects/export.csv?columns=materials",
            headers=auth_headers(client, "curator"),
        )

        assert "bronze; iron" in response.content.decode("utf-8-sig")

    def test_a_list_of_identifiers_comes_out_as_names(
        self, client: TestClient, db: Session, curator: User, collection: dict
    ) -> None:
        """The obvious implementation joins the list first and resolves after,
        which leaves a materials column full of UUIDs — readable to nobody and
        correctable by nobody."""
        bronze = Material(name="Bronze", slug="bronze-x")
        bone = Material(name="Bone", slug="bone-x")
        db.add_all([bronze, bone])
        db.commit()

        catalogue(
            client,
            collection["id"],
            title="Fibula",
            materials=[str(bronze.id), str(bone.id)],
        )

        response = client.get(
            "/api/v1/museum/objects/export.csv?columns=materials",
            headers=auth_headers(client, "curator"),
        )
        body = response.content.decode("utf-8-sig")

        assert "Bronze; Bone" in body
        assert str(bronze.id) not in body

    def test_the_export_shows_only_what_the_caller_may_read(
        self, client: TestClient, db: Session, curator: User, collection: dict
    ) -> None:
        catalogue(client, collection["id"], title="In the store")
        catalogue(client, collection["id"], title="On the website", is_public=True)

        body = client.get("/api/v1/museum/objects/export.csv").content.decode("utf-8-sig")

        assert "On the website" in body
        assert "In the store" not in body
