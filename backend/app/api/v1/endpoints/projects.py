"""Project CRUD and team management."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, CurrentUserOptional, DbSession, require_capability
from app.core.permissions import (
    Capability,
    can_delete,
    can_edit,
    can_view,
    visibility_filter,
)
from app.models.artifact import Artifact
from app.models.enums import (
    ActivityAction,
    NotificationType,
    ProjectRole,
    ProjectStatus,
    ResourceType,
)
from app.models.project import Project, ProjectMembership
from app.models.site import Site
from app.models.user import User
from app.schemas.common import Message, Page
from app.schemas.project import (
    MembershipCreate,
    MembershipRead,
    MembershipUpdate,
    ProjectCreate,
    ProjectDetail,
    ProjectSummary,
    ProjectUpdate,
    slugify,
)
from app.services import activity, notifications, records

router = APIRouter(prefix="/projects", tags=["Projects"])

RESOURCE = ResourceType.PROJECT


def _unique_slug(session: DbSession, name: str, exclude_id: uuid.UUID | None = None) -> str:
    """Derive a URL slug, appending a counter if the name is already taken."""
    base = slugify(name)
    candidate = base
    counter = 2
    while True:
        statement = select(Project.id).where(Project.slug == candidate)
        if exclude_id is not None:
            statement = statement.where(Project.id != exclude_id)
        if session.scalar(statement) is None:
            return candidate
        candidate = f"{base}-{counter}"
        counter += 1


def _load_project(session: DbSession, project_id: uuid.UUID) -> Project:
    return records.get_or_404(session, Project, project_id, "Project")


def _detail(session: DbSession, project: Project, user: User | None) -> ProjectDetail:
    """Assemble the response, including counts and the caller's rights."""
    site_count = (
        session.scalar(select(func.count()).select_from(Site).where(Site.project_id == project.id))
        or 0
    )
    artifact_count = (
        session.scalar(
            select(func.count())
            .select_from(Artifact)
            .join(Site, Artifact.site_id == Site.id)
            .where(Site.project_id == project.id)
        )
        or 0
    )
    member_count = (
        session.scalar(
            select(func.count())
            .select_from(ProjectMembership)
            .where(ProjectMembership.project_id == project.id)
        )
        or 0
    )
    detail = ProjectDetail.model_validate(project)
    detail.site_count = site_count
    detail.artifact_count = artifact_count
    detail.member_count = member_count
    detail.can_edit = can_edit(session, user, project, RESOURCE)
    detail.can_delete = can_delete(session, user, project, RESOURCE)
    return detail


@router.get(
    "",
    response_model=Page[ProjectSummary],
    summary="List projects",
    description=(
        "Returns the projects the caller may see: public ones for everybody, "
        "plus any they own, are a team member of, or have been granted access "
        "to. Filtering happens in SQL, so paging is over the visible set."
    ),
)
def list_projects(
    session: DbSession,
    user: CurrentUserOptional,
    q: Annotated[str | None, Query(description="Match name, code, institution or region")] = None,
    status_filter: Annotated[ProjectStatus | None, Query(alias="status")] = None,
    country: Annotated[str | None, Query()] = None,
    institution: Annotated[str | None, Query()] = None,
    mine: Annotated[bool, Query(description="Only projects I am a member of")] = False,
    sort: Annotated[str, Query(pattern="^-?(name|code|start_date|created_at|status)$")] = "name",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ProjectSummary]:
    statement = select(Project).where(visibility_filter(user, Project, RESOURCE))

    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Project.name).like(pattern),
                func.lower(Project.code).like(pattern),
                func.lower(Project.institution).like(pattern),
                func.lower(Project.region).like(pattern),
            )
        )
    if status_filter is not None:
        statement = statement.where(Project.status == status_filter)
    if country:
        statement = statement.where(func.lower(Project.country) == country.lower())
    if institution:
        statement = statement.where(
            func.lower(Project.institution).like(f"%{institution.lower()}%")
        )
    if mine:
        if user is None:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, detail="Sign in to list your projects"
            )
        statement = statement.where(
            Project.id.in_(
                select(ProjectMembership.project_id).where(ProjectMembership.user_id == user.id)
            )
        )

    descending = sort.startswith("-")
    column = getattr(Project, sort.lstrip("-"))
    statement = statement.order_by(column.desc() if descending else column.asc())

    rows, total = records.paginate(session, statement, limit, offset)
    return Page[ProjectSummary](
        items=[ProjectSummary.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=ProjectDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
    description="Requires the researcher role. The creator becomes its director.",
    responses={409: {"description": "Project code already in use"}},
)
def create_project(
    payload: ProjectCreate,
    session: DbSession,
    request: Request,
    user: Annotated[User, Depends(require_capability(Capability.CREATE_PROJECT))],
) -> ProjectDetail:
    if session.scalar(select(Project.id).where(Project.code == payload.code)) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"Project code {payload.code!r} is already in use"
        )

    data = payload.model_dump()
    project = Project(**data, slug=_unique_slug(session, payload.name), owner_id=user.id)
    session.add(project)
    session.flush()

    # The creator is the director: without this they would own the row but hold
    # no team role, and the project-level checks would not recognise them.
    session.add(
        ProjectMembership(
            project_id=project.id,
            user_id=user.id,
            role=ProjectRole.DIRECTOR,
            invited_by_id=user.id,
        )
    )

    records.on_created(session, project, RESOURCE, user=user, request=request)
    session.flush()
    return _detail(session, project, user)


@router.get(
    "/{project_id}",
    response_model=ProjectDetail,
    summary="Read a project",
    responses={404: {"description": "No such project, or not visible to you"}},
)
def read_project(
    project_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> ProjectDetail:
    project = _load_project(session, project_id)
    if not can_view(session, user, project, RESOURCE):
        # 404 rather than 403: revealing that a private project exists is
        # itself a disclosure.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")
    return _detail(session, project, user)


@router.patch(
    "/{project_id}",
    response_model=ProjectDetail,
    summary="Update a project",
    description="Every change is versioned; see `/projects/{id}/revisions`.",
    responses={403: {"description": "You may not edit this project"}},
)
def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> ProjectDetail:
    project = _load_project(session, project_id)
    if not can_view(session, user, project, RESOURCE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")
    if not can_edit(session, user, project, RESOURCE):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You may not edit this project")

    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] != project.name:
        changes["slug"] = _unique_slug(session, changes["name"], exclude_id=project.id)

    before = records.apply_changes(project, changes)
    records.on_updated(session, project, RESOURCE, before=before, user=user, request=request)
    session.flush()
    return _detail(session, project, user)


@router.delete(
    "/{project_id}",
    response_model=Message,
    summary="Delete a project",
    description=(
        "Only the project's director or an administrator may delete a project, "
        "and doing so removes its sites, artifacts and contexts. The final "
        "state of the project is kept in the revision history."
    ),
    responses={403: {"description": "You may not delete this project"}},
)
def delete_project(
    project_id: uuid.UUID, session: DbSession, request: Request, user: CurrentUser
) -> Message:
    project = _load_project(session, project_id)
    if not can_view(session, user, project, RESOURCE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")
    if not can_delete(session, user, project, RESOURCE):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Only the project director or an administrator may delete a project",
        )

    label = project.name
    records.on_deleted(session, project, RESOURCE, user=user, request=request, label=label)
    session.delete(project)
    return Message(detail=f"Project {label!r} deleted")


# --------------------------------------------------------------------------
# Team
# --------------------------------------------------------------------------
@router.get(
    "/{project_id}/members",
    response_model=list[MembershipRead],
    summary="List team members",
)
def list_members(
    project_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> list[MembershipRead]:
    project = _load_project(session, project_id)
    if not can_view(session, user, project, RESOURCE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")

    rows = session.scalars(
        select(ProjectMembership)
        .options(selectinload(ProjectMembership.user))
        .where(ProjectMembership.project_id == project_id)
        .order_by(ProjectMembership.created_at)
    ).all()
    return [MembershipRead.model_validate(row) for row in rows]


@router.post(
    "/{project_id}/members",
    response_model=MembershipRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a team member",
    responses={409: {"description": "Already a member of this project"}},
)
def add_member(
    project_id: uuid.UUID,
    payload: MembershipCreate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> MembershipRead:
    project = _load_project(session, project_id)
    if not can_edit(session, user, project, RESOURCE):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="You may not manage this project's team"
        )

    member = session.get(User, payload.user_id)
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")

    existing = session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == payload.user_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="That user is already on this project")

    membership = ProjectMembership(
        project_id=project_id,
        user_id=payload.user_id,
        role=payload.role,
        title=payload.title,
        invited_by_id=user.id,
    )
    session.add(membership)
    session.flush()

    notifications.notify(
        session,
        user_id=member.id,
        type=NotificationType.PROJECT_INVITATION,
        title=f"You were added to {project.name}",
        body=f"{user.full_name} added you as {payload.role.value}.",
        link=f"/projects/{project.slug}",
        resource_type=RESOURCE,
        resource_id=project.id,
        actor_id=user.id,
    )
    activity.log(
        session,
        action=ActivityAction.SHARE,
        user=user,
        resource_type=RESOURCE,
        resource_id=project.id,
        resource_label=project.name,
        project_id=project.id,
        summary=f"Added {member.username} as {payload.role.value}",
        request=request,
    )
    session.refresh(membership)
    return MembershipRead.model_validate(membership)


@router.patch(
    "/{project_id}/members/{user_id}",
    response_model=MembershipRead,
    summary="Change a member's role",
    responses={400: {"description": "Would leave the project without a director"}},
)
def update_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: MembershipUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> MembershipRead:
    project = _load_project(session, project_id)
    if not can_edit(session, user, project, RESOURCE):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="You may not manage this project's team"
        )

    membership = session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id, ProjectMembership.user_id == user_id
        )
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That user is not on this project")

    changes = payload.model_dump(exclude_unset=True)
    if changes.get("role") is not None and membership.role is ProjectRole.DIRECTOR:
        _require_another_director(session, project_id, user_id)

    records.apply_changes(membership, changes)
    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=project.id,
        resource_label=project.name,
        project_id=project.id,
        summary=f"Changed a team member's role to {membership.role.value}",
        request=request,
    )
    session.flush()
    session.refresh(membership)
    return MembershipRead.model_validate(membership)


@router.delete(
    "/{project_id}/members/{user_id}",
    response_model=Message,
    summary="Remove a team member",
)
def remove_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> Message:
    project = _load_project(session, project_id)
    # Leaving a project yourself needs no management rights.
    if user.id != user_id and not can_edit(session, user, project, RESOURCE):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="You may not manage this project's team"
        )

    membership = session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id, ProjectMembership.user_id == user_id
        )
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That user is not on this project")

    if membership.role is ProjectRole.DIRECTOR:
        _require_another_director(session, project_id, user_id)

    session.delete(membership)
    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=RESOURCE,
        resource_id=project.id,
        resource_label=project.name,
        project_id=project.id,
        summary="Removed a team member",
        request=request,
    )
    return Message(detail="Member removed")


def _require_another_director(
    session: DbSession, project_id: uuid.UUID, excluding_user_id: uuid.UUID
) -> None:
    """Refuse changes that would leave a project with nobody able to run it.

    A project with no director cannot be deleted or have its team managed by
    anyone short of an administrator, so this is a dead end worth preventing.
    """
    remaining = session.scalar(
        select(func.count())
        .select_from(ProjectMembership)
        .where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.role == ProjectRole.DIRECTOR,
            ProjectMembership.user_id != excluding_user_id,
        )
    )
    if not remaining:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="A project must keep at least one director",
        )
