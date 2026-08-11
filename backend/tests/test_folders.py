"""Folders: somewhere to put things, made by the people who use the platform.

The rule that keeps this from competing with the record links is that **a
folder is a label**. Removing the label leaves what it was on. Most of the
tests below exist to hold that line, because a filing system that deletes
files when a drawer is emptied is worse than no filing system.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User, UserRole
from tests.conftest import auth_headers, make_user


@pytest.fixture
def director(db: Session) -> User:
    return make_user(db, email="dir@example.org", username="dir", role=UserRole.ADMIN)


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


def png() -> bytes:
    pillow = pytest.importorskip("PIL.Image")
    buffer = io.BytesIO()
    pillow.new("RGB", (40, 30), (120, 90, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


def folder(client: TestClient, name: str, **fields) -> dict:
    response = client.post(
        "/api/v1/folders", json={"name": name, **fields}, headers=auth_headers(client, "dir")
    )
    assert response.status_code == 201, response.text
    return response.json()


def photo(client: TestClient, site_id: str, name: str) -> dict:
    response = client.post(
        "/api/v1/photographs",
        files={"file": (name, png(), "image/png")},
        data={"title": name, "site_id": site_id},
        headers=auth_headers(client, "dir"),
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestTheTree:
    def test_folders_nest(self, client: TestClient, director: User) -> None:
        season = folder(client, "2024")
        trench = folder(client, "Trench A", parent_id=season["id"])
        shots = folder(client, "Working shots", parent_id=trench["id"])

        assert shots["parent_id"] == trench["id"]
        assert trench["parent_id"] == season["id"]
        assert season["parent_id"] is None

    def test_two_folders_cannot_share_a_name_in_one_place(
        self, client: TestClient, director: User
    ) -> None:
        season = folder(client, "2024")
        folder(client, "Trench A", parent_id=season["id"])

        clash = client.post(
            "/api/v1/folders",
            json={"name": "Trench A", "parent_id": season["id"]},
            headers=auth_headers(client, "dir"),
        )
        assert clash.status_code == 409

        # But the same name in a different place is ordinary and allowed.
        other = folder(client, "2025")
        again = client.post(
            "/api/v1/folders",
            json={"name": "Trench A", "parent_id": other["id"]},
            headers=auth_headers(client, "dir"),
        )
        assert again.status_code == 201

    def test_two_top_level_folders_cannot_share_a_name_either(
        self, client: TestClient, director: User
    ) -> None:
        """`UNIQUE(parent_id, name)` does not catch this on its own, because
        NULL is not equal to NULL."""
        folder(client, "Photographs")

        clash = client.post(
            "/api/v1/folders", json={"name": "Photographs"}, headers=auth_headers(client, "dir")
        )
        assert clash.status_code == 409

    def test_a_folder_cannot_be_moved_inside_itself(
        self, client: TestClient, director: User
    ) -> None:
        """Dropping a folder into its own grandchild detaches the whole branch
        from the tree, and everything in it is then reachable from nothing."""
        season = folder(client, "2024")
        trench = folder(client, "Trench A", parent_id=season["id"])

        response = client.patch(
            f"/api/v1/folders/{season['id']}",
            json={"parent_id": trench["id"]},
            headers=auth_headers(client, "dir"),
        )
        assert response.status_code == 422
        assert "unreachable" in response.json()["detail"]

    def test_a_folder_cannot_be_its_own_parent(self, client: TestClient, director: User) -> None:
        season = folder(client, "2024")
        response = client.patch(
            f"/api/v1/folders/{season['id']}",
            json={"parent_id": season["id"]},
            headers=auth_headers(client, "dir"),
        )
        assert response.status_code == 422


class TestFilingThings:
    def test_a_photograph_can_be_filed_and_moved(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        headers = auth_headers(client, "dir")
        first = folder(client, "Working shots")
        second = folder(client, "Published")
        picture = photo(client, dig["site"]["id"], "trench.png")

        client.post(
            f"/api/v1/folders/{first['id']}/contents",
            json={"photograph_ids": [picture["id"]]},
            headers=headers,
        )
        listed = client.get(
            "/api/v1/photographs", params={"folder_id": first["id"]}, headers=headers
        ).json()
        assert [row["id"] for row in listed["items"]] == [picture["id"]]

        # Moved, not copied: a photograph in two folders is a photograph
        # nobody can file.
        client.post(
            f"/api/v1/folders/{second['id']}/contents",
            json={"photograph_ids": [picture["id"]]},
            headers=headers,
        )
        assert (
            client.get(
                "/api/v1/photographs", params={"folder_id": first["id"]}, headers=headers
            ).json()["total"]
            == 0
        )
        assert (
            client.get(
                "/api/v1/photographs", params={"folder_id": second["id"]}, headers=headers
            ).json()["total"]
            == 1
        )

    def test_what_is_unfiled_can_be_listed(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        headers = auth_headers(client, "dir")
        drawer = folder(client, "Filed")
        filed = photo(client, dig["site"]["id"], "filed.png")
        photo(client, dig["site"]["id"], "loose.png")

        client.post(
            f"/api/v1/folders/{drawer['id']}/contents",
            json={"photograph_ids": [filed["id"]]},
            headers=headers,
        )

        loose = client.get(
            "/api/v1/photographs", params={"folder_id": "none"}, headers=headers
        ).json()
        assert [row["title"] for row in loose["items"]] == ["loose.png"]

    def test_the_count_is_what_is_directly_inside(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """Not including sub-folders. A count that quietly swept everything
        underneath would make an empty folder look full."""
        headers = auth_headers(client, "dir")
        season = folder(client, "2024")
        trench = folder(client, "Trench A", parent_id=season["id"])
        picture = photo(client, dig["site"]["id"], "a.png")

        client.post(
            f"/api/v1/folders/{trench['id']}/contents",
            json={"photograph_ids": [picture["id"]]},
            headers=headers,
        )

        rows = {row["name"]: row for row in client.get("/api/v1/folders", headers=headers).json()}
        assert rows["Trench A"]["file_count"] == 1
        assert rows["2024"]["file_count"] == 0


class TestRemovingAFolder:
    def test_deleting_a_folder_keeps_the_files(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """The whole design rests on this. A folder is a label; removing the
        label leaves what it was on."""
        headers = auth_headers(client, "dir")
        drawer = folder(client, "Working shots")
        picture = photo(client, dig["site"]["id"], "trench.png")
        client.post(
            f"/api/v1/folders/{drawer['id']}/contents",
            json={"photograph_ids": [picture["id"]]},
            headers=headers,
        )

        removed = client.delete(f"/api/v1/folders/{drawer['id']}", headers=headers)
        assert removed.status_code == 200
        assert "Nothing in it was deleted" in removed.json()["detail"]

        # Still there, still on its site, now unfiled.
        still = client.get(f"/api/v1/photographs/{picture['id']}", headers=headers)
        assert still.status_code == 200
        assert still.json()["site_id"] == dig["site"]["id"]
        assert still.json()["folder_id"] is None

    def test_deleting_a_folder_takes_its_subfolders(
        self, client: TestClient, director: User
    ) -> None:
        headers = auth_headers(client, "dir")
        season = folder(client, "2024")
        folder(client, "Trench A", parent_id=season["id"])

        client.delete(f"/api/v1/folders/{season['id']}", headers=headers)

        remaining = client.get("/api/v1/folders", headers=headers).json()
        assert remaining == []


class TestChannels:
    def test_a_channel_is_a_folder(self, client: TestClient, director: User) -> None:
        """ "The pictures we posted to Instagram" is a real drawer in a real
        institution. Giving it a place in this tree beats a separate module
        with a second, incompatible idea of a folder."""
        headers = auth_headers(client, "dir")
        instagram = folder(client, "Instagram", kind="instagram")
        folder(client, "September", parent_id=instagram["id"])

        channels = client.get(
            "/api/v1/folders", params={"kind": "instagram"}, headers=headers
        ).json()
        assert [row["name"] for row in channels] == ["Instagram"]

        everything = client.get("/api/v1/folders", headers=headers).json()
        assert {row["name"] for row in everything} == {"Instagram", "September"}
