"""Fields an institution adds to the platform's forms.

The point of this feature is that one description of a form drives four
things — the record card, the edit form, the spreadsheet importer's column
list and the register — so most of what is worth testing is not "can a row be
written" but "does the field turn up in all four, and does its value survive a
round trip through a record that has no column for it".

The rest hold the two lines that would be expensive to lose: a custom field
cannot shadow a platform field, and removing one does not remove what was
recorded under it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User, UserRole
from tests.conftest import auth_headers, make_user


@pytest.fixture
def director(db: Session) -> User:
    return make_user(db, email="dir@example.org", username="dir", role=UserRole.ADMIN)


@pytest.fixture
def digger(db: Session) -> User:
    """Someone who records, and does not decide what is recorded."""
    return make_user(db, email="dig@example.org", username="dig", role=UserRole.RESEARCHER)


def add(client: TestClient, **payload) -> dict:
    response = client.post(
        "/api/v1/custom-fields",
        json={"record_type": "site", **payload},
        headers=auth_headers(client, "dir"),
    )
    assert response.status_code == 201, response.text
    return response.json()


def a_site(client: TestClient, **extra) -> dict:
    project = client.post(
        "/api/v1/projects",
        json={"name": "Tell el-Demo", "code": "TED"},
        headers=auth_headers(client, "dir"),
    ).json()
    response = client.post(
        "/api/v1/sites",
        json={"name": "North trench", "code": "TED-A", "project_id": project["id"], **extra},
        headers=auth_headers(client, "dir"),
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestDefining:
    def test_the_storage_name_is_derived_from_the_label(
        self, client: TestClient, director: User
    ) -> None:
        field = add(client, label="Ministry file no.")
        assert field["name"] == "ministry_file_no"
        assert field["label"] == "Ministry file no."

    def test_a_name_can_be_given_when_it_must_match_a_spreadsheet(
        self, client: TestClient, director: User
    ) -> None:
        field = add(client, label="Ministry file", name="MOA Ref")
        assert field["name"] == "moa_ref"

    def test_a_custom_field_cannot_shadow_a_platform_field(
        self, client: TestClient, director: User
    ) -> None:
        # `description` is on the site form already. Two fields with one name
        # means one of them is never the one somebody typed into.
        response = client.post(
            "/api/v1/custom-fields",
            json={"record_type": "site", "label": "Description"},
            headers=auth_headers(client, "dir"),
        )
        assert response.status_code == 409
        assert "already a field" in response.json()["detail"]

    def test_two_custom_fields_cannot_share_a_name(
        self, client: TestClient, director: User
    ) -> None:
        add(client, label="Ministry file no.")
        response = client.post(
            "/api/v1/custom-fields",
            json={"record_type": "site", "label": "ministry file no"},
            headers=auth_headers(client, "dir"),
        )
        assert response.status_code == 409

    def test_the_same_name_on_a_different_form_is_fine(
        self, client: TestClient, director: User
    ) -> None:
        add(client, label="Ministry file no.")
        second = client.post(
            "/api/v1/custom-fields",
            json={"record_type": "artifact", "label": "Ministry file no."},
            headers=auth_headers(client, "dir"),
        )
        assert second.status_code == 201

    def test_a_dropdown_needs_something_to_offer(
        self, client: TestClient, director: User
    ) -> None:
        response = client.post(
            "/api/v1/custom-fields",
            json={"record_type": "site", "label": "Guarding", "kind": "select"},
            headers=auth_headers(client, "dir"),
        )
        assert response.status_code == 422

    def test_a_reference_is_not_offered(self, client: TestClient, director: User) -> None:
        # Nothing enforces a foreign key inside a JSON blob, so offering one
        # would promise an integrity the storage cannot keep.
        response = client.post(
            "/api/v1/custom-fields",
            json={"record_type": "site", "label": "Dug by", "kind": "reference"},
            headers=auth_headers(client, "dir"),
        )
        assert response.status_code == 422

    def test_an_unknown_form_is_named_rather_than_accepted(
        self, client: TestClient, director: User
    ) -> None:
        response = client.post(
            "/api/v1/custom-fields",
            json={"record_type": "tractor", "label": "Hours"},
            headers=auth_headers(client, "dir"),
        )
        assert response.status_code == 422
        assert "no form called" in response.json()["detail"]

    def test_deciding_what_is_recorded_is_the_administrator_s(
        self, client: TestClient, director: User, digger: User
    ) -> None:
        response = client.post(
            "/api/v1/custom-fields",
            json={"record_type": "site", "label": "Ministry file no."},
            headers=auth_headers(client, "dig"),
        )
        assert response.status_code == 403


class TestOnTheForm:
    def test_the_field_joins_the_layout(self, client: TestClient, director: User) -> None:
        add(client, label="Ministry file no.", help="From the ministry's paperwork.")

        layout = client.get(
            "/api/v1/forms/layouts/site", headers=auth_headers(client, "dir")
        ).json()
        tab = next(tab for tab in layout["tabs"] if tab["key"] == "institution")
        field = tab["groups"][0]["fields"][0]

        assert field["name"] == "ministry_file_no"
        assert field["label"] == "Ministry file no."
        assert field["custom"] is True
        assert field["help"] == "From the ministry's paperwork."

    def test_a_dropdown_carries_its_own_choices(
        self, client: TestClient, director: User
    ) -> None:
        add(client, label="Guarding", kind="select", choices=["Guarded", "Unguarded"])

        layout = client.get(
            "/api/v1/forms/layouts/site", headers=auth_headers(client, "dir")
        ).json()
        field = next(
            field
            for tab in layout["tabs"]
            for group in tab["groups"]
            for field in group["fields"]
            if field["name"] == "guarding"
        )
        # It names a list, its own name, so the client's one lookup path serves
        # both taxonomy lists and an institution's own.
        assert field["value_list"] == "guarding"
        assert layout["value_list_options"]["guarding"] == [
            {"value": "Guarded", "label": "Guarded"},
            {"value": "Unguarded", "label": "Unguarded"},
        ]

    def test_the_raw_json_box_stops_being_an_editor(
        self, client: TestClient, director: User
    ) -> None:
        # Two controls over one value is how a typed correction disappears.
        before = client.get(
            "/api/v1/forms/layouts/site", headers=auth_headers(client, "dir")
        ).json()
        raw = next(
            field
            for tab in before["tabs"]
            for group in tab["groups"]
            for field in group["fields"]
            if field["kind"] == "json"
        )
        assert raw["read_only"] is False

        add(client, label="Ministry file no.")

        after = client.get(
            "/api/v1/forms/layouts/site", headers=auth_headers(client, "dir")
        ).json()
        raw = next(
            field
            for tab in after["tabs"]
            for group in tab["groups"]
            for field in group["fields"]
            if field["kind"] == "json"
        )
        assert raw["read_only"] is True

    def test_a_retired_field_leaves_the_form(self, client: TestClient, director: User) -> None:
        field = add(client, label="Ministry file no.")
        client.delete(f"/api/v1/custom-fields/{field['id']}", headers=auth_headers(client, "dir"))

        layout = client.get(
            "/api/v1/forms/layouts/site", headers=auth_headers(client, "dir")
        ).json()
        assert not any(tab["key"] == "institution" for tab in layout["tabs"])

    def test_the_importer_offers_it_as_a_column(
        self, client: TestClient, director: User, db: Session
    ) -> None:
        add(client, label="Ministry file no.")
        # The importer's column list is built from the same layout, which is
        # the whole return on layouts being data.
        from app.api.v1.endpoints.imports import _available_fields

        names = {item["name"] for item in _available_fields("site", db)}
        assert "ministry_file_no" in names


class TestValues:
    def test_a_value_survives_a_round_trip(self, client: TestClient, director: User) -> None:
        add(client, label="Ministry file no.")
        site = a_site(client, metadata_json={"ministry_file_no": "MOA/2024/117"})

        read = client.get(
            f"/api/v1/sites/{site['id']}", headers=auth_headers(client, "dir")
        ).json()
        assert read["metadata_json"]["ministry_file_no"] == "MOA/2024/117"

    def test_retiring_keeps_what_was_recorded(self, client: TestClient, director: User) -> None:
        field = add(client, label="Ministry file no.")
        site = a_site(client, metadata_json={"ministry_file_no": "MOA/2024/117"})

        removed = client.delete(
            f"/api/v1/custom-fields/{field['id']}", headers=auth_headers(client, "dir")
        )
        assert removed.status_code == 200
        assert "retired" in removed.json()["detail"]

        read = client.get(
            f"/api/v1/sites/{site['id']}", headers=auth_headers(client, "dir")
        ).json()
        assert read["metadata_json"]["ministry_file_no"] == "MOA/2024/117"

    def test_erasing_says_how_many_records_it_touched(
        self, client: TestClient, director: User
    ) -> None:
        field = add(client, label="Ministry file no.")
        site = a_site(client, metadata_json={"ministry_file_no": "MOA/2024/117", "keep": "me"})

        removed = client.delete(
            f"/api/v1/custom-fields/{field['id']}?erase_values=true",
            headers=auth_headers(client, "dir"),
        )
        assert removed.status_code == 200
        assert "1 record" in removed.json()["detail"]

        read = client.get(
            f"/api/v1/sites/{site['id']}", headers=auth_headers(client, "dir")
        ).json()
        # Only the field's own key goes; everything else on the record stays.
        assert "ministry_file_no" not in read["metadata_json"]
        assert read["metadata_json"]["keep"] == "me"

    def test_a_retired_field_is_still_listed_when_asked_for(
        self, client: TestClient, director: User
    ) -> None:
        field = add(client, label="Ministry file no.")
        client.delete(f"/api/v1/custom-fields/{field['id']}", headers=auth_headers(client, "dir"))

        headers = auth_headers(client, "dir")
        assert client.get("/api/v1/custom-fields", headers=headers).json() == []
        listed = client.get(
            "/api/v1/custom-fields", params={"include_retired": True}, headers=headers
        ).json()
        assert [row["name"] for row in listed] == ["ministry_file_no"]

    def test_putting_it_back_restores_the_form(self, client: TestClient, director: User) -> None:
        field = add(client, label="Ministry file no.")
        headers = auth_headers(client, "dir")
        client.delete(f"/api/v1/custom-fields/{field['id']}", headers=headers)
        client.patch(
            f"/api/v1/custom-fields/{field['id']}", json={"is_active": True}, headers=headers
        )

        layout = client.get("/api/v1/forms/layouts/site", headers=headers).json()
        assert any(tab["key"] == "institution" for tab in layout["tabs"])


class TestChanging:
    def test_the_label_changes_and_the_name_does_not(
        self, client: TestClient, director: User
    ) -> None:
        field = add(client, label="Ministry file no.")
        changed = client.patch(
            f"/api/v1/custom-fields/{field['id']}",
            json={"label": "MOA reference", "name": "something_else"},
            headers=auth_headers(client, "dir"),
        ).json()

        assert changed["label"] == "MOA reference"
        # Renaming the key would orphan every value already written under it,
        # so the field simply does not accept one.
        assert changed["name"] == "ministry_file_no"
