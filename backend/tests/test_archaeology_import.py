"""Importing an excavation from the spreadsheets it is already in.

Until now a museum could migrate off its spreadsheets and an excavation could
not, because the importer builds its column mapping from a form layout and
there were no layouts for sites, contexts or finds.

Three properties are worth defending, and they are the ones that decide whether
a real season's records can be loaded at all.

**A register names its context by number.** "1042", not a UUID — and a context
number is only unique within a site, so it cannot be a value list the way Period
is. Resolving it wrongly attaches a find to another site's context, which is the
one mistake in this file that produces a plausible-looking record that is false.

**The permission is the destination module's.** A museum supervisor with no
archaeology access must not be able to write four thousand contexts into a dig.
The obvious implementation — one ``require_module`` on the router — gets this
wrong, and gets it wrong silently.

**The headings people actually write are understood.** A register that says
"Locus", "SU", "Basket no." or "Ctx" should not have to be rewritten before it
can be read.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Module, ModuleLevel, User, UserRole
from tests.conftest import auth_headers, make_user


def as_csv(rows: list[list[str]]) -> bytes:
    return "\n".join(",".join(cell for cell in row) for row in rows).encode("utf-8")


def as_xlsx(rows: list[list[str]]) -> bytes:
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


@pytest.fixture
def director(db: Session) -> User:
    return make_user(db, email="dir@example.org", username="dir", role=UserRole.ADMIN)


@pytest.fixture
def curator(db: Session) -> User:
    """Senior in the museum, absent from archaeology. The interesting case."""
    return make_user(
        db,
        email="cur@example.org",
        username="cur",
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
        json={"name": "Tell el-Demo", "code": "TED-A", "project_id": project["id"]},
        headers=headers,
    )
    assert site.status_code == 201, site.text
    return {"project": project, "site": site.json()}


def upload(
    client: TestClient,
    data: bytes,
    record_type: str,
    *,
    identifier: str = "dir",
    name: str = "sheet.csv",
):
    return client.post(
        "/api/v1/imports",
        files={"file": (name, data, "text/csv")},
        data={"record_type": record_type},
        headers=auth_headers(client, identifier),
    )


def run(client: TestClient, batch_id: str, *, defaults: dict | None = None, identifier="dir"):
    """Set any defaults, then commit. Returns the commit body."""
    headers = auth_headers(client, identifier)
    if defaults:
        patched = client.patch(
            f"/api/v1/imports/{batch_id}", json={"defaults": defaults}, headers=headers
        )
        assert patched.status_code == 200, patched.text
    return client.post(f"/api/v1/imports/{batch_id}/commit", headers=headers)


CONTEXTS = [
    ["Context no.", "Type", "Trench", "Munsell", "Description"],
    ["1001", "layer", "A", "10YR 5/3", "Topsoil"],
    ["1002", "layer", "A", "10YR 4/2", "Occupation deposit"],
    ["1003", "cut", "A", "", "Pit cut"],
]


class TestSites:
    def test_a_sheet_of_sites_imports(self, client: TestClient, director: User, dig: dict) -> None:
        batch = upload(
            client,
            as_csv(
                [
                    ["Site code", "Site name", "Country", "Latitude", "Longitude"],
                    ["TED-B", "Tell el-Demo North", "Jordan", "31.9", "35.9"],
                    ["TED-C", "Tell el-Demo South", "Jordan", "31.8", "35.8"],
                ]
            ),
            "site",
        )
        assert batch.status_code == 201, batch.text

        committed = run(client, batch.json()["id"], defaults={"project_id": dig["project"]["id"]})
        assert committed.status_code == 200, committed.text
        assert committed.json()["valid_rows"] == 2

        sites = client.get("/api/v1/sites?limit=50", headers=auth_headers(client, "dir")).json()
        codes = {row["code"] for row in sites["items"]}
        assert {"TED-B", "TED-C"} <= codes

    def test_without_a_project_it_says_so_and_says_how(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """A sheet of sites never says which project. Whoever made it knew."""
        batch = upload(
            client, as_csv([["Site code", "Site name"], ["TED-D", "North slope"]]), "site"
        )
        committed = run(client, batch.json()["id"])

        assert committed.status_code == 200
        body = committed.json()
        assert body["valid_rows"] == 0 or body["rows"][0]["errors"]
        message = " ".join(body["rows"][0]["errors"])
        assert "project" in message.lower()
        # Both ways of supplying it, or the answer to "no project" is a shrug:
        # a sheet of sites almost never names its project, and being told only
        # "map a column" leaves somebody adding a column of one repeated value.
        assert "map a column" in message.lower()
        assert "every row" in message.lower()


class TestContexts:
    def test_a_context_sheet_imports(self, client: TestClient, director: User, dig: dict) -> None:
        batch = upload(client, as_csv(CONTEXTS), "excavation_context")
        assert batch.status_code == 201, batch.text

        committed = run(client, batch.json()["id"], defaults={"site_id": dig["site"]["id"]})
        assert committed.status_code == 200, committed.text
        assert committed.json()["valid_rows"] == 3

        listed = client.get(
            f"/api/v1/contexts?site_id={dig['site']['id']}", headers=auth_headers(client, "dir")
        ).json()
        numbers = {row["context_number"] for row in listed["items"]}
        assert numbers == {"1001", "1002", "1003"}

    def test_the_headings_people_actually_write_are_understood(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """ "Locus" and "SU" are the same column as "Context no." on most digs."""
        batch = upload(
            client,
            as_csv(
                [
                    ["Locus", "Locus type", "Stratum", "Soil", "Colour"],
                    ["2001", "fill", "III", "silty clay", "7.5YR 4/4"],
                ]
            ),
            "excavation_context",
        )
        assert batch.status_code == 201, batch.text

        mapping = batch.json()["mapping"]
        assert mapping["Locus"] == "context_number"
        assert mapping["Locus type"] == "context_type"
        assert mapping["Stratum"] == "stratigraphic_unit"
        assert mapping["Soil"] == "composition"
        assert mapping["Colour"] == "munsell_color"

    def test_it_reads_xlsx_too(self, client: TestClient, director: User, dig: dict) -> None:
        batch = upload(client, as_xlsx(CONTEXTS), "excavation_context", name="contexts.xlsx")
        assert batch.status_code == 201, batch.text
        committed = run(client, batch.json()["id"], defaults={"site_id": dig["site"]["id"]})
        assert committed.json()["valid_rows"] == 3


class TestFinds:
    @pytest.fixture
    def contexts(self, client: TestClient, director: User, dig: dict) -> dict:
        batch = upload(client, as_csv(CONTEXTS), "excavation_context")
        run(client, batch.json()["id"], defaults={"site_id": dig["site"]["id"]})
        return dig

    def test_a_finds_register_imports_and_finds_its_contexts(
        self, client: TestClient, director: User, contexts: dict
    ) -> None:
        """The property this whole file exists for.

        A register names its context by number. Resolving that wrongly attaches
        the find to another site's context — a record that looks entirely
        plausible and is false.
        """
        batch = upload(
            client,
            as_csv(
                [
                    ["Find no.", "Object name", "Locus", "Ware", "Count", "Weight"],
                    ["TED-1", "Rim sherd", "1001", "Cooking pot", "3", "142"],
                    ["TED-2", "Body sherd", "1002", "Storage jar", "1", "55"],
                ]
            ),
            "artifact",
        )
        assert batch.status_code == 201, batch.text

        committed = run(client, batch.json()["id"], defaults={"site_id": contexts["site"]["id"]})
        assert committed.status_code == 200, committed.text
        assert committed.json()["valid_rows"] == 2

        headers = auth_headers(client, "dir")
        finds = client.get(
            f"/api/v1/artifacts?site_id={contexts['site']['id']}", headers=headers
        ).json()["items"]
        assert {row["inventory_number"] for row in finds} == {"TED-1", "TED-2"}

        first = next(row for row in finds if row["inventory_number"] == "TED-1")
        detail = client.get(f"/api/v1/artifacts/{first['id']}", headers=headers).json()
        assert detail["context_id"] is not None
        # …and it is *that* context, not merely some context.
        context = client.get(f"/api/v1/contexts/{detail['context_id']}", headers=headers).json()
        assert context["context_number"] == "1001"

    def test_a_context_that_does_not_exist_names_itself(
        self, client: TestClient, director: User, contexts: dict
    ) -> None:
        """Rather than attaching the find to nothing and saying it worked."""
        batch = upload(
            client,
            as_csv([["Find no.", "Locus"], ["TED-9", "9999"]]),
            "artifact",
        )
        committed = run(client, batch.json()["id"], defaults={"site_id": contexts["site"]["id"]})

        errors = " ".join(committed.json()["rows"][0]["errors"])
        assert "9999" in errors
        assert contexts["site"]["code"] in errors

    def test_a_find_with_no_context_still_imports(
        self, client: TestClient, director: User, contexts: dict
    ) -> None:
        """Surface finds and museum backlog have none, and are still finds."""
        batch = upload(
            client, as_csv([["Find no.", "Object name"], ["TED-8", "Loom weight"]]), "artifact"
        )
        committed = run(client, batch.json()["id"], defaults={"site_id": contexts["site"]["id"]})
        assert committed.json()["valid_rows"] == 1


class TestPermission:
    def test_a_museum_supervisor_cannot_import_an_excavation(
        self, client: TestClient, curator: User, dig: dict
    ) -> None:
        """The one an obvious implementation gets wrong, and gets wrong silently.

        A single ``require_module(Module.MUSEUM, SUPERVISOR)`` on the router
        would let this through, because the caller genuinely is a museum
        supervisor. The module that decides is the one being written into.
        """
        response = upload(client, as_csv(CONTEXTS), "excavation_context", identifier="cur")
        assert response.status_code == 403
        assert "archaeology" in response.json()["detail"].lower()

    def test_and_may_still_import_a_catalogue(self, client: TestClient, curator: User) -> None:
        response = upload(
            client,
            as_csv([["Inventory no.", "Object name"], ["X.1", "Bowl"]]),
            "museum_object",
            identifier="cur",
        )
        assert response.status_code == 201, response.text

    def test_an_unknown_record_type_lists_what_is_available(
        self, client: TestClient, director: User
    ) -> None:
        response = upload(client, as_csv([["A"], ["1"]]), "pottery_analysis")
        assert response.status_code == 422
        assert "artifact" in response.json()["detail"]


class TestUndo:
    def test_an_import_of_contexts_can_be_undone(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """The revert path was written against museum objects only, so this is
        the test that it now deletes what it created rather than nothing."""
        batch = upload(client, as_csv(CONTEXTS), "excavation_context")
        batch_id = batch.json()["id"]
        run(client, batch_id, defaults={"site_id": dig["site"]["id"]})

        headers = auth_headers(client, "dir")
        reverted = client.delete(f"/api/v1/imports/{batch_id}/records", headers=headers)
        assert reverted.status_code == 200, reverted.text
        assert "3 records deleted" in reverted.json()["detail"]

        listed = client.get(f"/api/v1/contexts?site_id={dig['site']['id']}", headers=headers).json()
        assert listed["total"] == 0
