"""Per-module permissions.

The point of this model is the user who is senior in one module and a stranger
in another: an archaeology supervisor who may not read the museum's loans, a
collections manager who cannot see excavation records. The old single-role
model could not express that at all, so most of these cases are new behaviour
rather than a restatement of the role table.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.permissions import (
    DEFAULT_MODULE_ACCESS,
    PLATFORM_CAPABILITIES,
    Capability,
    has_capability,
    has_module_access,
    module_level,
    module_of,
    requires_approval,
)
from app.models import Module, ModuleLevel, ResourceType, User, UserRole
from app.services import access
from tests.conftest import auth_headers, make_user


# --------------------------------------------------------------------------
# The level ladder
# --------------------------------------------------------------------------
class TestModuleLevels:
    def test_levels_are_ordered(self) -> None:
        assert ModuleLevel.VIEWER < ModuleLevel.CONTRIBUTOR
        assert ModuleLevel.CONTRIBUTOR < ModuleLevel.EDITOR
        assert ModuleLevel.EDITOR < ModuleLevel.SUPERVISOR
        assert ModuleLevel.SUPERVISOR < ModuleLevel.ADMINISTRATOR

    def test_every_module_has_a_level_for_every_legacy_role(self) -> None:
        """No role may map to nothing by accident — that would silently lock
        an existing account out when the migration runs."""
        for role in UserRole:
            assert role in DEFAULT_MODULE_ACCESS
        # The administrator is the deliberate exception: they need no row.
        assert DEFAULT_MODULE_ACCESS[UserRole.ADMIN] is None
        for role in (UserRole.VISITOR, UserRole.STUDENT, UserRole.RESEARCHER):
            assert DEFAULT_MODULE_ACCESS[role] is not None

    def test_every_resource_type_belongs_to_a_module(self) -> None:
        for resource_type in ResourceType:
            assert isinstance(module_of(resource_type), Module)


# --------------------------------------------------------------------------
# Granting and revoking
# --------------------------------------------------------------------------
class TestGranting:
    def test_a_new_account_reaches_only_archaeology(self, db: Session) -> None:
        user = make_user(db, email="fresh@example.org", username="fresh")

        assert module_level(user, Module.ARCHAEOLOGY) is ModuleLevel.CONTRIBUTOR
        for module in (Module.MUSEUM, Module.MANAGEMENT, Module.INVENTORY):
            assert module_level(user, module) is None

    def test_access_is_additive_across_modules(self, db: Session) -> None:
        user = make_user(
            db,
            email="curator@example.org",
            username="curator",
            role=UserRole.RESEARCHER,
            modules={
                Module.MUSEUM: ModuleLevel.ADMINISTRATOR,
                Module.INVENTORY: ModuleLevel.VIEWER,
            },
        )

        # Senior in two places, absent from the rest — the whole point.
        assert module_level(user, Module.ARCHAEOLOGY) is ModuleLevel.SUPERVISOR
        assert module_level(user, Module.MUSEUM) is ModuleLevel.ADMINISTRATOR
        assert module_level(user, Module.INVENTORY) is ModuleLevel.VIEWER
        assert module_level(user, Module.MANAGEMENT) is None
        assert module_level(user, Module.SOCIAL_MEDIA) is None

    def test_granting_twice_replaces_rather_than_duplicates(self, db: Session) -> None:
        user = make_user(db, email="promoted@example.org", username="promoted")

        access.grant(db, user, Module.MUSEUM, ModuleLevel.VIEWER)
        access.grant(db, user, Module.MUSEUM, ModuleLevel.EDITOR)

        assert module_level(user, Module.MUSEUM) is ModuleLevel.EDITOR
        museum_rows = [row for row in user.module_access if row.module is Module.MUSEUM]
        assert len(museum_rows) == 1

    def test_revoking_leaves_other_modules_alone(self, db: Session) -> None:
        user = make_user(
            db,
            email="partial@example.org",
            username="partial",
            modules={Module.MUSEUM: ModuleLevel.EDITOR},
        )

        assert access.revoke(db, user, Module.MUSEUM) is True
        assert module_level(user, Module.MUSEUM) is None
        assert module_level(user, Module.ARCHAEOLOGY) is ModuleLevel.CONTRIBUTOR

    def test_revoking_what_was_never_granted_is_not_an_error(self, db: Session) -> None:
        user = make_user(db, email="never@example.org", username="never")
        assert access.revoke(db, user, Module.SOCIAL_MEDIA) is False

    def test_an_administrator_holds_every_module_without_rows(self, db: Session) -> None:
        admin = make_user(db, email="root@example.org", username="root", role=UserRole.ADMIN)

        assert admin.module_access == []
        for module in Module:
            assert module_level(admin, module) is ModuleLevel.ADMINISTRATOR

    def test_a_deactivated_account_reaches_nothing(self, db: Session) -> None:
        user = make_user(
            db,
            email="gone@example.org",
            username="gone",
            role=UserRole.ADMIN,
            is_active=False,
        )
        assert module_level(user, Module.ARCHAEOLOGY) is None


# --------------------------------------------------------------------------
# Capabilities
# --------------------------------------------------------------------------
class TestCapabilities:
    @pytest.mark.parametrize(
        ("level", "capability", "expected"),
        [
            (ModuleLevel.VIEWER, Capability.CREATE_RECORD, False),
            (ModuleLevel.CONTRIBUTOR, Capability.CREATE_RECORD, True),
            (ModuleLevel.CONTRIBUTOR, Capability.UPLOAD_FILE, True),
            (ModuleLevel.CONTRIBUTOR, Capability.CREATE_PROJECT, False),
            (ModuleLevel.CONTRIBUTOR, Capability.APPROVE_SUBMISSION, False),
            (ModuleLevel.EDITOR, Capability.CREATE_PROJECT, False),
            (ModuleLevel.EDITOR, Capability.APPROVE_SUBMISSION, False),
            (ModuleLevel.SUPERVISOR, Capability.CREATE_PROJECT, True),
            (ModuleLevel.SUPERVISOR, Capability.APPROVE_SUBMISSION, True),
            (ModuleLevel.SUPERVISOR, Capability.DELETE_PROJECT, False),
            (ModuleLevel.ADMINISTRATOR, Capability.DELETE_PROJECT, True),
        ],
    )
    def test_capability_needs_its_level(
        self, db: Session, level: ModuleLevel, capability: Capability, expected: bool
    ) -> None:
        user = make_user(
            db,
            email=f"{level.value}@example.org",
            username=f"cap.{level.value}",
            role=UserRole.VISITOR,
            modules={Module.ARCHAEOLOGY: level},
        )
        assert has_capability(user, capability, Module.ARCHAEOLOGY) is expected

    def test_a_capability_in_one_module_says_nothing_about_another(self, db: Session) -> None:
        user = make_user(
            db,
            email="split@example.org",
            username="split",
            role=UserRole.VISITOR,
            modules={
                Module.ARCHAEOLOGY: ModuleLevel.SUPERVISOR,
                Module.MUSEUM: ModuleLevel.VIEWER,
            },
        )

        assert has_capability(user, Capability.CREATE_RECORD, Module.ARCHAEOLOGY) is True
        assert has_capability(user, Capability.CREATE_RECORD, Module.MUSEUM) is False
        assert has_capability(user, Capability.CREATE_RECORD, Module.INVENTORY) is False

    @pytest.mark.parametrize("capability", sorted(PLATFORM_CAPABILITIES, key=lambda c: c.value))
    def test_platform_capabilities_are_out_of_reach_of_module_seniority(
        self, db: Session, capability: Capability
    ) -> None:
        """Running a museum must not confer the ability to create accounts."""
        user = make_user(
            db,
            email=f"top.{capability.value}@example.org",
            username=f"top.{capability.value}".replace("_", "."),
            role=UserRole.RESEARCHER,
            modules=dict.fromkeys(Module, ModuleLevel.ADMINISTRATOR),
        )

        assert has_capability(user, capability, Module.MUSEUM) is False
        assert has_capability(user, capability, Module.ARCHAEOLOGY) is False

    def test_platform_capabilities_belong_to_the_global_administrator(self, db: Session) -> None:
        admin = make_user(db, email="pa@example.org", username="pa", role=UserRole.ADMIN)
        for capability in PLATFORM_CAPABILITIES:
            assert has_capability(admin, capability) is True

    def test_anonymous_callers_hold_nothing(self) -> None:
        for capability in Capability:
            assert has_capability(None, capability) is False
        assert module_level(None, Module.ARCHAEOLOGY) is None
        assert has_module_access(None, Module.ARCHAEOLOGY, ModuleLevel.VIEWER) is False


# --------------------------------------------------------------------------
# Approval follows the level, not the job title
# --------------------------------------------------------------------------
class TestApprovalThreshold:
    @pytest.mark.parametrize(
        ("level", "needs_approval"),
        [
            (ModuleLevel.VIEWER, True),
            (ModuleLevel.CONTRIBUTOR, True),
            (ModuleLevel.EDITOR, False),
            (ModuleLevel.SUPERVISOR, False),
            (ModuleLevel.ADMINISTRATOR, False),
        ],
    )
    def test_contributors_submit_for_approval_and_editors_do_not(
        self, db: Session, level: ModuleLevel, needs_approval: bool
    ) -> None:
        user = make_user(
            db,
            email=f"approve.{level.value}@example.org",
            username=f"approve.{level.value}",
            role=UserRole.VISITOR,
            modules={Module.ARCHAEOLOGY: level},
        )
        assert requires_approval(user, Module.ARCHAEOLOGY) is needs_approval

    def test_a_user_with_no_access_to_the_module_is_not_asked_for_approval(
        self, db: Session
    ) -> None:
        """They cannot create there at all, so the question does not arise."""
        user = make_user(db, email="outside@example.org", username="outside")
        assert requires_approval(user, Module.MUSEUM) is False


# --------------------------------------------------------------------------
# End to end: the module ceiling actually bites
# --------------------------------------------------------------------------
class TestModuleCeilingOverHttp:
    @pytest.fixture
    def project(self, client: TestClient, researcher: User) -> dict:
        response = client.post(
            "/api/v1/projects",
            json={"name": "Access Test", "code": "acc-1", "is_public": True},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 201, response.text
        return response.json()

    def test_losing_archaeology_access_stops_writing_but_not_public_reading(
        self, client: TestClient, db: Session, researcher: User, project: dict
    ) -> None:
        writer = make_user(
            db,
            email="writer@example.org",
            username="writer",
            role=UserRole.RESEARCHER,
        )
        headers = auth_headers(client, "writer")

        # With access, they can create a project of their own.
        first = client.post(
            "/api/v1/projects",
            json={"name": "Mine", "code": "mine-1", "is_public": True},
            headers=headers,
        )
        assert first.status_code == 201, first.text

        access.revoke(db, writer, Module.ARCHAEOLOGY)
        db.flush()

        second = client.post(
            "/api/v1/projects",
            json={"name": "Also mine", "code": "mine-2", "is_public": True},
            headers=headers,
        )
        assert second.status_code == 403
        assert "archaeology" in second.json()["detail"].lower()

        # Public records stay readable: public is public, module access or not.
        listing = client.get("/api/v1/projects", headers=headers)
        assert listing.status_code == 200
        assert project["id"] in {item["id"] for item in listing.json()["items"]}

    def test_a_viewer_cannot_edit_even_their_own_record(
        self, client: TestClient, db: Session, researcher: User
    ) -> None:
        """Demotion to viewer takes away writing, including on their own work."""
        author = make_user(
            db, email="demoted@example.org", username="demoted", role=UserRole.RESEARCHER
        )
        headers = auth_headers(client, "demoted")

        created = client.post(
            "/api/v1/projects",
            json={"name": "Before demotion", "code": "dem-1", "is_public": True},
            headers=headers,
        )
        assert created.status_code == 201
        project_id = created.json()["id"]

        access.grant(db, author, Module.ARCHAEOLOGY, ModuleLevel.VIEWER)
        db.flush()

        patched = client.patch(
            f"/api/v1/projects/{project_id}",
            json={"name": "After demotion"},
            headers=headers,
        )
        assert patched.status_code == 403

        # They can still read it — authorship is not revoked, only writing.
        assert client.get(f"/api/v1/projects/{project_id}", headers=headers).status_code == 200

    def test_an_editor_may_edit_a_colleagues_record_without_approving_it(
        self, client: TestClient, db: Session, researcher: User, project: dict
    ) -> None:
        editor = make_user(
            db,
            email="editor@example.org",
            username="editor",
            role=UserRole.VISITOR,
            modules={Module.ARCHAEOLOGY: ModuleLevel.EDITOR},
        )
        client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": str(editor.id), "role": "researcher"},
            headers=auth_headers(client, "researcher"),
        )

        site = client.post(
            "/api/v1/sites",
            json={"project_id": project["id"], "name": "Editor's site", "code": "ES"},
            headers=auth_headers(client, "editor"),
        )
        assert site.status_code == 201, site.text
        # An editor's own work is trusted, so it does not queue for review.
        assert site.json()["review_status"] == "approved"

        # But approving someone else's is a supervisor's job.
        refused = client.post(
            f"/api/v1/sites/{site.json()['id']}/approve",
            json={},
            headers=auth_headers(client, "editor"),
        )
        assert refused.status_code == 403


# --------------------------------------------------------------------------
# The administration endpoints
# --------------------------------------------------------------------------
class TestAccessEndpoints:
    def test_a_user_can_read_their_own_access(
        self, client: TestClient, db: Session, researcher: User
    ) -> None:
        response = client.get("/api/v1/users/me/access", headers=auth_headers(client, "researcher"))
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["is_platform_admin"] is False
        assert body["access"] == {"archaeology": "supervisor"}

    def test_an_administrator_reports_holding_everything_implicitly(
        self, client: TestClient, db: Session, admin: User
    ) -> None:
        body = client.get("/api/v1/users/me/access", headers=auth_headers(client, "admin")).json()

        assert body["is_platform_admin"] is True
        # Empty is not the same as "no access" — the flag says which it is.
        assert body["access"] == {}

    def test_an_administrator_can_grant_and_revoke(
        self, client: TestClient, db: Session, admin: User, student: User
    ) -> None:
        headers = auth_headers(client, "admin")

        granted = client.put(
            f"/api/v1/users/{student.id}/access",
            json={"module": "museum", "level": "editor", "note": "Cataloguing the 2024 finds"},
            headers=headers,
        )
        assert granted.status_code == 200, granted.text
        assert granted.json()["access"] == {"archaeology": "contributor", "museum": "editor"}

        revoked = client.delete(f"/api/v1/users/{student.id}/access/museum", headers=headers)
        assert revoked.status_code == 200
        assert revoked.json()["access"] == {"archaeology": "contributor"}

    def test_revoking_access_nobody_holds_is_reported(
        self, client: TestClient, db: Session, admin: User, student: User
    ) -> None:
        response = client.delete(
            f"/api/v1/users/{student.id}/access/inventory", headers=auth_headers(client, "admin")
        )
        assert response.status_code == 404

    def test_granting_to_a_platform_administrator_is_refused(
        self, client: TestClient, db: Session, admin: User
    ) -> None:
        other = make_user(db, email="admin2@example.org", username="admin2", role=UserRole.ADMIN)

        response = client.put(
            f"/api/v1/users/{other.id}/access",
            json={"module": "museum", "level": "viewer"},
            headers=auth_headers(client, "admin"),
        )
        assert response.status_code == 400
        assert "already hold" in response.json()["detail"]

    def test_only_administrators_may_grant(
        self, client: TestClient, db: Session, researcher: User, student: User
    ) -> None:
        response = client.put(
            f"/api/v1/users/{student.id}/access",
            json={"module": "museum", "level": "administrator"},
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 403

    def test_a_user_cannot_read_anothers_access(
        self, client: TestClient, db: Session, researcher: User, student: User
    ) -> None:
        response = client.get(
            f"/api/v1/users/{student.id}/access", headers=auth_headers(client, "researcher")
        )
        assert response.status_code == 403

    def test_granting_takes_effect_without_signing_in_again(
        self, client: TestClient, db: Session, admin: User
    ) -> None:
        newcomer = make_user(
            db, email="newcomer@example.org", username="newcomer", role=UserRole.VISITOR
        )
        headers = auth_headers(client, "newcomer")

        before = client.get("/api/v1/users/me/access", headers=headers).json()
        assert before["access"] == {"archaeology": "viewer"}

        client.put(
            f"/api/v1/users/{newcomer.id}/access",
            json={"module": "inventory", "level": "contributor"},
            headers=auth_headers(client, "admin"),
        )

        # Same token, no re-login: access lives in the database, not the token.
        after = client.get("/api/v1/users/me/access", headers=headers).json()
        assert after["access"]["inventory"] == "contributor"

    def _create_account(self, client: TestClient, username: str, **extra: object) -> dict:
        response = client.post(
            "/api/v1/users",
            json={
                "email": f"{username}@example.org",
                "username": username,
                "full_name": username.title(),
                "password": "StrongPassword1",
                "role": "student",
                **extra,
            },
            headers=auth_headers(client, "admin"),
        )
        assert response.status_code == 201, response.text
        return client.get(
            f"/api/v1/users/{response.json()['id']}/access", headers=auth_headers(client, "admin")
        ).json()

    def test_an_account_created_without_a_map_gets_the_role_default(
        self, client: TestClient, db: Session, admin: User
    ) -> None:
        created = self._create_account(client, "defaulted")
        assert created["access"] == {"archaeology": "contributor"}

    def test_an_explicit_map_replaces_the_default_rather_than_adding_to_it(
        self, client: TestClient, db: Session, admin: User
    ) -> None:
        """A collections manager with no business in the trenches.

        If the map were additive, every account would carry archaeology access
        whether or not the person has any use for it, and the spec's "no
        archaeology" user could not be created at all.
        """
        created = self._create_account(
            client,
            "collections",
            module_access={"museum": "administrator", "inventory": "editor"},
        )
        assert created["access"] == {"museum": "administrator", "inventory": "editor"}
        assert "archaeology" not in created["access"]

    def test_an_account_can_be_created_with_no_module_access_at_all(
        self, client: TestClient, db: Session, admin: User
    ) -> None:
        """Somebody whose access is decided later, not on the day they join."""
        created = self._create_account(client, "pending", module_access={})
        assert created["access"] == {}
