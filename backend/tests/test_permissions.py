"""Tests for the authorisation policy.

These exercise :mod:`app.core.permissions` directly, because the policy is what
every future endpoint will depend on — a regression here is a data leak, not a
broken page.
"""

from __future__ import annotations

from datetime import UTC

import pytest
from sqlalchemy.orm import Session

from app.core.permissions import (
    Capability,
    can_approve,
    can_delete,
    can_edit,
    can_view,
    effective_level,
    has_capability,
    requires_approval,
)
from app.models import (
    PermissionLevel,
    Project,
    ProjectMembership,
    ProjectRole,
    RecordPermission,
    ResourceType,
    ReviewStatus,
    Site,
    User,
    UserRole,
)


@pytest.fixture
def project(db: Session, researcher: User) -> Project:
    project = Project(
        name="Excavation at Test Hill",
        code="TEST-01",
        slug="test-01",
        owner_id=researcher.id,
        is_public=False,
    )
    db.add(project)
    db.flush()
    db.add(
        ProjectMembership(project_id=project.id, user_id=researcher.id, role=ProjectRole.DIRECTOR)
    )
    db.flush()
    return project


@pytest.fixture
def site(db: Session, project: Project, researcher: User) -> Site:
    site = Site(
        project_id=project.id,
        name="Test Hill",
        code="TH",
        owner_id=researcher.id,
        is_public=False,
    )
    db.add(site)
    db.flush()
    return site


class TestRoleOrdering:
    def test_roles_compare_by_privilege(self) -> None:
        assert UserRole.VISITOR < UserRole.STUDENT < UserRole.RESEARCHER < UserRole.ADMIN
        assert UserRole.ADMIN >= UserRole.RESEARCHER
        assert not UserRole.STUDENT >= UserRole.RESEARCHER

    def test_permission_levels_compare(self) -> None:
        assert PermissionLevel.VIEWER < PermissionLevel.EDITOR < PermissionLevel.OWNER


class TestCapabilities:
    @pytest.mark.parametrize(
        ("role", "capability", "expected"),
        [
            (UserRole.VISITOR, Capability.CREATE_RECORD, False),
            (UserRole.VISITOR, Capability.UPLOAD_FILE, False),
            (UserRole.VISITOR, Capability.CREATE_PROJECT, False),
            (UserRole.STUDENT, Capability.CREATE_RECORD, True),
            (UserRole.STUDENT, Capability.UPLOAD_FILE, True),
            (UserRole.STUDENT, Capability.CREATE_PROJECT, False),
            (UserRole.STUDENT, Capability.APPROVE_SUBMISSION, False),
            (UserRole.STUDENT, Capability.MANAGE_USERS, False),
            (UserRole.RESEARCHER, Capability.CREATE_PROJECT, True),
            (UserRole.RESEARCHER, Capability.APPROVE_SUBMISSION, True),
            (UserRole.RESEARCHER, Capability.MANAGE_USERS, False),
            (UserRole.RESEARCHER, Capability.MANAGE_SYSTEM, False),
            (UserRole.ADMIN, Capability.MANAGE_USERS, True),
            (UserRole.ADMIN, Capability.MANAGE_SYSTEM, True),
            (UserRole.ADMIN, Capability.DELETE_PROJECT, True),
        ],
    )
    def test_capability_matrix(
        self, db: Session, role: UserRole, capability: Capability, expected: bool
    ) -> None:
        from tests.conftest import make_user

        user = make_user(db, email=f"{role.value}@x.org", username=role.value, role=role)
        assert has_capability(user, capability) is expected

    def test_anonymous_has_no_capabilities(self) -> None:
        for capability in Capability:
            assert has_capability(None, capability) is False

    def test_inactive_user_has_no_capabilities(self, db: Session) -> None:
        from tests.conftest import make_user

        user = make_user(
            db, email="off@x.org", username="off", role=UserRole.ADMIN, is_active=False
        )
        assert has_capability(user, Capability.MANAGE_USERS) is False


class TestVisibility:
    def test_anonymous_sees_public_records_only(self, db: Session, site: Site) -> None:
        assert can_view(db, None, site, ResourceType.SITE) is False
        site.is_public = True
        assert can_view(db, None, site, ResourceType.SITE) is True

    def test_anonymous_can_never_edit_a_public_record(self, db: Session, site: Site) -> None:
        site.is_public = True
        assert can_edit(db, None, site, ResourceType.SITE) is False
        assert can_delete(db, None, site, ResourceType.SITE) is False

    def test_visitor_cannot_edit_even_a_public_record(
        self, db: Session, site: Site, visitor: User
    ) -> None:
        site.is_public = True
        assert can_view(db, visitor, site, ResourceType.SITE) is True
        assert can_edit(db, visitor, site, ResourceType.SITE) is False

    def test_non_member_cannot_see_a_private_record(
        self, db: Session, site: Site, student: User
    ) -> None:
        assert can_view(db, student, site, ResourceType.SITE) is False

    def test_admin_sees_everything(self, db: Session, site: Site, admin: User) -> None:
        assert effective_level(db, admin, site, ResourceType.SITE) is PermissionLevel.OWNER
        assert can_view(db, admin, site, ResourceType.SITE) is True
        assert can_edit(db, admin, site, ResourceType.SITE) is True


class TestProjectMembership:
    def test_membership_grants_access_to_project_contents(
        self, db: Session, project: Project, site: Site, student: User
    ) -> None:
        assert can_view(db, student, site, ResourceType.SITE) is False

        db.add(
            ProjectMembership(project_id=project.id, user_id=student.id, role=ProjectRole.STUDENT)
        )
        db.flush()

        # A student member reads the project's sites but does not edit them.
        assert can_view(db, student, site, ResourceType.SITE) is True
        assert can_edit(db, student, site, ResourceType.SITE) is False

    def test_researcher_member_can_edit_project_contents(
        self, db: Session, project: Project, site: Site
    ) -> None:
        from tests.conftest import make_user

        colleague = make_user(db, email="c@x.org", username="colleague", role=UserRole.RESEARCHER)
        db.add(
            ProjectMembership(
                project_id=project.id, user_id=colleague.id, role=ProjectRole.RESEARCHER
            )
        )
        db.flush()
        assert can_edit(db, colleague, site, ResourceType.SITE) is True
        assert can_delete(db, colleague, site, ResourceType.SITE) is False

    def test_observer_reads_but_does_not_write(
        self, db: Session, project: Project, site: Site, student: User
    ) -> None:
        db.add(
            ProjectMembership(project_id=project.id, user_id=student.id, role=ProjectRole.OBSERVER)
        )
        db.flush()
        assert can_view(db, student, site, ResourceType.SITE) is True
        assert can_edit(db, student, site, ResourceType.SITE) is False


class TestOwnership:
    def test_students_may_edit_their_own_records(
        self, db: Session, project: Project, student: User
    ) -> None:
        own_site = Site(
            project_id=project.id, name="Student's site", code="SS", owner_id=student.id
        )
        db.add(own_site)
        db.flush()
        assert can_edit(db, student, own_site, ResourceType.SITE) is True

    def test_students_may_not_delete_projects(
        self, db: Session, project: Project, student: User
    ) -> None:
        """Even as the record's owner — the specification is explicit."""
        project.owner_id = student.id
        db.add(project)
        db.flush()
        assert can_delete(db, student, project, ResourceType.PROJECT) is False

    def test_project_director_may_delete_the_project(
        self, db: Session, project: Project, researcher: User
    ) -> None:
        assert can_delete(db, researcher, project, ResourceType.PROJECT) is True

    def test_researcher_without_directorship_may_not_delete_the_project(
        self, db: Session, project: Project
    ) -> None:
        from tests.conftest import make_user

        other = make_user(db, email="o@x.org", username="other", role=UserRole.RESEARCHER)
        db.add(
            ProjectMembership(project_id=project.id, user_id=other.id, role=ProjectRole.RESEARCHER)
        )
        db.flush()
        assert can_delete(db, other, project, ResourceType.PROJECT) is False


class TestExplicitGrants:
    def test_grant_shares_one_record_outside_the_team(
        self, db: Session, site: Site, student: User, researcher: User
    ) -> None:
        assert can_view(db, student, site, ResourceType.SITE) is False

        db.add(
            RecordPermission(
                resource_type=ResourceType.SITE,
                resource_id=site.id,
                user_id=student.id,
                level=PermissionLevel.EDITOR,
                granted_by_id=researcher.id,
            )
        )
        db.flush()

        assert can_view(db, student, site, ResourceType.SITE) is True
        assert can_edit(db, student, site, ResourceType.SITE) is True

    def test_expired_grant_confers_nothing(self, db: Session, site: Site, student: User) -> None:
        from datetime import datetime, timedelta

        db.add(
            RecordPermission(
                resource_type=ResourceType.SITE,
                resource_id=site.id,
                user_id=student.id,
                level=PermissionLevel.EDITOR,
                expires_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        db.flush()
        assert can_view(db, student, site, ResourceType.SITE) is False

    def test_grant_on_one_record_does_not_leak_to_another(
        self, db: Session, project: Project, site: Site, student: User
    ) -> None:
        other_site = Site(project_id=project.id, name="Other", code="OT")
        db.add(other_site)
        db.flush()
        db.add(
            RecordPermission(
                resource_type=ResourceType.SITE,
                resource_id=site.id,
                user_id=student.id,
                level=PermissionLevel.EDITOR,
            )
        )
        db.flush()
        assert can_view(db, student, other_site, ResourceType.SITE) is False


class TestApprovalWorkflow:
    def test_student_submissions_need_approval(
        self, db: Session, student: User, researcher: User, admin: User, visitor: User
    ) -> None:
        assert requires_approval(student) is True
        assert requires_approval(researcher) is False
        assert requires_approval(admin) is False
        assert requires_approval(None) is False

    def test_pending_records_are_hidden_from_readers(
        self, db: Session, project: Project, student: User
    ) -> None:
        pending = Site(
            project_id=project.id,
            name="Unreviewed",
            code="UR",
            owner_id=student.id,
            is_public=True,
            review_status=ReviewStatus.PENDING,
        )
        db.add(pending)
        db.flush()

        # Public, but not yet approved: anonymous readers must not see it.
        assert can_view(db, None, pending, ResourceType.SITE) is False
        # Its author still sees their own submission.
        assert can_view(db, student, pending, ResourceType.SITE) is True

    def test_pending_records_are_visible_to_approvers(
        self, db: Session, project: Project, student: User, researcher: User
    ) -> None:
        pending = Site(
            project_id=project.id,
            name="Unreviewed",
            code="UR2",
            owner_id=student.id,
            review_status=ReviewStatus.PENDING,
        )
        db.add(pending)
        db.flush()
        assert can_view(db, researcher, pending, ResourceType.SITE) is True
        assert can_approve(db, researcher, pending, ResourceType.SITE) is True

    def test_students_cannot_approve(self, db: Session, project: Project, student: User) -> None:
        own = Site(
            project_id=project.id,
            name="Mine",
            code="MN",
            owner_id=student.id,
            review_status=ReviewStatus.PENDING,
        )
        db.add(own)
        db.flush()
        assert can_approve(db, student, own, ResourceType.SITE) is False

    def test_researcher_cannot_approve_outside_their_projects(
        self, db: Session, project: Project, student: User
    ) -> None:
        from tests.conftest import make_user

        outsider = make_user(db, email="out@x.org", username="outsider", role=UserRole.RESEARCHER)
        pending = Site(
            project_id=project.id,
            name="Not theirs",
            code="NT",
            owner_id=student.id,
            review_status=ReviewStatus.PENDING,
        )
        db.add(pending)
        db.flush()
        assert can_approve(db, outsider, pending, ResourceType.SITE) is False
