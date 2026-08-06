"""The library.

The tests that earn their place are about the two things that decide whether a
reference manager can be adopted at all, and the one thing this one does that a
reference manager cannot.

**A bibliography can come in.** A real ``.bib`` file has nested braces, TeX
accents, ``@string`` definitions, comments and biblatex spellings, and a parser
that only handles the synthetic case fails on every file anybody actually has.

**A bibliography can leave.** A library you cannot export is a library nobody
sensible puts anything into, and the export has to survive a round trip.

**A reference is attached to what it is about, at the pages it is about it.**
"Smith 1987 is about this site" is a bibliography entry; "Smith 1987, 88-91,
describes context 1042" is a finding aid.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Module, ModuleLevel, User, UserRole
from tests.conftest import auth_headers, make_user

BIB = r"""
% Exported by Zotero, and looking like it.

@string{lev = "Levant"}

@comment{this line is not an entry}

@article{smith1987,
  title = {A study of {Nabataean} pottery at {Tell el-Demo}},
  author = {Smith, Jane A. and M{\"u}ller, Hans},
  journal = {Levant},
  volume = {19},
  number = {2},
  pages = {88--91},
  year = {1987},
  doi = {10.1000/xyz},
  keywords = {pottery; Nabataean, survey}
}

@incollection{alqasim2003,
  author = "Dupont, Fran\c{c}ois",
  title = "Grey literature \& the ministry archive",
  booktitle = {Excavations in the {Levant}},
  publisher = {Oxbow},
  address = {Oxford},
  year = 2003
}

@phdthesis{untitled2001, author = {Nobody}, year = {2001} }
"""


@pytest.fixture
def director(db: Session) -> User:
    return make_user(db, email="dir@example.org", username="dir", role=UserRole.ADMIN)


@pytest.fixture
def outsider(db: Session) -> User:
    """No archaeology access at all."""
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
    ).json()
    context = client.post(
        "/api/v1/contexts",
        json={"context_number": "1042", "site_id": site["id"], "context_type": "layer"},
        headers=headers,
    ).json()
    return {"project": project, "site": site, "context": context}


def add(client: TestClient, **fields):
    body = {"title": "A study of Nabataean pottery", "authors": "Smith, J.", "year": 1987, **fields}
    return client.post("/api/v1/library/references", json=body, headers=auth_headers(client, "dir"))


def upload_bib(client: TestClient, text: str = BIB, path: str = "/api/v1/library/import", **params):
    return client.post(
        path,
        files={"file": ("library.bib", text.encode("utf-8"), "text/plain")},
        headers=auth_headers(client, "dir"),
        params=params,
    )


class TestReferences:
    def test_a_reference_is_added_and_reads_as_a_line(
        self, client: TestClient, director: User
    ) -> None:
        body = add(client, journal="Levant", volume="19", pages="88-91").json()
        assert body["title"] == "A study of Nabataean pottery"
        # A label rather than a citation style: implementing Harvard badly
        # produces something that looks like a citation and is wrong.
        assert body["label"].startswith("Smith, J. (1987).")
        assert "Levant 19" in body["label"]

    def test_the_same_doi_twice_is_refused_with_the_first_one_named(
        self, client: TestClient, director: User
    ) -> None:
        add(client, doi="10.1000/xyz")
        again = add(client, title="The same thing under another name", doi="10.1000/xyz")

        assert again.status_code == 409
        assert "A study of Nabataean pottery" in again.json()["detail"]

    def test_searching_covers_the_fields_people_search_by(
        self, client: TestClient, director: User
    ) -> None:
        add(client, title="Nabataean pottery", keywords=["survey"])
        add(client, title="Roman glass", authors="Brown, P.", journal="Levant")

        headers = auth_headers(client, "dir")
        assert client.get("/api/v1/library/references?q=nabataean", headers=headers).json()[
            "total"
        ] == 1
        assert client.get("/api/v1/library/references?q=brown", headers=headers).json()["total"] == 1
        assert client.get("/api/v1/library/references?q=levant", headers=headers).json()["total"] == 1
        assert client.get("/api/v1/library/references?keyword=survey", headers=headers).json()[
            "total"
        ] == 1

    def test_references_with_no_year_sort_last_not_first(
        self, client: TestClient, director: User
    ) -> None:
        """A library sorted by year should not open with the ones that have none."""
        add(client, title="No year at all", year=None)
        add(client, title="Dated", year=1990)

        listed = client.get(
            "/api/v1/library/references?sort=-year", headers=auth_headers(client, "dir")
        ).json()
        assert listed["items"][0]["title"] == "Dated"


class TestFolders:
    def test_a_reference_can_be_in_several_folders(
        self, client: TestClient, director: User
    ) -> None:
        """Forcing a choice is what makes people stop filing things."""
        headers = auth_headers(client, "dir")
        one = client.post(
            "/api/v1/library/collections", json={"name": "Tell el-Demo"}, headers=headers
        ).json()
        two = client.post(
            "/api/v1/library/collections", json={"name": "Nabataean pottery"}, headers=headers
        ).json()

        reference = add(client, collection_ids=[one["id"], two["id"]]).json()
        assert set(reference["collection_ids"]) == {one["id"], two["id"]}

        for folder in (one, two):
            found = client.get(
                f"/api/v1/library/references?collection_id={folder['id']}", headers=headers
            ).json()
            assert found["total"] == 1

    def test_two_folders_with_one_name_in_one_place_are_refused(
        self, client: TestClient, director: User
    ) -> None:
        headers = auth_headers(client, "dir")
        client.post("/api/v1/library/collections", json={"name": "Reports"}, headers=headers)
        again = client.post(
            "/api/v1/library/collections", json={"name": "Reports"}, headers=headers
        )
        assert again.status_code == 409

    def test_removing_a_folder_keeps_its_references(
        self, client: TestClient, director: User
    ) -> None:
        """A folder is a view onto references, not a container of them."""
        headers = auth_headers(client, "dir")
        folder = client.post(
            "/api/v1/library/collections", json={"name": "To read"}, headers=headers
        ).json()
        add(client, collection_ids=[folder["id"]])

        removed = client.delete(f"/api/v1/library/collections/{folder['id']}", headers=headers)
        assert removed.status_code == 200
        assert "still in the library" in removed.json()["detail"]
        assert client.get("/api/v1/library/references", headers=headers).json()["total"] == 1


class TestWhatItIsAbout:
    def test_a_reference_is_attached_to_a_context_at_its_pages(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """The whole reason for building this here rather than using Zotero."""
        headers = auth_headers(client, "dir")
        reference = add(client).json()

        attached = client.post(
            f"/api/v1/library/references/{reference['id']}/links",
            json={
                "context_id": dig["context"]["id"],
                "locator": "88-91",
                "note": "Describes the burnt layer",
            },
            headers=headers,
        )
        assert attached.status_code == 201, attached.text
        body = attached.json()
        assert body["locator"] == "88-91"
        assert body["target_kind"] == "Context"
        assert body["target_label"] == "1042"

    def test_a_record_can_be_asked_what_is_published_about_it(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        headers = auth_headers(client, "dir")
        reference = add(client).json()
        client.post(
            f"/api/v1/library/references/{reference['id']}/links",
            json={"site_id": dig["site"]["id"], "locator": "ch. 4"},
            headers=headers,
        )

        found = client.get(
            f"/api/v1/library/for-record?site_id={dig['site']['id']}", headers=headers
        ).json()
        assert len(found) == 1
        assert found[0]["locator"] == "ch. 4"
        # The reference comes with it, so a site page draws its bibliography in
        # one request rather than one per row.
        assert found[0]["reference"]["title"] == "A study of Nabataean pottery"

    def test_one_record_per_attachment(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """Or "what is this about" has two answers in one row."""
        reference = add(client).json()
        response = client.post(
            f"/api/v1/library/references/{reference['id']}/links",
            json={"site_id": dig["site"]["id"], "context_id": dig["context"]["id"]},
            headers=auth_headers(client, "dir"),
        )
        assert response.status_code == 422

    def test_an_attachment_to_nothing_is_refused(
        self, client: TestClient, director: User
    ) -> None:
        reference = add(client).json()
        response = client.post(
            f"/api/v1/library/references/{reference['id']}/links",
            json={"locator": "88-91"},
            headers=auth_headers(client, "dir"),
        )
        assert response.status_code == 422

    def test_filtering_the_library_by_the_site_it_is_about(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        headers = auth_headers(client, "dir")
        about = add(client, title="About this site").json()
        add(client, title="About something else")
        client.post(
            f"/api/v1/library/references/{about['id']}/links",
            json={"site_id": dig["site"]["id"]},
            headers=headers,
        )

        found = client.get(
            f"/api/v1/library/references?site_id={dig['site']['id']}", headers=headers
        ).json()
        assert [row["title"] for row in found["items"]] == ["About this site"]


class TestBibtex:
    def test_a_real_file_imports(self, client: TestClient, director: User) -> None:
        """Nested braces, TeX accents, @string, @comment, a bare year, biblatex."""
        response = upload_bib(client)
        assert response.status_code == 200, response.text
        # The untitled thesis is dropped: a reference nobody can find again by
        # name is what makes a library unusable.
        assert response.json()["created"] == 2

        listed = client.get(
            "/api/v1/library/references?sort=year", headers=auth_headers(client, "dir")
        ).json()
        first = listed["items"][0]
        assert first["title"] == "A study of Nabataean pottery at Tell el-Demo"
        assert "Müller" in first["authors"]
        assert first["keywords"] == ["pottery", "Nabataean", "survey"]
        assert first["reference_type"] == "article"

        second = listed["items"][1]
        assert "François" in second["authors"]
        assert second["title"] == "Grey literature & the ministry archive"
        assert second["reference_type"] == "chapter"

    def test_importing_the_same_file_twice_adds_nothing(
        self, client: TestClient, director: User
    ) -> None:
        assert upload_bib(client).json()["created"] == 2
        again = upload_bib(client).json()
        assert again["created"] == 0
        assert again["skipped"] == 2

    def test_the_preview_writes_nothing(self, client: TestClient, director: User) -> None:
        preview = upload_bib(client, path="/api/v1/library/import/preview")
        assert preview.status_code == 200, preview.text
        assert preview.json()["new"] == 2

        assert (
            client.get("/api/v1/library/references", headers=auth_headers(client, "dir")).json()[
                "total"
            ]
            == 0
        )

    def test_everything_can_be_filed_into_a_folder_as_it_arrives(
        self, client: TestClient, director: User
    ) -> None:
        headers = auth_headers(client, "dir")
        folder = client.post(
            "/api/v1/library/collections", json={"name": "Imported"}, headers=headers
        ).json()

        result = upload_bib(client, collection_id=folder["id"]).json()
        assert "Imported" in result["detail"]
        assert (
            client.get(
                f"/api/v1/library/references?collection_id={folder['id']}", headers=headers
            ).json()["total"]
            == 2
        )

    def test_a_file_with_nothing_in_it_says_what_an_entry_looks_like(
        self, client: TestClient, director: User
    ) -> None:
        response = upload_bib(client, text="just some notes I typed")
        assert response.status_code == 422
        assert "@article" in response.json()["detail"]

    def test_it_exports_and_the_export_imports_again(
        self, client: TestClient, director: User
    ) -> None:
        """The round trip. A library you cannot get out is one nobody fills."""
        upload_bib(client)

        exported = client.get("/api/v1/library/export.bib", headers=auth_headers(client, "dir"))
        assert exported.status_code == 200
        assert "attachment" in exported.headers["content-disposition"]

        text = exported.content.decode("utf-8")
        assert "@article{smith1987," in text
        # Braced twice, so a style cannot lower-case the site's name.
        assert "{{A study of Nabataean pottery at Tell el-Demo}}" in text
        # And the ampersand is escaped, or LaTeX stops on it.
        assert r"Grey literature \& the ministry archive" in text

        # Re-imported into an empty library, it comes back the same.
        for row in client.get(
            "/api/v1/library/references", headers=auth_headers(client, "dir")
        ).json()["items"]:
            client.delete(
                f"/api/v1/library/references/{row['id']}", headers=auth_headers(client, "dir")
            )

        again = upload_bib(client, text=text)
        assert again.json()["created"] == 2

    def test_the_export_can_be_narrowed_to_one_site(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        headers = auth_headers(client, "dir")
        about = add(client, title="About this site").json()
        add(client, title="Nothing to do with it")
        client.post(
            f"/api/v1/library/references/{about['id']}/links",
            json={"site_id": dig["site"]["id"]},
            headers=headers,
        )

        text = client.get(
            f"/api/v1/library/export.bib?site_id={dig['site']['id']}", headers=headers
        ).content.decode("utf-8")
        assert "About this site" in text
        assert "Nothing to do with it" not in text


class TestPermission:
    def test_reading_needs_the_archaeology_module(
        self, client: TestClient, director: User, outsider: User
    ) -> None:
        add(client)
        assert (
            client.get("/api/v1/library/references", headers=auth_headers(client, "cur")).status_code
            == 403
        )

    def test_it_needs_an_account(self, client: TestClient, director: User) -> None:
        assert client.get("/api/v1/library/references").status_code == 401
