"""User directory and administration."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, DbSession, RequireAdmin
from app.core.config import settings
from app.core.security import hash_password
from app.models.enums import ActivityAction, Module, ResourceType, UserRole
from app.models.user import User
from app.schemas.common import Message, Page
from app.schemas.user import (
    ModuleAccessGrant,
    ModuleAccessSummary,
    PasswordReset,
    UserCreateAdmin,
    UserCreated,
    UserPublic,
    UserRead,
    UserUpdate,
    UserUpdateAdmin,
)
from app.services import access, activity, auth, branding, mail

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "",
    response_model=Page[UserPublic],
    summary="List users",
    description=(
        "Visible to any signed-in user so team members can be found and "
        "invited. Contact details are omitted; administrators use "
        "`/users/{id}` for the full record."
    ),
)
def list_users(
    session: DbSession,
    _: CurrentUser,
    q: Annotated[str | None, Query(description="Match name, username or institution")] = None,
    role: Annotated[UserRole | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[UserPublic]:
    statement = select(User)
    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(User.full_name).like(pattern),
                func.lower(User.username).like(pattern),
                func.lower(User.institution).like(pattern),
            )
        )
    if role is not None:
        statement = statement.where(User.role == role)
    if is_active is not None:
        statement = statement.where(User.is_active == is_active)

    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = session.scalars(statement.order_by(User.full_name).limit(limit).offset(offset)).all()
    return Page[UserPublic](
        items=[UserPublic.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/me", response_model=UserRead, summary="Update own profile")
def update_me(payload: UserUpdate, session: DbSession, user: CurrentUser, request: Request) -> User:
    changes = payload.model_dump(exclude_unset=True)
    before = {key: getattr(user, key) for key in changes}
    for key, value in changes.items():
        setattr(user, key, value)
    session.add(user)

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=ResourceType.USER,
        resource_id=user.id,
        resource_label=user.username,
        changes=activity.diff(before, changes),
        request=request,
    )
    return user


@router.get(
    "/{user_id}",
    response_model=UserRead,
    summary="Read a user",
    description="Administrators may read anyone; other users only themselves.",
    responses={404: {"description": "No such user"}},
)
def read_user(user_id: uuid.UUID, session: DbSession, user: CurrentUser) -> User:
    if user.role is not UserRole.ADMIN and user.id != user_id:
        # 404 rather than 403: whether an id exists is itself information.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    return target


@router.post(
    "",
    response_model=UserCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user (administrator)",
    description=(
        "Makes the account and, unless `send_welcome_email` is false, e-mails "
        "the person their address, username and first password.\n\n"
        "The response says what happened to that message. **The account is "
        "made either way** - a site with no outbound mail is a supported way "
        "to run this, and the administrator needs to know whether to pass the "
        "password on by hand.\n\n"
        "The password cannot be re-sent later: only its hash is kept. Setting "
        "a new one is how somebody who lost the message gets back in."
    ),
    responses={409: {"description": "E-mail address or username already taken"}},
)
def create_user(
    payload: UserCreateAdmin, session: DbSession, admin: RequireAdmin, request: Request
) -> UserCreated:
    existing = session.scalar(
        select(User).where(
            or_(
                func.lower(User.email) == payload.email.lower(),
                func.lower(User.username) == payload.username.lower(),
            )
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="E-mail or username already in use")

    user = User(
        email=payload.email.lower(),
        username=payload.username,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        institution=payload.institution,
        department=payload.department,
        position=payload.position,
        orcid=payload.orcid,
        country=payload.country,
        bio=payload.bio,
        phone=payload.phone,
        is_active=payload.is_active,
        is_verified=payload.is_verified,
    )
    session.add(user)
    session.flush()
    # An explicit map is the *complete* set of access, not an addition to the
    # role default. Otherwise "communications officer, no archaeology" would be
    # inexpressible — every account would carry archaeology whether or not the
    # person has any business in it.
    if payload.module_access is None:
        access.grant_defaults(session, user, granted_by=admin)
    else:
        for module, level in payload.module_access.items():
            access.grant(session, user, module, level, granted_by=admin)

    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=admin,
        resource_type=ResourceType.USER,
        resource_id=user.id,
        resource_label=user.username,
        summary=f"Created user with role {user.role.value}",
        request=request,
    )
    session.flush()

    sent, note = _welcome(session, user, payload, invited_by=admin)
    return UserCreated(
        user=UserRead.model_validate(user),
        welcome_email_sent=sent,
        welcome_email_note=note,
    )


def _welcome(
    session: DbSession, user: User, payload: UserCreateAdmin, *, invited_by: User
) -> tuple[bool, str]:
    """Tell the new person their account exists, and report honestly.

    Never raises. An account that was made is made; a message that failed to go
    out is a thing to tell the administrator, not a reason to undo somebody's
    account and leave them with neither.
    """
    if not payload.send_welcome_email:
        return False, "No message was sent, as asked. Give them the password yourself."

    organisation = branding.read(session).display_name
    subject, body, html = mail.welcome(
        full_name=user.full_name,
        username=user.username,
        password=payload.password,
        address=settings.FRONTEND_URL,
        organisation=organisation,
        role=user.role.value,
        invited_by=invited_by.full_name,
    )
    result = mail.send(user.email, subject, body, html=html, reply_to=invited_by.email)
    if result.ok:
        return True, f"Their sign-in details were e-mailed to {user.email}."
    return False, (
        f"The account was made, but the e-mail did not go out: {result.detail} "
        f"Give them the password yourself."
    )


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    summary="Update a user (administrator)",
    responses={
        400: {"description": "Would remove the last administrator"},
        404: {"description": "No such user"},
    },
)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateAdmin,
    session: DbSession,
    admin: RequireAdmin,
    request: Request,
) -> User:
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")

    changes = payload.model_dump(exclude_unset=True)

    # Guard against locking everyone out of the administration panel.
    demoting = changes.get("role") not in (None, UserRole.ADMIN) and "role" in changes
    deactivating = changes.get("is_active") is False
    if target.role is UserRole.ADMIN and (demoting or deactivating):
        remaining = session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == UserRole.ADMIN, User.is_active.is_(True), User.id != target.id)
        )
        if not remaining:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote or deactivate the last active administrator",
            )

    if "email" in changes and changes["email"]:
        changes["email"] = changes["email"].lower()
        clash = session.scalar(
            select(User).where(func.lower(User.email) == changes["email"], User.id != target.id)
        )
        if clash is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="E-mail already in use")

    before = {key: getattr(target, key) for key in changes}
    for key, value in changes.items():
        setattr(target, key, value)

    # Deactivation must take effect immediately, not when tokens expire.
    if deactivating:
        auth.revoke_all_for_user(session, target.id)
        target.tokens_valid_after = datetime.now(UTC)
    session.add(target)

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=admin,
        resource_type=ResourceType.USER,
        resource_id=target.id,
        resource_label=target.username,
        changes=activity.diff(before, changes),
        request=request,
    )
    return target


@router.post(
    "/{user_id}/reset-password",
    response_model=Message,
    summary="Reset a user's password (administrator)",
)
def reset_password(
    user_id: uuid.UUID,
    payload: PasswordReset,
    session: DbSession,
    admin: RequireAdmin,
    request: Request,
) -> Message:
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")

    target.hashed_password = hash_password(payload.new_password)
    target.tokens_valid_after = datetime.now(UTC)
    target.failed_login_count = 0
    target.locked_until = None
    session.add(target)
    revoked = auth.revoke_all_for_user(session, target.id)

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=admin,
        resource_type=ResourceType.USER,
        resource_id=target.id,
        resource_label=target.username,
        summary="Password reset by administrator",
        request=request,
    )
    return Message(detail=f"Password reset; {revoked} session(s) signed out")


@router.delete(
    "/{user_id}",
    response_model=Message,
    summary="Deactivate a user (administrator)",
    description=(
        "Accounts are deactivated, never deleted: excavation records must keep "
        "pointing at the person who created them. Use `PATCH` with "
        "`is_active: true` to restore access."
    ),
)
def deactivate_user(
    user_id: uuid.UUID, session: DbSession, admin: RequireAdmin, request: Request
) -> Message:
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate yourself")

    if target.role is UserRole.ADMIN:
        remaining = session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == UserRole.ADMIN, User.is_active.is_(True), User.id != target.id)
        )
        if not remaining:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate the last active administrator",
            )

    target.is_active = False
    target.tokens_valid_after = datetime.now(UTC)
    session.add(target)
    auth.revoke_all_for_user(session, target.id)

    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=admin,
        resource_type=ResourceType.USER,
        resource_id=target.id,
        resource_label=target.username,
        summary="Account deactivated",
        request=request,
    )
    return Message(detail="Account deactivated")


# --------------------------------------------------------------------------
# Module access
# --------------------------------------------------------------------------
def _access_summary(user: User) -> ModuleAccessSummary:
    return ModuleAccessSummary(
        user_id=user.id,
        username=user.username,
        is_platform_admin=user.role is UserRole.ADMIN,
        access={grant.module: grant.level for grant in user.module_access},
    )


@router.get(
    "/me/access",
    response_model=ModuleAccessSummary,
    summary="What modules you can reach",
    description=(
        "The modules this account has access to, and at what level. A client "
        "reads this once at sign-in to decide which sections of the interface "
        "to show.\n\n"
        "A platform administrator holds every module implicitly and so reports "
        "`is_platform_admin: true` with an empty `access` map — that is not the "
        "same as having no access."
    ),
)
def read_own_access(user: CurrentUser) -> ModuleAccessSummary:
    return _access_summary(user)


@router.get(
    "/{user_id}/access",
    response_model=ModuleAccessSummary,
    summary="What modules a user can reach (administrator)",
)
def read_user_access(
    user_id: uuid.UUID, session: DbSession, admin: RequireAdmin
) -> ModuleAccessSummary:
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    return _access_summary(target)


@router.put(
    "/{user_id}/access",
    response_model=ModuleAccessSummary,
    summary="Grant or change module access (administrator)",
    description=(
        "Sets the level this user holds in one module, replacing whatever they "
        "held before. Access is additive across modules: granting museum access "
        "does not touch their archaeology access.\n\n"
        "Granting access to a platform administrator is refused — they already "
        "hold every module, and a row would imply it could be taken away."
    ),
)
def grant_user_access(
    user_id: uuid.UUID,
    payload: ModuleAccessGrant,
    session: DbSession,
    admin: RequireAdmin,
    request: Request,
) -> ModuleAccessSummary:
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.role is UserRole.ADMIN:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                "Platform administrators already hold every module. Change their "
                "role first if their access should be limited."
            ),
        )

    access.grant(
        session,
        target,
        payload.module,
        payload.level,
        granted_by=admin,
        note=payload.note,
    )
    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=admin,
        resource_type=ResourceType.USER,
        resource_id=target.id,
        resource_label=target.username,
        summary=(
            f"Granted {payload.level.value} access to the "
            f"{payload.module.value.replace('_', ' ')} module"
        ),
        request=request,
    )
    return _access_summary(target)


@router.delete(
    "/{user_id}/access/{module}",
    response_model=ModuleAccessSummary,
    summary="Revoke module access (administrator)",
    description=(
        "Removes this user's access to one module entirely. Records they "
        "created there are untouched — the account keeps its authorship, it "
        "simply can no longer reach the module."
    ),
)
def revoke_user_access(
    user_id: uuid.UUID,
    module: Module,
    session: DbSession,
    admin: RequireAdmin,
    request: Request,
) -> ModuleAccessSummary:
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")

    if not access.revoke(session, target, module):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"That user has no access to the {module.value.replace('_', ' ')} module",
        )

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=admin,
        resource_type=ResourceType.USER,
        resource_id=target.id,
        resource_label=target.username,
        summary=f"Revoked access to the {module.value.replace('_', ' ')} module",
        request=request,
    )
    return _access_summary(target)
