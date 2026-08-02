"""The copy kept on disk when something is deleted.

Deleting is the one action nobody can undo by clicking again. The database
already keeps a final revision, which answers "put it back" — these tests
cover the case a revision cannot answer, which is losing the database.

The important assertions are that the file is written *before* the row goes,
so the children are still there to capture; and that a failure to write does
not stop the deletion, because a full disk must not make the platform
unusable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User, UserRole
from app.services import deletions
from tests.conftest import auth_headers, make_user


@pytest.fixture
def archive_root() -> Path:
    """An empty archive for each test.

    The folder is not rolled back the way the database is — these are real
    files on a real disk, which is the whole point of the feature. So it is
    emptied per test rather than per session; otherwise every assertion about
    "the file that was written" would really be reading the previous test's.
    """
    import shutil

    root = Path(os.environ["DELETED_ROOT"])
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    return root


def files_in(root: Path) -> list[Path]:
    return sorted(root.rglob("*.json"))


def read_one(root: Path) -> dict:
    found = files_in(root)
    assert len(found) == 1, f"expected one archive, found {[p.name for p in found]}"
    return json.loads(found[0].read_text(encoding="utf-8"))


@pytest.fixture
def director(db: Session) -> User:
    return make_user(
        db, email="director@example.org", username="director", role=UserRole.ADMIN
    )


def make_project(client: TestClient, **fields) -> dict:
    payload = {"name": "Tell el-Demo", "code": "TED-2024"} | fields
    response = client.post(
        "/api/v1/projects", json=payload, headers=auth_headers(client, "director")
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestArchiveIsWritten:
    def test_deleting_a_project_leaves_a_file_behind(
        self, client: TestClient, director: User, archive_root: Path
    ) -> None:
        project = make_project(client)
        response = client.delete(
            f"/api/v1/projects/{project['id']}", headers=auth_headers(client, "director")
        )
        assert response.status_code == 200, response.text

        data = read_one(archive_root)
        assert data["resource_type"] == "project"
        assert data["resource_id"] == project["id"]
        assert data["record"]["code"] == "TED-2024"
        assert data["record"]["name"] == "Tell el-Demo"

    def test_it_records_who_deleted_it_and_when(
        self, client: TestClient, director: User, archive_root: Path
    ) -> None:
        project = make_project(client)
        client.delete(
            f"/api/v1/projects/{project['id']}", headers=auth_headers(client, "director")
        )

        data = read_one(archive_root)
        assert data["deleted_by"]["username"] == "director"
        # An ISO timestamp, not a bare date: "who deleted this and when" is a
        # question asked about a specific afternoon.
        assert data["deleted_at"].startswith("20")
        assert "T" in data["deleted_at"]

    def test_the_filename_carries_the_label_so_it_can_be_found_by_eye(
        self, client: TestClient, director: User, archive_root: Path
    ) -> None:
        project = make_project(client, name="North trench", code="NT-2019")
        client.delete(
            f"/api/v1/projects/{project['id']}", headers=auth_headers(client, "director")
        )

        name = files_in(archive_root)[0].name
        assert name.startswith("project-")
        # Somebody hunting for what they lost searches for the name they
        # remember, not a UUID.
        assert "NT-2019" in name or "North-trench" in name

    def test_a_name_with_a_slash_in_it_does_not_break_the_path(
        self, client: TestClient, director: User, archive_root: Path
    ) -> None:
        project = make_project(client, name="Survey 2019 / north", code="S-2019")
        response = client.delete(
            f"/api/v1/projects/{project['id']}", headers=auth_headers(client, "director")
        )
        assert response.status_code == 200

        found = files_in(archive_root)
        assert len(found) == 1
        assert "/" not in found[0].name

    def test_children_come_across_with_the_parent(
        self, client: TestClient, director: User, archive_root: Path
    ) -> None:
        """The whole point of archiving before the row goes.

        A site's contexts are gone the moment the site is, so an archive taken
        afterwards would hold a name and nothing else.
        """
        project = make_project(client)
        site = client.post(
            "/api/v1/sites",
            json={"name": "Tell el-Demo", "code": "TED-S1", "project_id": project["id"]},
            headers=auth_headers(client, "director"),
        )
        assert site.status_code == 201, site.text
        site_id = site.json()["id"]

        for number in ("1001", "1002"):
            created = client.post(
                "/api/v1/contexts",
                json={"context_number": number, "site_id": site_id, "context_type": "layer"},
                headers=auth_headers(client, "director"),
            )
            assert created.status_code == 201, created.text

        client.delete(f"/api/v1/sites/{site_id}", headers=auth_headers(client, "director"))

        archives = files_in(archive_root)
        site_archive = next(path for path in archives if path.name.startswith("site-"))
        data = json.loads(site_archive.read_text(encoding="utf-8"))
        # Contexts hang off a site by foreign key with no mapped
        # collection, so this is the sweep rather than the relationship pass.
        rows = data["children"].get("excavation_contexts.site_id", [])
        numbers = {row["context_number"] for row in rows}
        assert numbers == {"1001", "1002"}

    def test_each_deletion_gets_its_own_file(
        self, client: TestClient, director: User, archive_root: Path
    ) -> None:
        for index in range(3):
            project = make_project(client, name=f"Project {index}", code=f"P-{index}")
            client.delete(
                f"/api/v1/projects/{project['id']}", headers=auth_headers(client, "director")
            )
        assert len(files_in(archive_root)) == 3


class TestArchiveNeverBlocksTheDeletion:
    def test_the_record_still_goes_when_the_archive_cannot_be_written(
        self,
        client: TestClient,
        director: User,
        archive_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A full disk must not make the platform unusable.

        Refusing to delete because the copy failed punishes somebody for a
        problem they cannot see, and leaves them with no way forward at all.
        """
        project = make_project(client)

        def explode(*args: object, **kwargs: object) -> None:
            raise OSError("No space left on device")

        monkeypatch.setattr(Path, "write_text", explode)

        response = client.delete(
            f"/api/v1/projects/{project['id']}", headers=auth_headers(client, "director")
        )
        assert response.status_code == 200, response.text

        gone = client.get(
            f"/api/v1/projects/{project['id']}", headers=auth_headers(client, "director")
        )
        assert gone.status_code == 404

    def test_the_failure_is_logged_rather_than_swallowed(
        self,
        client: TestClient,
        director: User,
        archive_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        project = make_project(client)

        def explode(*args: object, **kwargs: object) -> None:
            raise OSError("No space left on device")

        monkeypatch.setattr(Path, "write_text", explode)

        with caplog.at_level("WARNING", logger="archeo.deletions"):
            client.delete(
                f"/api/v1/projects/{project['id']}", headers=auth_headers(client, "director")
            )

        # Not silent. Somebody reading the log has to be able to tell that the
        # safety net was not there.
        assert any("Could not archive" in record.message for record in caplog.records)


class TestListingWhatWasDeleted:
    def test_recent_reads_the_files_back(
        self, client: TestClient, director: User, archive_root: Path
    ) -> None:
        project = make_project(client, name="Gone", code="GONE-1")
        client.delete(
            f"/api/v1/projects/{project['id']}", headers=auth_headers(client, "director")
        )

        entries = deletions.recent()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["label"] in {"Gone", "GONE-1"}
        assert entry["resource_type"] == "project"
        assert entry["deleted_by"] == "director"

    def test_an_empty_archive_is_not_an_error(self, archive_root: Path) -> None:
        assert deletions.recent() == []
