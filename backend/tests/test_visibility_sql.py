"""The SQL visibility filter must agree with the Python permission check.

``can_view`` decides access for one loaded record; ``visibility_filter``
expresses the same policy as a SQL predicate so listings can paginate. Two
statements of one rule drift apart unless something holds them together — this
test is that something.

If you change one and not the other, the matrix below fails and names the case.
"""

from __future__ import annotations

import itertools

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import can_edit, can_view, editable_filter, visibility_filter
from app.models import (
    Artifact,
    ExcavationContext,
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
from tests.conftest import make_user


@pytest.fixture
def world(db: Session) -> dict:
    """A small world containing every combination the policy distinguishes."""
    owner = make_user(db, email="owner@x.org", username="owner", role=UserRole.RESEARCHER)
    member_researcher = make_user(
        db, email="mr@x.org", username="memberresearcher", role=UserRole.RESEARCHER
    )
    member_student = make_user(db, email="ms@x.org", username="memberstudent")
    outsider = make_user(db, email="out@x.org", username="outsider")
    granted = make_user(db, email="grant@x.org", username="granted")
    visitor = make_user(db, email="vis@x.org", username="visitorx", role=UserRole.VISITOR)
    admin = make_user(db, email="adm@x.org", username="adminx", role=UserRole.ADMIN)

    project = Project(name="Policy Project", code="POL-1", slug="pol-1", owner_id=owner.id)
    public_project = Project(
        name="Open Project", code="POL-2", slug="pol-2", owner_id=owner.id, is_public=True
    )
    db.add_all([project, public_project])
    db.flush()

    db.add_all(
        [
            ProjectMembership(project_id=project.id, user_id=owner.id, role=ProjectRole.DIRECTOR),
            ProjectMembership(
                project_id=project.id,
                user_id=member_researcher.id,
                role=ProjectRole.RESEARCHER,
            ),
            ProjectMembership(
                project_id=project.id, user_id=member_student.id, role=ProjectRole.STUDENT
            ),
        ]
    )

    sites = {
        "private_approved": Site(
            project_id=project.id, name="Private", code="P1", owner_id=owner.id
        ),
        "public_approved": Site(
            project_id=project.id, name="Public", code="P2", owner_id=owner.id, is_public=True
        ),
        "public_pending": Site(
            project_id=project.id,
            name="Pending",
            code="P3",
            owner_id=member_student.id,
            is_public=True,
            review_status=ReviewStatus.PENDING,
        ),
        "private_rejected": Site(
            project_id=project.id,
            name="Rejected",
            code="P4",
            owner_id=member_student.id,
            review_status=ReviewStatus.REJECTED,
        ),
        "orphan_public": Site(
            project_id=public_project.id, name="Orphan", code="P5", is_public=True
        ),
    }
    db.add_all(sites.values())
    db.flush()

    db.add(
        RecordPermission(
            resource_type=ResourceType.SITE,
            resource_id=sites["private_approved"].id,
            user_id=granted.id,
            level=PermissionLevel.VIEWER,
        )
    )

    artifact = Artifact(
        site_id=sites["private_approved"].id, inventory_number="A-1", owner_id=owner.id
    )
    context = ExcavationContext(
        site_id=sites["private_approved"].id, context_number="C-1", owner_id=owner.id
    )
    db.add_all([artifact, context])
    db.flush()

    return {
        "users": {
            "owner": owner,
            "member_researcher": member_researcher,
            "member_student": member_student,
            "outsider": outsider,
            "granted": granted,
            "visitor": visitor,
            "admin": admin,
            "anonymous": None,
        },
        "sites": sites,
        "project": project,
        "public_project": public_project,
        "artifact": artifact,
        "context": context,
    }


USER_KEYS = [
    "owner",
    "member_researcher",
    "member_student",
    "outsider",
    "granted",
    "visitor",
    "admin",
    "anonymous",
]
SITE_KEYS = [
    "private_approved",
    "public_approved",
    "public_pending",
    "private_rejected",
    "orphan_public",
]


class TestSitesAgree:
    @pytest.mark.parametrize(("user_key", "site_key"), itertools.product(USER_KEYS, SITE_KEYS))
    def test_can_view_matches_visibility_filter(
        self, db: Session, world: dict, user_key: str, site_key: str
    ) -> None:
        user: User | None = world["users"][user_key]
        site: Site = world["sites"][site_key]

        python_says = can_view(db, user, site, ResourceType.SITE)
        sql_says = (
            db.scalar(
                select(Site.id).where(
                    Site.id == site.id, visibility_filter(user, Site, ResourceType.SITE)
                )
            )
            is not None
        )

        assert (
            python_says == sql_says
        ), f"{user_key} vs {site_key}: can_view={python_says} but visibility_filter={sql_says}"

    @pytest.mark.parametrize(("user_key", "site_key"), itertools.product(USER_KEYS, SITE_KEYS))
    def test_can_edit_matches_editable_filter(
        self, db: Session, world: dict, user_key: str, site_key: str
    ) -> None:
        user: User | None = world["users"][user_key]
        site: Site = world["sites"][site_key]

        python_says = can_edit(db, user, site, ResourceType.SITE)
        sql_says = (
            db.scalar(
                select(Site.id).where(
                    Site.id == site.id, editable_filter(user, Site, ResourceType.SITE)
                )
            )
            is not None
        )

        assert (
            python_says == sql_says
        ), f"{user_key} vs {site_key}: can_edit={python_says} but editable_filter={sql_says}"


class TestNestedRecordsAgree:
    """Artifacts and contexts reach their project through a site, which is the
    part of the SQL translation most likely to be got wrong."""

    @pytest.mark.parametrize("user_key", USER_KEYS)
    def test_artifacts(self, db: Session, world: dict, user_key: str) -> None:
        user = world["users"][user_key]
        artifact = world["artifact"]
        python_says = can_view(db, user, artifact, ResourceType.ARTIFACT)
        sql_says = (
            db.scalar(
                select(Artifact.id).where(
                    Artifact.id == artifact.id,
                    visibility_filter(user, Artifact, ResourceType.ARTIFACT),
                )
            )
            is not None
        )
        assert python_says == sql_says, f"{user_key}: {python_says} vs {sql_says}"

    @pytest.mark.parametrize("user_key", USER_KEYS)
    def test_contexts(self, db: Session, world: dict, user_key: str) -> None:
        user = world["users"][user_key]
        context = world["context"]
        python_says = can_view(db, user, context, ResourceType.CONTEXT)
        sql_says = (
            db.scalar(
                select(ExcavationContext.id).where(
                    ExcavationContext.id == context.id,
                    visibility_filter(user, ExcavationContext, ResourceType.CONTEXT),
                )
            )
            is not None
        )
        assert python_says == sql_says, f"{user_key}: {python_says} vs {sql_says}"


class TestProjectsAgree:
    @pytest.mark.parametrize("user_key", USER_KEYS)
    @pytest.mark.parametrize("project_key", ["project", "public_project"])
    def test_projects(self, db: Session, world: dict, user_key: str, project_key: str) -> None:
        user = world["users"][user_key]
        project = world[project_key]
        python_says = can_view(db, user, project, ResourceType.PROJECT)
        sql_says = (
            db.scalar(
                select(Project.id).where(
                    Project.id == project.id,
                    visibility_filter(user, Project, ResourceType.PROJECT),
                )
            )
            is not None
        )
        assert python_says == sql_says, f"{user_key}/{project_key}: {python_says} vs {sql_says}"


class TestSpecificExpectations:
    """A few cases spelled out, so the matrix cannot pass by both sides being
    wrong in the same way."""

    def test_outsider_sees_only_public_approved(self, db: Session, world: dict) -> None:
        outsider = world["users"]["outsider"]
        visible = set(
            db.scalars(
                select(Site.code).where(visibility_filter(outsider, Site, ResourceType.SITE))
            ).all()
        )
        assert visible == {"P2", "P5"}, "public but unapproved records must stay hidden"

    def test_student_author_sees_their_pending_record(self, db: Session, world: dict) -> None:
        student = world["users"]["member_student"]
        visible = set(
            db.scalars(
                select(Site.code).where(visibility_filter(student, Site, ResourceType.SITE))
            ).all()
        )
        assert {"P3", "P4"} <= visible, "authors must see their own submissions"

    def test_researcher_member_sees_pending_for_review(self, db: Session, world: dict) -> None:
        reviewer = world["users"]["member_researcher"]
        visible = set(
            db.scalars(
                select(Site.code).where(visibility_filter(reviewer, Site, ResourceType.SITE))
            ).all()
        )
        assert "P3" in visible, "reviewers must see what they are meant to review"

    def test_granted_user_sees_only_the_granted_record(self, db: Session, world: dict) -> None:
        granted = world["users"]["granted"]
        visible = set(
            db.scalars(
                select(Site.code).where(visibility_filter(granted, Site, ResourceType.SITE))
            ).all()
        )
        assert "P1" in visible
        assert "P4" not in visible, "a grant on one record must not leak to another"

    def test_admin_sees_everything(self, db: Session, world: dict) -> None:
        admin = world["users"]["admin"]
        visible = set(
            db.scalars(
                select(Site.code).where(visibility_filter(admin, Site, ResourceType.SITE))
            ).all()
        )
        assert visible == {"P1", "P2", "P3", "P4", "P5"}

    def test_anonymous_can_edit_nothing(self, db: Session, world: dict) -> None:
        assert (
            db.scalars(
                select(Site.code).where(editable_filter(None, Site, ResourceType.SITE))
            ).all()
            == []
        )
