"""The sheet room, the deliveries, and the folder on the disk.

Three features that share one idea: a file has to be reachable by somebody who
is not sitting in front of the platform. A spreadsheet kept as a document, a
bundle sent to a person with no account, and the whole archive written out as
named folders are the same requirement at three sizes.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Module, ModuleLevel, User, UserRole
from tests.conftest import auth_headers, make_user


@pytest.fixture
def director(db: Session) -> User:
    return make_user(db, email="dir@example.org", username="dir", role=UserRole.ADMIN)


@pytest.fixture
def onlooker(db: Session) -> User:
    """Can read the archaeology module and not export from it."""
    return make_user(
        db,
        email="look@example.org",
        username="look",
        role=UserRole.VISITOR,
        modules={Module.ARCHAEOLOGY: ModuleLevel.VIEWER},
        grant_defaults=False,
    )


def workbook(rows: list[list[object]]) -> bytes:
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def png() -> bytes:
    pillow = pytest.importorskip("PIL.Image")
    buffer = io.BytesIO()
    pillow.new("RGB", (40, 30), (120, 90, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


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


def import_a_register(client: TestClient, dig: dict) -> dict:
    """Upload and commit a small finds register, returning the batch."""
    headers = auth_headers(client, "dir")
    data = workbook(
        [
            ["Inventory no.", "Object type", "Trench"],
            ["TED-2024-001", "Jar rim", "A"],
            ["TED-2024-002", "Loom weight", "A"],
        ]
    )
    created = client.post(
        "/api/v1/imports",
        files={"file": ("finds-register.xlsx", data, "application/vnd.ms-excel")},
        data={"record_type": "artifact"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    batch = created.json()

    client.patch(
        f"/api/v1/imports/{batch['id']}",
        json={
            "mapping": {
                "Inventory no.": "inventory_number",
                "Object type": "object_type",
                "Trench": "trench",
            },
            "defaults": {"site_id": dig["site"]["id"]},
        },
        headers=headers,
    )
    committed = client.post(f"/api/v1/imports/{batch['id']}/commit", json={}, headers=headers)
    assert committed.status_code == 200, committed.text
    return client.get(f"/api/v1/imports/{batch['id']}", headers=headers).json()


class TestTheRoom:
    def test_a_sheet_that_has_been_imported_says_so(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        import_a_register(client, dig)
        room = client.get("/api/v1/imports", headers=auth_headers(client, "dir")).json()
        assert room["items"][0]["state"] == "imported"
        assert room["items"][0]["owner_label"] == "Dir"

    def test_the_original_comes_back_byte_for_byte(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """It is evidence. What was received, before anybody mapped a column."""
        batch = import_a_register(client, dig)
        response = client.get(
            f"/api/v1/imports/{batch['id']}/original", headers=auth_headers(client, "dir")
        )
        assert response.status_code == 200
        assert response.content[:2] == b"PK"  # an xlsx is a zip
        assert "finds-register.xlsx" in response.headers["content-disposition"]

    def test_archiving_takes_it_out_of_the_working_list(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        batch = import_a_register(client, dig)
        headers = auth_headers(client, "dir")
        client.patch(
            f"/api/v1/imports/{batch['id']}/shelf", json={"is_archived": True}, headers=headers
        )

        assert client.get("/api/v1/imports", headers=headers).json()["total"] == 0
        put_away = client.get(
            "/api/v1/imports", params={"include_archived": True}, headers=headers
        ).json()
        assert put_away["items"][0]["state"] == "archived"

        # And the file is still there, which is the whole difference between
        # archiving and deleting.
        assert (
            client.get(
                f"/api/v1/imports/{batch['id']}/original", headers=headers
            ).status_code
            == 200
        )

    def test_a_sheet_cannot_replace_itself(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        batch = import_a_register(client, dig)
        response = client.patch(
            f"/api/v1/imports/{batch['id']}/shelf",
            json={"superseded_by_id": batch["id"]},
            headers=auth_headers(client, "dir"),
        )
        assert response.status_code == 422

    def test_a_superseded_sheet_says_which_one_replaced_it(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        old = import_a_register(client, dig)
        new = import_a_register(client, dig)
        headers = auth_headers(client, "dir")
        changed = client.patch(
            f"/api/v1/imports/{old['id']}/shelf",
            json={"superseded_by_id": new["id"]},
            headers=headers,
        ).json()
        assert changed["state"] == "superseded"
        assert changed["superseded_by_id"] == new["id"]


class TestBringingASheetUpToDate:
    """The corrections, in the file's own columns.

    A register that comes back with columns called ``inventory_number`` is a
    register somebody has to re-key before sending it to a ministry, which is
    the work this was supposed to save.
    """

    def test_the_copy_carries_the_edits_under_the_original_headings(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        openpyxl = pytest.importorskip("openpyxl")
        batch = import_a_register(client, dig)
        headers = auth_headers(client, "dir")

        find = client.get(
            "/api/v1/artifacts",
            params={"q": "TED-2024-001", "site_id": dig["site"]["id"]},
            headers=headers,
        ).json()["items"][0]
        client.patch(
            f"/api/v1/artifacts/{find['id']}",
            json={"object_type": "Jar rim, painted"},
            headers=headers,
        )

        assert (
            client.post(f"/api/v1/imports/{batch['id']}/refresh", headers=headers).json()[
                "has_current_copy"
            ]
            is True
        )
        response = client.get(f"/api/v1/imports/{batch['id']}/current.xlsx", headers=headers)
        assert response.status_code == 200

        book = openpyxl.load_workbook(io.BytesIO(response.content))
        sheet = book[[name for name in book.sheetnames if name != "About this file"][0]]
        headings = [cell.value for cell in sheet[1]]
        assert headings == ["Inventory no.", "Object type", "Trench"]
        values = [[cell.value for cell in row] for row in sheet.iter_rows(min_row=2)]
        assert ["TED-2024-001", "Jar rim, painted", "A"] in values

    def test_asking_for_a_copy_before_one_is_built_says_so(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        batch = import_a_register(client, dig)
        response = client.get(
            f"/api/v1/imports/{batch['id']}/current.xlsx", headers=auth_headers(client, "dir")
        )
        assert response.status_code == 404
        assert "Bring it up to date" in response.json()["detail"]

    def test_a_sheet_that_was_never_imported_cannot_be_brought_up_to_date(
        self, client: TestClient, director: User
    ) -> None:
        headers = auth_headers(client, "dir")
        batch = client.post(
            "/api/v1/imports",
            files={
                "file": (
                    "notes.xlsx",
                    workbook([["Inventory no."], ["TED-1"]]),
                    "application/vnd.ms-excel",
                )
            },
            data={"record_type": "artifact"},
            headers=headers,
        ).json()

        response = client.post(f"/api/v1/imports/{batch['id']}/refresh", headers=headers)
        assert response.status_code == 409
        assert "has not been imported" in response.json()["detail"]

    def test_a_deleted_record_is_left_out_and_counted(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        openpyxl = pytest.importorskip("openpyxl")
        batch = import_a_register(client, dig)
        headers = auth_headers(client, "dir")
        find = client.get(
            "/api/v1/artifacts",
            params={"q": "TED-2024-001", "site_id": dig["site"]["id"]},
            headers=headers,
        ).json()["items"][0]
        client.delete(f"/api/v1/artifacts/{find['id']}", headers=headers)

        client.post(f"/api/v1/imports/{batch['id']}/refresh", headers=headers)
        response = client.get(f"/api/v1/imports/{batch['id']}/current.xlsx", headers=headers)
        book = openpyxl.load_workbook(io.BytesIO(response.content))
        # A rebuilt sheet with a row for something that no longer exists would
        # be a worse lie than a shorter sheet, so the cover says how many went.
        cover = "\n".join(
            str(cell.value)
            for row in book["About this file"].iter_rows()
            for cell in row
            if cell.value
        )
        assert "have since been deleted" in cover


class TestDeliveries:
    """Files for somebody who does not have an account, and never will."""

    def photo(self, client: TestClient, site_id: str, title: str) -> dict:
        response = client.post(
            "/api/v1/photographs",
            files={"file": (f"{title}.png", png(), "image/png")},
            data={"title": title, "site_id": site_id},
            headers=auth_headers(client, "dir"),
        )
        assert response.status_code == 201, response.text
        return response.json()

    def test_a_bundle_lands_on_the_disk_under_readable_names(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        from pathlib import Path

        picture = self.photo(client, dig["site"]["id"], "Trench A from the north")
        made = client.post(
            "/api/v1/deliveries",
            json={
                "title": "For the ministry",
                "to_name": "Layla",
                "to_email": "layla@example.org",
                "photograph_ids": [picture["id"]],
            },
            headers=auth_headers(client, "dir"),
        )
        assert made.status_code == 201, made.text
        body = made.json()
        assert body["file_count"] == 1
        # A link with a long random token in the path, and nothing else.
        assert "/collect/" in body["collect_url"]
        assert len(body["collect_url"].rsplit("/", 1)[-1]) >= 32

        # The name on disk is the one a person would look for, not a digest.
        folder = Path(body["folder_on_disk"])
        assert folder.is_dir()
        names = [path.name for path in folder.rglob("*") if path.is_file()]
        assert "About this folder.txt" in names
        # The picture's own title, not a digest. The folder level it would
        # otherwise have sat alone in is folded into the name rather than
        # costing a click - see `_collapse`.
        assert any("Trench A from the north" in name for name in names)
        assert not any(name.startswith(("ab", "9f")) and len(name) > 40 for name in names)

    def test_nothing_chosen_is_refused_in_words(
        self, client: TestClient, director: User
    ) -> None:
        response = client.post(
            "/api/v1/deliveries",
            json={"title": "Empty", "to_name": "Layla", "to_email": "layla@example.org"},
            headers=auth_headers(client, "dir"),
        )
        assert response.status_code == 422
        assert "Nothing was chosen" in response.json()["detail"]

    def test_the_recipient_needs_no_account(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        picture = self.photo(client, dig["site"]["id"], "The jar")
        made = client.post(
            "/api/v1/deliveries",
            json={
                "title": "The jar photographs",
                "to_name": "Layla",
                "to_email": "layla@example.org",
                "photograph_ids": [picture["id"]],
            },
            headers=auth_headers(client, "dir"),
        ).json()
        token = made["collect_url"].rsplit("/", 1)[-1]

        # No Authorization header anywhere below.
        page = client.get(f"/api/v1/deliveries/collect/{token}")
        assert page.status_code == 200
        assert page.json()["title"] == "The jar photographs"
        assert page.json()["file_count"] == 1

        download = client.get(f"/api/v1/deliveries/collect/{token}/download")
        assert download.status_code == 200
        assert download.content[:2] == b"PK"

    def test_a_wrong_token_says_nothing_about_the_archive(self, client: TestClient) -> None:
        response = client.get("/api/v1/deliveries/collect/not-a-real-token")
        assert response.status_code == 404
        assert "not valid any more" in response.json()["detail"]

    def test_collecting_is_recorded(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        picture = self.photo(client, dig["site"]["id"], "The jar")
        made = client.post(
            "/api/v1/deliveries",
            json={
                "title": "The jar",
                "to_name": "Layla",
                "to_email": "layla@example.org",
                "photograph_ids": [picture["id"]],
            },
            headers=auth_headers(client, "dir"),
        ).json()
        token = made["collect_url"].rsplit("/", 1)[-1]
        client.get(f"/api/v1/deliveries/collect/{token}/download")

        after = client.get(
            f"/api/v1/deliveries/{made['id']}", headers=auth_headers(client, "dir")
        ).json()
        assert after["status"] == "collected"
        assert after["collected_count"] == 1

    def test_deleting_a_bundle_leaves_the_archive_alone(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        picture = self.photo(client, dig["site"]["id"], "The jar")
        headers = auth_headers(client, "dir")
        made = client.post(
            "/api/v1/deliveries",
            json={
                "title": "The jar",
                "to_name": "Layla",
                "to_email": "layla@example.org",
                "photograph_ids": [picture["id"]],
            },
            headers=headers,
        ).json()

        removed = client.delete(f"/api/v1/deliveries/{made['id']}", headers=headers)
        assert removed.status_code == 200

        # The photograph is untouched: a bundle is a second copy.
        assert (
            client.get(f"/api/v1/photographs/{picture['id']}", headers=headers).status_code == 200
        )
        # And the link no longer works.
        token = made["collect_url"].rsplit("/", 1)[-1]
        assert client.get(f"/api/v1/deliveries/collect/{token}").status_code == 404

    def test_sending_files_out_needs_export_access(
        self, client: TestClient, director: User, onlooker: User, dig: dict
    ) -> None:
        picture = self.photo(client, dig["site"]["id"], "The jar")
        response = client.post(
            "/api/v1/deliveries",
            json={
                "title": "Mine now",
                "to_name": "Me",
                "to_email": "me@example.org",
                "photograph_ids": [picture["id"]],
            },
            headers=auth_headers(client, "look"),
        )
        assert response.status_code == 403


class TestTheFolderOnTheDisk:
    """The archive as folders, for picking up without a browser."""

    def test_it_writes_the_records_names_not_digests(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        from pathlib import Path

        headers = auth_headers(client, "dir")
        client.post(
            "/api/v1/photographs",
            files={"file": ("a.png", png(), "image/png")},
            data={"title": "Trench A working shot", "site_id": dig["site"]["id"]},
            headers=headers,
        )
        client.post(
            "/api/v1/photographs",
            files={"file": ("b.png", png(), "image/png")},
            data={"title": "Trench A, second", "site_id": dig["site"]["id"]},
            headers=headers,
        )

        built = client.post("/api/v1/mirror", headers=headers)
        assert built.status_code == 200, built.text
        root = Path(built.json()["folder_on_disk"])

        assert (root / "Sites" / "TED-A North trench" / "Photographs").is_dir()
        names = {path.name for path in root.rglob("*") if path.is_file()}
        assert "Trench A working shot.png" in names
        assert "About this folder.txt" in names

    def test_a_lone_file_is_not_buried_in_a_folder_of_its_own(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """One file inside one folder inside one folder is three clicks of
        nothing, and it is how a filing system becomes one people avoid."""
        from pathlib import Path

        headers = auth_headers(client, "dir")
        client.post(
            "/api/v1/photographs",
            files={"file": ("a.png", png(), "image/png")},
            data={"title": "The only picture", "site_id": dig["site"]["id"]},
            headers=headers,
        )
        built = client.post("/api/v1/mirror", headers=headers).json()
        root = Path(built["folder_on_disk"])

        # The Photographs level held one file and nothing else, so it folded
        # into the name rather than costing a click.
        assert not (root / "Sites" / "TED-A North trench" / "Photographs").exists()
        assert (root / "Sites" / "TED-A North trench" / "The only picture - Photographs.png").is_file()

    def test_building_it_again_replaces_rather_than_doubles(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        headers = auth_headers(client, "dir")
        client.post(
            "/api/v1/photographs",
            files={"file": ("a.png", png(), "image/png")},
            data={"title": "Trench A", "site_id": dig["site"]["id"]},
            headers=headers,
        )
        first = client.post("/api/v1/mirror", headers=headers).json()
        second = client.post("/api/v1/mirror", headers=headers).json()
        assert first["files"] == second["files"]

    def test_the_state_says_when_it_was_built(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        headers = auth_headers(client, "dir")
        built = client.post("/api/v1/mirror", headers=headers).json()

        after = client.get("/api/v1/mirror", headers=headers).json()
        assert after["exists"] is True
        assert after["built_at"] is not None
        assert after["folder_on_disk"] == built["folder_on_disk"]
