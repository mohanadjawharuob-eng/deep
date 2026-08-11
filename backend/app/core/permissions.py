"""Authorisation policy.

Access is decided by combining four independent sources, and the *most
permissive* of them wins:

1. **Module access** — a ceiling, per functional area. A user with no grant on
   the museum module cannot write museum records however senior they are in
   archaeology. Held as rows in ``user_module_access``; see
   :class:`~app.models.enums.ModuleLevel` for what each level means.
2. **Project membership** — the usual way access is granted inside a module:
   joining a project's team confers a level on everything in it.
3. **Explicit record grants** — rows in ``record_permissions`` for sharing a
   single record outside the team.
4. **The global role** — reserved for administering the *platform* (users,
   taxonomy, settings). A platform administrator implicitly holds the top level
   in every module; every other role is silent about module access.

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
    Module,
    ModuleLevel,
    PermissionLevel,
    ProjectRole,
    ResourceType,
    ReviewStatus,
    UserRole,
)
from app.models.project import ProjectMembership
from app.models.user import RecordPermission, User


class Capability(str, enum.Enum):
    """A record-independent ability, checked against one module."""

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


#: Capabilities that are properties of the *platform*, not of any one module.
#: These belong to the global administrator role and are not reachable by being
#: senior in a module: running a museum's collection must not confer the
#: ability to create accounts.
PLATFORM_CAPABILITIES: frozenset[Capability] = frozenset(
    {Capability.MANAGE_USERS, Capability.MANAGE_TAXONOMY, Capability.MANAGE_SYSTEM}
)

#: Minimum level *within a module* for each module-scoped capability.
_CAPABILITY_MINIMUM: dict[Capability, ModuleLevel] = {
    Capability.CREATE_RECORD: ModuleLevel.CONTRIBUTOR,
    Capability.UPLOAD_FILE: ModuleLevel.CONTRIBUTOR,
    Capability.EXPORT_DATA: ModuleLevel.CONTRIBUTOR,
    Capability.CREATE_PROJECT: ModuleLevel.SUPERVISOR,
    Capability.APPROVE_SUBMISSION: ModuleLevel.SUPERVISOR,
    Capability.VIEW_ACTIVITY_LOG: ModuleLevel.SUPERVISOR,
    # Deleting an entire project is destructive and irreversible; the check in
    # ``can_delete`` additionally requires being the project's director, so this
    # level alone is not sufficient.
    Capability.DELETE_PROJECT: ModuleLevel.ADMINISTRATOR,
}

#: Which module each kind of record belongs to. Everything is archaeology
#: today; museum, inventory and the rest join this table as they are built.
_RESOURCE_MODULE: dict[ResourceType, Module] = {
    ResourceType.PROJECT: Module.ARCHAEOLOGY,
    ResourceType.SITE: Module.ARCHAEOLOGY,
    ResourceType.ARTIFACT: Module.ARCHAEOLOGY,
    ResourceType.CONTEXT: Module.ARCHAEOLOGY,
    ResourceType.PHOTOGRAPH: Module.ARCHAEOLOGY,
    ResourceType.DOCUMENT: Module.ARCHAEOLOGY,
    ResourceType.MODEL3D: Module.ARCHAEOLOGY,
    ResourceType.GIS_LAYER: Module.ARCHAEOLOGY,
    ResourceType.PUBLICATION: Module.ARCHAEOLOGY,
    ResourceType.MUSEUM_OBJECT: Module.MUSEUM,
    ResourceType.ACTIVITY: Module.ACTIVITIES,
    #: A user account is platform-wide, not the property of any module.
    ResourceType.USER: Module.MANAGEMENT,
}

#: Modules whose records are not project-scoped. Nothing in a museum store or
#: an equipment cupboard belongs to an excavation project, so the project
#: membership half of the policy has nothing to say about them and access is
#: decided by module level plus ownership alone. See :func:`flat_can_edit`.
FLAT_MODULES: frozenset[Module] = frozenset(
    {Module.MUSEUM, Module.INVENTORY, Module.SOCIAL_MEDIA, Module.MANAGEMENT, Module.ACTIVITIES}
)

#: The level a user gets in the archaeology module from their legacy global
#: role. Used when creating an account and by the backfill migration, so that
#: the behaviour described in the original role table is preserved exactly.
DEFAULT_MODULE_ACCESS: dict[UserRole, ModuleLevel | None] = {
    UserRole.VISITOR: ModuleLevel.VIEWER,
    UserRole.STUDENT: ModuleLevel.CONTRIBUTOR,
    # Researchers approve student work and start projects, which is supervision.
    UserRole.RESEARCHER: ModuleLevel.SUPERVISOR,
    # Administrators need no row: they hold every module implicitly.
    UserRole.ADMIN: None,
}

#: The modules a new account is seeded with, at the level its role implies.
#:
#: Archaeology is the platform's original module and has been seeded since the
#: beginning. Activities joins it because the hub and the calendar are the
#: institution's shared memory rather than one team's working area: a record of
#: what we did, what it cost and what permission it needed is only worth
#: keeping if everybody can open it, and a calendar half the staff cannot add a
#: day to is a calendar that goes stale in a fortnight.
#:
#: Everything else stays deliberate. Being able to read the kit list from the
#: 2019 season says nothing about whether you should see what a conservator is
#: paid.
SEEDED_MODULES: tuple[Module, ...] = (Module.ARCHAEOLOGY, Module.ACTIVITIES)

#: How a project role maps onto a permission level for the project's contents.
_PROJECT_ROLE_LEVEL: dict[ProjectRole, PermissionLevel] = {
    ProjectRole.DIRECTOR: PermissionLevel.OWNER,
    ProjectRole.RESEARCHER: PermissionLevel.EDITOR,
    ProjectRole.STUDENT: PermissionLevel.VIEWER,
    ProjectRole.OBSERVER: PermissionLevel.VIEWER,
}


def module_of(resource_type: ResourceType) -> Module:
    """Which module owns a kind of record."""
    return _RESOURCE_MODULE.get(resource_type, Module.ARCHAEOLOGY)


def module_level(user: User | None, module: Module) -> ModuleLevel | None:
    """The level ``user`` holds in ``module``; ``None`` means no access."""
    if user is None or not user.is_active:
        return None
    return user.level_in(module)


def has_module_access(user: User | None, module: Module, minimum: ModuleLevel) -> bool:
    level = module_level(user, module)
    return level is not None and level >= minimum


def has_capability(
    user: User | None,
    capability: Capability,
    module: Module = Module.ARCHAEOLOGY,
) -> bool:
    """Check a record-independent ability within one module.

    Platform capabilities ignore ``module`` entirely — they are the global
    administrator's, and no amount of seniority inside a module reaches them.
    """
    if user is None or not user.is_active:
        return False

    if capability in PLATFORM_CAPABILITIES:
        return user.role is UserRole.ADMIN

    if user.role is UserRole.ADMIN:
        return True

    minimum = _CAPABILITY_MINIMUM.get(capability)
    if minimum is None:  # pragma: no cover - every capability is mapped
        return False
    return has_module_access(user, module, minimum)


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


# --------------------------------------------------------------------------
# Media that belongs to the museum rather than to a trench
# --------------------------------------------------------------------------
def _is_museum_media(record: Any) -> bool:
    """Whether this record hangs from an accessioned object.

    Photographs, documents and models are gated on the archaeology module,
    which was right while every one of them hung from an excavation record.
    An accessioned object is not one: it may have been donated in 1890 and
    have no project anywhere above it. A curator with no archaeology access
    could upload a picture of a dish and then not be able to see it.

    So a media record naming a museum object is governed by the museum module
    instead. The excavation links, where the object came out of a trench, still
    do their own work - the picture appears on the find's page too, for people
    who can see the find.
    """
    return getattr(record, "museum_object_id", None) is not None


def _museum_media_level(user: User | None) -> PermissionLevel | None:
    """What the museum module grants over its own media."""
    if has_module_access(user, Module.MUSEUM, ModuleLevel.ADMINISTRATOR):
        return PermissionLevel.OWNER
    if has_module_access(user, Module.MUSEUM, ModuleLevel.EDITOR):
        return PermissionLevel.EDITOR
    if has_module_access(user, Module.MUSEUM, ModuleLevel.CONTRIBUTOR):
        return PermissionLevel.EDITOR
    if has_module_access(user, Module.MUSEUM, ModuleLevel.VIEWER):
        return PermissionLevel.VIEWER
    return None


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
    if has_module_access(user, module_of(resource_type), ModuleLevel.ADMINISTRATOR):
        return PermissionLevel.OWNER

    levels: list[PermissionLevel] = []

    if _is_museum_media(record):
        museum = _museum_media_level(user)
        if museum is not None:
            levels.append(museum)

    if _record_is_public(record):
        levels.append(PermissionLevel.VIEWER)

    if user is not None and user.is_active and module_level(user, module_of(resource_type)):
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
    """Editing needs an ``EDITOR`` level *and* module access that may write."""
    writable = has_module_access(user, module_of(resource_type), ModuleLevel.CONTRIBUTOR)
    if _is_museum_media(record):
        writable = writable or has_module_access(user, Module.MUSEUM, ModuleLevel.CONTRIBUTOR)
    if not writable:
        return False
    level = effective_level(session, user, record, resource_type)
    return level is not None and level >= PermissionLevel.EDITOR


# --------------------------------------------------------------------------
# Modules with no projects in them
# --------------------------------------------------------------------------
# A museum object is not part of an excavation, so asking which project team a
# user belongs to answers nothing about whether they may catalogue it. For
# those modules the policy collapses to two of the four sources — module level
# and ownership — and these three functions are the whole of it. They are here
# rather than in the museum endpoints so that both halves of the platform ask
# the same code the same question.
def flat_can_view(user: User | None, record: Any, module: Module) -> bool:
    """Anyone with module access reads the module; anyone else reads what is
    public, which is exactly what an institution's own website would show."""
    if has_module_access(user, module, ModuleLevel.VIEWER):
        return True
    return _record_is_public(record)


def flat_can_edit(user: User | None, record: Any, module: Module) -> bool:
    """An editor changes anything in the module; a contributor changes what
    they themselves catalogued."""
    if not has_module_access(user, module, ModuleLevel.CONTRIBUTOR):
        return False
    if has_module_access(user, module, ModuleLevel.EDITOR):
        return True
    owner_id = _record_owner_id(record)
    return owner_id is not None and user is not None and owner_id == user.id


def flat_visibility_filter(user: User | None, model: Any, module: Module) -> Any:
    """The SQL mirror of :func:`flat_can_view`."""
    if has_module_access(user, module, ModuleLevel.VIEWER):
        return true()
    return model.is_public.is_(True)


def can_delete(
    session: Session, user: User | None, record: Any, resource_type: ResourceType
) -> bool:
    """Deletion needs ``OWNER``; deleting a project additionally needs the
    project director role or a module administrator, per the rule that
    contributors may never delete a whole project."""
    module = module_of(resource_type)
    if not has_module_access(user, module, ModuleLevel.CONTRIBUTOR):
        return False
    if has_module_access(user, module, ModuleLevel.ADMINISTRATOR):
        return True

    level = effective_level(session, user, record, resource_type)
    if level is None or level < PermissionLevel.OWNER:
        return False

    if resource_type is ResourceType.PROJECT:
        if not has_module_access(user, module, ModuleLevel.SUPERVISOR):
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
    record — a supervisor may not approve work in a project they are not on."""
    module = module_of(resource_type)
    if not has_capability(user, Capability.APPROVE_SUBMISSION, module):
        return False
    if has_module_access(user, module, ModuleLevel.ADMINISTRATOR):
        return True
    return can_edit(session, user, record, resource_type)


def requires_approval(user: User | None, module: Module = Module.ARCHAEOLOGY) -> bool:
    """Whether records created by this user start as pending review.

    Contributors submit for approval; editors and above do not. This is the
    level's defining difference: a contributor's work is checked, an editor's
    is trusted.
    """
    level = module_level(user, module)
    return level is not None and level < ModuleLevel.EDITOR


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

    if user is None or not user.is_active or module_level(user, module_of(resource_type)) is None:
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
    module = module_of(resource_type)
    if has_module_access(user, module, ModuleLevel.ADMINISTRATOR):
        return true()

    clauses: list[Any] = [model.is_public.is_(True)]

    # Module access is a per-user scalar, so it is resolved here rather than
    # joined — the shape of the generated SQL is unchanged by this check.
    # The museum's own media, for a user who may have no archaeology access at
    # all. Mirrors `_is_museum_media` on the single-record path.
    if hasattr(model, "museum_object_id") and has_module_access(
        user, Module.MUSEUM, ModuleLevel.VIEWER
    ):
        clauses.append(model.museum_object_id.isnot(None))

    if user is not None and user.is_active and module_level(user, module) is not None:
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
    module = module_of(resource_type)
    museum_media = hasattr(model, "museum_object_id") and has_module_access(
        user, Module.MUSEUM, ModuleLevel.CONTRIBUTOR
    )
    if not has_module_access(user, module, ModuleLevel.CONTRIBUTOR) and not museum_media:
        return false()
    if has_module_access(user, module, ModuleLevel.ADMINISTRATOR):
        return true()

    clauses: list[Any] = [model.owner_id == user.id]
    if museum_media:
        clauses.append(model.museum_object_id.isnot(None))

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
