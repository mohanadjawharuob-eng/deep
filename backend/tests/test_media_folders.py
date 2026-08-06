"""Recording a folder instead of uploading it.

A season's raw frames are four hundred gigabytes, already on the project drive
and already backed up. Uploading them costs a week and buys nothing. But a
catalogue that is *silent* about four hundred gigabytes will be read as
complete, and the drive will be reformatted by somebody who checked the archive
first.

Two properties are worth defending.

**It is filed under a real record, and inherits that record's permissions.** An
unattached note about a path is unfindable and unprotectable; and a folder on a
site somebody cannot see must not be listed to them, because the path itself
says where the site is.

**Deleting it touches nothing on disk.** The word "delete" beside a path reads
like it might, and somebody has to be able to be sure.
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
def outsider(db: Session) -> User:
    return make_user(db, email="stu@example.org", username="stu", role=UserRole.STUDENT)


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


def record(client: TestClient, site_id: str, *, identifier: str = "dir", **fields):
    body = {
        "label": "Trench A season photographs",
        "path": r"D:\Seasons\2019\TrenchA",
        "kind": "photographs",
        "site_id": site_id,
        **fields,
    }
    return client.post("/api/v1/media-folders", json=body, headers=auth_headers(client, identifier))


class TestRecordingAFolder:
    def test_a_folder_is_recorded_against_a_site(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        response = record(
            client,
            dig["site"]["id"],
            medium="External drive DIG-2019",
            item_count=8412,
            size_gb=412.5,
            is_backed_up=True,
        )
        assert response.status_code == 201, response.text

        body = response.json()
        assert body["path"] == r"D:\Seasons\2019\TrenchA"
        assert body["medium"] == "External drive DIG-2019"
        assert body["item_count"] == 8412
        assert body["site_id"] == dig["site"]["id"]
        # Filled in from the site, so a project-level listing finds it too.
        assert body["project_id"] == dig["project"]["id"]

    def test_the_path_is_stored_exactly_as_written(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """Never parsed, never resolved, never normalised.

        A Windows path, a share, a mount point on somebody else's laptop and a
        shelf reference for a box of discs all go in this field, and the
        platform is in no position to tell them apart.
        """
        for path in (
            r"\\nas01\excavation\2019",
            "/Volumes/Archive/TED/2019",
            "Shelf 4, box marked TED-2019 (12 DVDs)",
        ):
            body = record(client, dig["site"]["id"], path=path).json()
            assert body["path"] == path

    def test_backed_up_has_three_states(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """Yes, no, and nobody has said — and the third is the common one.

        Storing "nobody has looked" as "not backed up" would produce a list of
        alarming red rows nobody trusts; storing it as "backed up" would be a
        lie in the only direction that costs data.
        """
        assert record(client, dig["site"]["id"]).json()["is_backed_up"] is None
        assert record(client, dig["site"]["id"], is_backed_up=False).json()["is_backed_up"] is False

    def test_it_must_hang_off_something(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        response = client.post(
            "/api/v1/media-folders",
            json={"label": "Loose note", "path": "D:/somewhere"},
            headers=auth_headers(client, "dir"),
        )
        assert response.status_code == 422

    def test_an_empty_path_is_refused(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        assert record(client, dig["site"]["id"], path="   ").status_code == 422


class TestFinding:
    def test_listed_by_the_record_you_are_looking_at(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        record(client, dig["site"]["id"], label="Photographs")
        record(client, dig["site"]["id"], label="Drone survey", kind="survey")

        headers = auth_headers(client, "dir")
        listed = client.get(
            f"/api/v1/media-folders?site_id={dig['site']['id']}", headers=headers
        ).json()
        assert listed["total"] == 2

        just_survey = client.get(
            f"/api/v1/media-folders?site_id={dig['site']['id']}&kind=survey", headers=headers
        ).json()
        assert [row["label"] for row in just_survey["items"]] == ["Drone survey"]

    def test_a_site_somebody_cannot_see_does_not_leak_its_paths(
        self, client: TestClient, director: User, outsider: User, dig: dict
    ) -> None:
        """The path says where the site is. That is the thing being protected."""
        client.patch(
            f"/api/v1/sites/{dig['site']['id']}",
            json={"is_public": False},
            headers=auth_headers(client, "dir"),
        )
        record(client, dig["site"]["id"])

        listed = client.get("/api/v1/media-folders", headers=auth_headers(client, "stu")).json()
        assert listed["total"] == 0


class TestChangingIt:
    def test_a_path_can_be_corrected(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """Which is most of what happens to these: the drive gets a new letter."""
        folder = record(client, dig["site"]["id"]).json()
        updated = client.patch(
            f"/api/v1/media-folders/{folder['id']}",
            json={"path": r"E:\Seasons\2019\TrenchA", "medium": "Drive relabelled DIG-A"},
            headers=auth_headers(client, "dir"),
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["path"] == r"E:\Seasons\2019\TrenchA"
        # Unsent fields keep their values.
        assert updated.json()["label"] == "Trench A season photographs"

    def test_deleting_says_that_nothing_on_disk_was_touched(
        self, client: TestClient, director: User, dig: dict
    ) -> None:
        """"Delete" beside a path reads like it might remove the folder."""
        folder = record(client, dig["site"]["id"]).json()
        response = client.delete(
            f"/api/v1/media-folders/{folder['id']}", headers=auth_headers(client, "dir")
        )
        assert response.status_code == 200, response.text
        assert "nothing on disk" in response.json()["detail"].lower()

        assert (
            client.get(
                f"/api/v1/media-folders/{folder['id']}", headers=auth_headers(client, "dir")
            ).status_code
            == 404
        )

    def test_somebody_not_on_the_project_cannot_record_one(
        self, client: TestClient, director: User, outsider: User, dig: dict
    ) -> None:
        """Refused, and refused the same way every other attachment is.

        A private project answers 404 rather than 403, because whether it
        exists is itself the information being withheld. Once it is public the
        refusal becomes a plain 403 about not being on the team — which is the
        answer, and this records both so a future change to either cannot pass
        unnoticed.
        """
        headers = auth_headers(client, "dir")
        assert record(client, dig["site"]["id"], identifier="stu").status_code == 404

        client.patch(
            f"/api/v1/projects/{dig['project']['id']}", json={"is_public": True}, headers=headers
        )
        client.patch(
            f"/api/v1/sites/{dig['site']['id']}", json={"is_public": True}, headers=headers
        )
        refused = record(client, dig["site"]["id"], identifier="stu")
        assert refused.status_code == 403
        assert "member" in refused.json()["detail"].lower()
