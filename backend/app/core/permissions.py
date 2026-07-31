"""Authorisation policy.

Access is decided by combining three independent sources, and the *most
permissive* of them wins:

1. **Global role** — a ceiling on what a user may ever do. A visitor cannot
   write anything, no matter what grants exist.
2. **Project membership** — the usual way access is granted: joining a
   project's team confers a level on everything inside it.
3. **Explicit record grants** — rows in ``record_permissions`` for sharing a
   single record outside the team.

Ownership and the public flag are shortcuts on top of those: an owner always
holds ``OWNER`` on their record, and a public record is readable by anyone,
including unauthenticated visitors.

Every check happens here rather than in the endpoints, so there is one place
to audit and one place to change.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC
from typing import Any

from sqlalchemy import and_, false, or_, select, true
from sqlalchemy.orm import Session

from app.models.enums import (
    PermissionLevel,
    ProjectRole,
    ResourceType,
    ReviewStatus,
    UserRole,
)
from app.models.project import ProjectMembership
from app.models.user import RecordPermission, User


class Capability(str, enum.Enum):
    """Global, record-independent abilities."""

    CREATE_PROJECT = "create_project"
    CREATE_RECORD = "create_record"
    UPLOAD_FILE = "upload_file"
    APPROVE_SUBMISSION = "approve_submission"
    MANAGE_USERS = "manage_users"
    MANAGE_TAXONOMY = "manage_taxonomy"
    MANAGE_SYSTEM = "manage_system"
    VIEW_ACTIVITY_LOG = "view_activity_log"
    DELETE_PROJECT = "delete_project"
    EXPORT_DATA = "export_data"


#: Minimum global role for each capability. Anything not listed is admin-only.
_CAPABILITY_MINIMUM: dict[Capability, UserRole] = {
    Capability.CREATE_PROJECT: UserRole.RESEARCHER,
    Capability.CREATE_RECORD: UserRole.STUDENT,
    Capability.UPLOAD_FILE: UserRole.STUDENT,
    Capability.APPROVE_SUBMISSION: UserRole.RESEARCHER,
    Capability.EXPORT_DATA: UserRole.STUDENT,
    Capability.VIEW_ACTIVITY_LOG: UserRole.RESEARCHER,
    Capability.MANAGE_USERS: UserRole.ADMIN,
    Capability.MANAGE_TAXONOMY: UserRole.ADMIN,
    Capability.MANAGE_SYSTEM: UserRole.ADMIN,
    # Deleting an entire project is destructive and irreversible for students
    # and researchers alike; only the project's director or an admin may do it,
    # which is enforced in ``can_delete`` rather than by role alone.
    Capability.DELETE_PROJECT: UserRole.ADMIN,
}

#: How a project role maps onto a permission level for the project's contents.
_PROJECT_ROLE_LEVEL: dict[ProjectRole, PermissionLevel] = {
    ProjectRole.DIRECTOR: PermissionLevel.OWNER,
    ProjectRole.RESEARCHER: PermissionLevel.EDITOR,
    ProjectRole.STUDENT: PermissionLevel.VIEWER,
    ProjectRole.OBSERVER: PermissionLevel.VIEWER,
}


def has_capability(user: User | None, capability: Capability) -> bool:
    """Check a global ability, ignoring any particular record."""
    if user is None or not user.is_active:
        return False
    if user.role is UserRole.ADMIN:
        return True
    minimum = _CAPABILITY_MINIMUM.get(capability, UserRole.ADMIN)
    return user.role >= minimum


# --------------------------------------------------------------------------
# Record-level checks
# --------------------------------------------------------------------------
def _record_owner_id(record: Any) -> uuid.UUID | None:
    return getattr(record, "owner_id", None)


def _record_is_public(record: Any) -> bool:
    return bool(getattr(record, "is_public", False))


def resolve_project_id(session: Session, record: Any) -> uuid.UUID | None:
    """Find the project a record belongs to.

    Sites, contexts and media carry the link directly or one hop away; the
    walk stops as soon as a project id is found.
    """
    # Import here to avoid a cycle: models import nothing from this module.
    from app.models.artifact import Artifact
    from app.models.context import ExcavationContext
    from app.models.project import Project
    from app.models.site import Site

    if isinstance(record, Project):
        return record.id

    direct = getattr(record, "project_id", None)
    if direct is not None:
        return direct

    site_id = getattr(record, "site_id", None)
    if site_id is not None:
        return session.scalar(select(Site.project_id).where(Site.id == site_id))

    artifact_id = getattr(record, "artifact_id", None)
    if artifact_id is not None:
        return session.scalar(
            select(Site.project_id)
            .join(Artifact, Artifact.site_id == Site.id)
            .where(Artifact.id == artifact_id)
        )

    context_id = getattr(record, "context_id", None)
    if context_id is not None:
        return session.scalar(
            select(Site.project_id)
            .join(ExcavationContext, ExcavationContext.site_id == Site.id)
            .where(ExcavationContext.id == context_id)
        )
    return None


def project_level(
    session: Session, user: User, project_id: uuid.UUID | None
) -> PermissionLevel | None:
    """The level a user holds through team membership, if any."""
    if project_id is None:
        return None
    membership = session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user.id,
        )
    )
    if membership is None:
        return None
    return _PROJECT_ROLE_LEVEL[membership.role]


def explicit_level(
    session: Session, user: User, resource_type: ResourceType, resource_id: uuid.UUID
) -> PermissionLevel | None:
    """The level from an explicit per-record grant, if any and not expired."""
    from datetime import datetime

    grant = session.scalar(
        select(RecordPermission).where(
            RecordPermission.resource_type == resource_type,
            RecordPermission.resource_id == resource_id,
            RecordPermission.user_id == user.id,
        )
    )
    if grant is None:
        return None
    if grant.expires_at is not None and grant.expires_at <= datetime.now(UTC):
        return None
    return grant.level


def effective_level(
    session: Session,
    user: User | None,
    record: Any,
    resource_type: ResourceType,
) -> PermissionLevel | None:
    """Highest level ``user`` holds on ``record``; ``None`` means no access.

    Note that this reports *access*, not *ability*: a student who is the owner
    of a record gets ``OWNER`` here, but :func:`can_delete` still refuses to
    let them delete a project. Role ceilings are applied by the ``can_*``
    helpers, not by this function.
    """
    if user is not None and user.is_active and user.role is UserRole.ADMIN:
        return PermissionLevel.OWNER

    levels: list[PermissionLevel] = []

    if _record_is_public(record):
        levels.append(PermissionLevel.VIEWER)

    if user is not None and user.is_active:
        owner_id = _record_owner_id(record)
        if owner_id is not None and owner_id == user.id:
            levels.append(PermissionLevel.OWNER)

        via_project = project_level(session, user, resolve_project_id(session, record))
        if via_project is not None:
            levels.append(via_project)

        record_id = getattr(record, "id", None)
        if record_id is not None:
            via_grant = explicit_level(session, user, resource_type, record_id)
            if via_grant is not None:
                levels.append(via_grant)

    if not levels:
        return None
    return max(levels, key=lambda level: level.rank)


def can_view(session: Session, user: User | None, record: Any, resource_type: ResourceType) -> bool:
    """Anyone with any level may read.

    Records still awaiting approval are hidden from users who could not act on
    them, so an unreviewed student submission does not appear in public
    listings before a researcher has seen it.
    """
    level = effective_level(session, user, record, resource_type)
    if level is None:
        return False

    review_status = getattr(record, "review_status", None)
    if review_status in (ReviewStatus.PENDING, ReviewStatus.DRAFT, ReviewStatus.REJECTED):
        # Only the owner and users who can edit the record see it pre-approval.
        owner_id = _record_owner_id(record)
        is_owner = user is not None and owner_id is not None and owner_id == user.id
        return is_owner or level >= PermissionLevel.EDITOR
    return True


def can_edit(session: Session, user: User | None, record: Any, resource_type: ResourceType) -> bool:
    """Editing needs an ``EDITOR`` level *and* a role that may write at all."""
    if user is None or not user.is_active or user.role is UserRole.VISITOR:
        return False
    level = effective_level(session, user, record, resource_type)
    return level is not None and level >= PermissionLevel.EDITOR


def can_delete(
    session: Session, user: User | None, record: Any, resource_type: ResourceType
) -> bool:
    """Deletion needs ``OWNER``; deleting a project additionally needs the
    project director role or an administrator, per the specification's rule
    that students may never delete projects."""
    if user is None or not user.is_active or user.role is UserRole.VISITOR:
        return False
    if user.role is UserRole.ADMIN:
        return True

    level = effective_level(session, user, record, resource_type)
    if level is None or level < PermissionLevel.OWNER:
        return False

    if resource_type is ResourceType.PROJECT:
        if user.role < UserRole.RESEARCHER:
            return False
        membership = session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == getattr(record, "id", None),
                ProjectMembership.user_id == user.id,
            )
        )
        is_director = membership is not None and membership.role is ProjectRole.DIRECTOR
        return is_director or _record_owner_id(record) == user.id
    return True


def can_approve(
    session: Session, user: User | None, record: Any, resource_type: ResourceType
) -> bool:
    """Approving a submission needs the capability and edit rights on the
    record — a researcher may not approve work in a project they are not on."""
    if not has_capability(user, Capability.APPROVE_SUBMISSION):
        return False
    if user is not None and user.role is UserRole.ADMIN:
        return True
    return can_edit(session, user, record, resource_type)


def requires_approval(user: User | None) -> bool:
    """Whether records created by this user start as pending review.

    Students submit for approval; researchers and administrators do not.
    """
    return user is not None and user.role is UserRole.STUDENT


# --------------------------------------------------------------------------
# Query-level filtering
# --------------------------------------------------------------------------
# The ``can_*`` helpers above decide access for *one* record already loaded.
# Listings cannot work that way — fetching every row to filter in Python would
# neither paginate nor scale — so the same rules are expressed a second time as
# SQL predicates.
#
# Two expressions of one policy is exactly the kind of thing that drifts apart,
# so ``tests/test_visibility_sql.py`` asserts they agree across a matrix of
# users, records and review states. Change one and that test says to change the
# other.


def _member_projects(user: User, roles: list[ProjectRole] | None = None) -> Any:
    """Subquery of the project ids a user belongs to, optionally by role."""
    statement = select(ProjectMembership.project_id).where(ProjectMembership.user_id == user.id)
    if roles is not None:
        statement = statement.where(ProjectMembership.role.in_(roles))
    return statement


def _scope_to_projects(model: Any, project_ids: Any) -> Any:
    """Relate ``model`` to a set of project ids, whatever its distance.

    Projects match on their own id, sites carry ``project_id`` directly, and
    artifacts and contexts reach it through their site. Returns ``None`` for a
    model with no route to a project — which correctly contributes no clause,
    leaving such records reachable only by ownership or an explicit grant.
    """
    from app.models.project import Project
    from app.models.site import Site

    if model is Project:
        return model.id.in_(project_ids)
    if hasattr(model, "project_id"):
        return model.project_id.in_(project_ids)
    if hasattr(model, "site_id"):
        return model.site_id.in_(select(Site.id).where(Site.project_id.in_(project_ids)))
    return None


def _granted_records(
    user: User, resource_type: ResourceType, levels: list[PermissionLevel] | None = None
) -> Any:
    """Subquery of record ids explicitly granted to a user."""
    statement = select(RecordPermission.resource_id).where(
        RecordPermission.user_id == user.id,
        RecordPermission.resource_type == resource_type,
    )
    if levels is not None:
        statement = statement.where(RecordPermission.level.in_(levels))
    return statement


def _review_visibility_filter(user: User | None, model: Any, resource_type: ResourceType) -> Any:
    """Restrict unapproved records to their author and to potential approvers."""
    if not hasattr(model, "review_status"):
        return None

    approved = model.review_status == ReviewStatus.APPROVED

    if user is None or not user.is_active:
        return approved

    allowed: list[Any] = [approved, model.owner_id == user.id]

    editor_clause = _scope_to_projects(
        model, _member_projects(user, [ProjectRole.DIRECTOR, ProjectRole.RESEARCHER])
    )
    if editor_clause is not None:
        allowed.append(editor_clause)

    allowed.append(
        model.id.in_(
            _granted_records(user, resource_type, [PermissionLevel.EDITOR, PermissionLevel.OWNER])
        )
    )
    return or_(*allowed)


def visibility_filter(user: User | None, model: Any, resource_type: ResourceType) -> Any:
    """SQL predicate selecting the rows ``user`` may read.

    Mirrors :func:`can_view`, including the rule that records awaiting review
    stay hidden from everyone but their author and those who could act on them.
    """
    if user is not None and user.is_active and user.role is UserRole.ADMIN:
        return true()

    clauses: list[Any] = [model.is_public.is_(True)]

    if user is not None and user.is_active:
        clauses.append(model.owner_id == user.id)

        membership_clause = _scope_to_projects(model, _member_projects(user))
        if membership_clause is not None:
            clauses.append(membership_clause)

        clauses.append(model.id.in_(_granted_records(user, resource_type)))

    access = or_(*clauses)
    review = _review_visibility_filter(user, model, resource_type)
    return access if review is None else and_(access, review)


def editable_filter(user: User | None, model: Any, resource_type: ResourceType) -> Any:
    """SQL predicate selecting the rows ``user`` may modify.

    Mirrors :func:`can_edit` for queries that act on many rows at once.
    """
    if user is None or not user.is_active or user.role is UserRole.VISITOR:
        return false()
    if user.role is UserRole.ADMIN:
        return true()

    clauses: list[Any] = [model.owner_id == user.id]

    editor_clause = _scope_to_projects(
        model, _member_projects(user, [ProjectRole.DIRECTOR, ProjectRole.RESEARCHER])
    )
    if editor_clause is not None:
        clauses.append(editor_clause)

    clauses.append(
        model.id.in_(
            _granted_records(user, resource_type, [PermissionLevel.EDITOR, PermissionLevel.OWNER])
        )
    )
    return or_(*clauses)
