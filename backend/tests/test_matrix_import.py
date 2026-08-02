"""Building a Harris matrix from a spreadsheet.

The test that earns its place is the cycle check. A matrix is acyclic by
definition, and a sheet that says 1001 is above 1002, 1002 above 1003 and 1003
above 1001 describes a sequence that could not have happened — nearly always
two columns the wrong way round. Importing that silently turns a typing
mistake into a published stratigraphy, and nobody finds out until a specialist
tries to phase the site.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User, UserRole
from tests.conftest import auth_headers, make_user


def as_csv(rows: list[list[str]]) -> bytes:
    return "\n".join(",".join(cell for cell in row) for row in rows).encode("utf-8")


def as_xlsx(rows: list[list[str]]) -> bytes:
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Matrix"
    for row in rows:
        sheet.append(row)
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


@pytest.fixture
def director(db: Session) -> User:
    return make_user(db, email="dir@example.org", username="dir", role=UserRole.ADMIN)


@pytest.fixture
def site(client: TestClient, director: User) -> dict:
    """A site with four contexts, and nothing said about their order yet."""
    headers = auth_headers(client, "dir")
    project = client.post(
        "/api/v1/projects", json={"name": "Dig", "code": "DIG-1"}, headers=headers
    ).json()
    site = client.post(
        "/api/v1/sites",
        json={"name": "Trench A", "code": "TA", "project_id": project["id"]},
        headers=headers,
    ).json()
    for number in ("1001", "1002", "1003", "1004"):
        created = client.post(
            "/api/v1/contexts",
            json={"context_number": number, "site_id": site["id"], "context_type": "layer"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
    return site


def upload(client: TestClient, site: dict, data: bytes, *, what: str = "import", name="m.csv"):
    return client.post(
        f"/api/v1/contexts/sites/{site['id']}/stratigraphy/{what}",
        files={"file": (name, data, "text/csv")},
        headers=auth_headers(client, "dir"),
    )


GOOD = [
    ["Context", "Relationship", "Related context"],
    ["1001", "above", "1002"],
    ["1002", "above", "1003"],
    ["1003", "cuts", "1004"],
]


class TestReadingTheSheet:
    def test_a_straightforward_sheet_imports(
        self, client: TestClient, director: User, site: dict
    ) -> None:
        response = upload(client, site, as_csv(GOOD))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["written"] == 3
        assert body["usable"] == 3
        assert body["problems"] == []

    def test_it_reads_xlsx_as_well_as_csv(
        self, client: TestClient, director: User, site: dict
    ) -> None:
        response = upload(client, site, as_xlsx(GOOD), name="matrix.xlsx")
        assert response.status_code == 200, response.text
        assert response.json()["written"] == 3

    def test_the_words_people_actually_write_are_understood(
        self, client: TestClient, director: User, site: dict
    ) -> None:
        """A sheet written for people should not have to be rewritten for a computer."""
        response = upload(
            client,
            site,
            as_csv(
                [
                    ["Context no.", "Relationship", "Related unit"],
                    ["1001", "Overlies", "1002"],
                    ["1002", "Truncated by", "1003"],
                    ["1004", "EARLIER THAN", "1001"],
                ]
            ),
        )
        assert response.status_code == 200, response.text
        assert response.json()["written"] == 3

    def test_both_directions_are_written(
        self, client: TestClient, director: User, site: dict
    ) -> None:
        """Otherwise the matrix reads from one context and not the other."""
        upload(client, site, as_csv([GOOD[0], ["1001", "above", "1002"]]))

        headers = auth_headers(client, "dir")
        contexts = client.get(
            f"/api/v1/contexts?site_id={site['id']}", headers=headers
        ).json()["items"]
        lower = next(row for row in contexts if row["context_number"] == "1002")

        detail = client.get(f"/api/v1/contexts/{lower['id']}", headers=headers).json()
        relations = {item["relation"] for item in detail.get("relationships", [])}
        assert "below" in relations

    def test_a_column_it_cannot_find_is_said_plainly(
        self, client: TestClient, director: User, site: dict
    ) -> None:
        response = upload(
            client,
            site,
            as_csv([["Alpha", "Beta"], ["1001", "1002"]]),
            what="preview",
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["can_apply"] is False
        assert "column" in body["problems"][0]["message"].lower()

    def test_an_unknown_context_is_reported_with_its_row(
        self, client: TestClient, director: User, site: dict
    ) -> None:
        response = upload(
            client,
            site,
            as_csv([GOOD[0], ["1001", "above", "1002"], ["9999", "above", "1001"]]),
            what="preview",
        )
        body = response.json()
        assert body["usable"] == 1
        problem = body["problems"][0]
        # The row number, so somebody can go straight to it in the sheet.
        assert problem["row"] == 3
        assert "9999" in problem["message"]

    def test_a_row_that_relates_a_context_to_itself_is_refused(
        self, client: TestClient, director: User, site: dict
    ) -> None:
        body = upload(
            client, site, as_csv([GOOD[0], ["1001", "above", "1001"]]), what="preview"
        ).json()
        assert body["usable"] == 0
        assert "itself" in body["problems"][0]["message"]

    def test_reimporting_a_corrected_sheet_does_not_duplicate(
        self, client: TestClient, director: User, site: dict
    ) -> None:
        assert upload(client, site, as_csv(GOOD)).json()["written"] == 3
        again = upload(client, site, as_csv(GOOD)).json()
        # The normal way to use this is to fix the sheet and send it again.
        assert again["written"] == 0
        assert again["already_there"] == 3


class TestImpossibleSequences:
    def test_a_loop_stops_the_whole_import(
        self, client: TestClient, director: User, site: dict
    ) -> None:
        response = upload(
            client,
            site,
            as_csv(
                [
                    GOOD[0],
                    ["1001", "above", "1002"],
                    ["1002", "above", "1003"],
                    ["1003", "above", "1001"],
                ]
            ),
        )
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert "cannot exist" in detail
        # The loop itself, so the wrong link can be found rather than hunted.
        assert "1001" in detail and "1003" in detail

    def test_nothing_at_all_is_written_when_it_loops(
        self, client: TestClient, director: User, site: dict
    ) -> None:
        """No partial import. A cycle makes the whole sequence wrong."""
        upload(
            client,
            site,
            as_csv(
                [
                    GOOD[0],
                    ["1001", "above", "1002"],
                    ["1002", "above", "1003"],
                    ["1003", "above", "1001"],
                ]
            ),
        )
        headers = auth_headers(client, "dir")
        contexts = client.get(
            f"/api/v1/contexts?site_id={site['id']}", headers=headers
        ).json()["items"]
        first = next(row for row in contexts if row["context_number"] == "1001")
        detail = client.get(f"/api/v1/contexts/{first['id']}", headers=headers).json()
        assert detail.get("relationships", []) == []

    def test_the_preview_shows_the_loop_before_anything_is_attempted(
        self, client: TestClient, director: User, site: dict
    ) -> None:
        body = upload(
            client,
            site,
            as_csv(
                [
                    GOOD[0],
                    ["1001", "above", "1002"],
                    ["1002", "above", "1001"],
                ]
            ),
            what="preview",
        ).json()
        assert body["can_apply"] is False
        assert len(body["contradictions"]) == 1
        assert body["contradictions"][0][0] == body["contradictions"][0][-1]

    def test_a_loop_closed_against_what_is_already_stored_is_caught(
        self, client: TestClient, director: User, site: dict
    ) -> None:
        """The common case, and the one a sheet-only check would miss.

        Half the matrix is imported already; the new rows close a loop with
        what is in the database rather than within themselves.
        """
        assert (
            upload(
                client,
                site,
                as_csv([GOOD[0], ["1001", "above", "1002"], ["1002", "above", "1003"]]),
            ).status_code
            == 200
        )

        response = upload(client, site, as_csv([GOOD[0], ["1003", "above", "1001"]]))
        assert response.status_code == 422
        assert "cannot exist" in response.json()["detail"]

    def test_below_is_read_as_the_same_statement_as_above(
        self, client: TestClient, director: User, site: dict
    ) -> None:
        """1002 below 1001 says exactly what 1001 above 1002 says.

        The cycle check has to see one consistent direction, or half the loops
        in a real sheet slip through because they were written the other way
        up.
        """
        response = upload(
            client,
            site,
            as_csv(
                [
                    GOOD[0],
                    ["1001", "above", "1002"],
                    ["1003", "below", "1002"],
                    ["1003", "above", "1001"],
                ]
            ),
        )
        assert response.status_code == 422, response.text

    def test_contemporary_relations_do_not_count_as_a_loop(
        self, client: TestClient, director: User, site: dict
    ) -> None:
        """"Same as" both ways is a statement, not a contradiction."""
        response = upload(
            client,
            site,
            as_csv(
                [
                    GOOD[0],
                    ["1001", "same as", "1002"],
                    ["1002", "same as", "1001"],
                    ["1003", "contemporary with", "1004"],
                ]
            ),
        )
        assert response.status_code == 200, response.text


class TestPermission:
    def test_somebody_who_cannot_edit_the_site_cannot_rewrite_its_matrix(
        self, client: TestClient, director: User, db: Session, site: dict
    ) -> None:
        # Public, so the refusal is about editing rather than about seeing.
        # A site they cannot see gives a 404, and rightly — its existence is
        # itself the thing being withheld.
        client.patch(
            f"/api/v1/sites/{site['id']}",
            json={"is_public": True},
            headers=auth_headers(client, "dir"),
        )
        make_user(db, email="stu@example.org", username="stu", role=UserRole.STUDENT)
        response = client.post(
            f"/api/v1/contexts/sites/{site['id']}/stratigraphy/import",
            files={"file": ("m.csv", as_csv(GOOD), "text/csv")},
            headers=auth_headers(client, "stu"),
        )
        assert response.status_code == 403

    def test_a_site_they_cannot_even_see_gives_a_404(
        self, client: TestClient, director: User, db: Session, site: dict
    ) -> None:
        make_user(db, email="stu2@example.org", username="stu2", role=UserRole.STUDENT)
        response = client.post(
            f"/api/v1/contexts/sites/{site['id']}/stratigraphy/import",
            files={"file": ("m.csv", as_csv(GOOD), "text/csv")},
            headers=auth_headers(client, "stu2"),
        )
        # Not a 403, which would confirm the site exists.
        assert response.status_code == 404

    def test_it_needs_an_account(self, client: TestClient, director: User, site: dict) -> None:
        response = client.post(
            f"/api/v1/contexts/sites/{site['id']}/stratigraphy/import",
            files={"file": ("m.csv", as_csv(GOOD), "text/csv")},
        )
        assert response.status_code == 401
