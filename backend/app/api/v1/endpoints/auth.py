"""Authentication endpoints: register, login, refresh, logout, sessions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, DbSession
from app.core.security import hash_password, hash_token, verify_password
from app.models.enums import ActivityAction, ResourceType, UserRole
from app.models.user import RefreshToken, User
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshRequest,
    SessionInfo,
    TokenPair,
)
from app.schemas.common import Message
from app.schemas.user import PasswordChange, UserCreate, UserRead
from app.services import activity, auth

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
    responses={409: {"description": "E-mail address or username already taken"}},
)
def register(payload: UserCreate, session: DbSession, request: Request) -> User:
    """Create an account.

    New accounts always get the **student** role — the least privileged role
    that can still contribute — and are inactive for verification purposes
    only in production. An administrator promotes users from the admin panel.
    """
    existing = session.scalar(
        select(User).where(
            or_(
                func.lower(User.email) == payload.email.lower(),
                func.lower(User.username) == payload.username.lower(),
            )
        )
    )
    if existing is not None:
        field = "E-mail address" if existing.email.lower() == payload.email.lower() else "Username"
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"{field} is already registered")

    user = User(
        email=payload.email.lower(),
        username=payload.username,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=UserRole.STUDENT,
        institution=payload.institution,
        department=payload.department,
        position=payload.position,
        orcid=payload.orcid,
        country=payload.country,
        bio=payload.bio,
        phone=payload.phone,
        is_active=True,
        is_verified=False,
    )
    session.add(user)
    session.flush()

    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_type=ResourceType.USER,
        resource_id=user.id,
        resource_label=user.username,
        summary="Account registered",
        request=request,
    )
    return user


@router.post("/login", response_model=LoginResponse, summary="Sign in")
def login(payload: LoginRequest, session: DbSession, request: Request) -> LoginResponse:
    """Exchange credentials for an access/refresh token pair."""
    try:
        user = auth.authenticate(session, payload.identifier, payload.password)
    except auth.AuthError as exc:
        activity.log(
            session,
            action=ActivityAction.LOGIN_FAILED,
            summary=f"Failed sign-in for {payload.identifier!r}: {exc.code}",
            request=request,
        )
        # Commit so the failure counter and the audit entry survive the 401.
        session.commit()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    tokens = auth.issue_tokens(session, user, request)
    activity.log(
        session,
        action=ActivityAction.LOGIN,
        user=user,
        resource_type=ResourceType.USER,
        resource_id=user.id,
        resource_label=user.username,
        request=request,
    )
    return LoginResponse(**tokens.model_dump(), user=UserRead.model_validate(user))


@router.post(
    "/token",
    response_model=TokenPair,
    summary="Sign in (OAuth2 password flow)",
    description=(
        "Form-encoded variant of `/login`, provided so the interactive API "
        "documentation's *Authorize* button works. Prefer `/login`."
    ),
)
def login_oauth2(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: DbSession,
    request: Request,
) -> TokenPair:
    try:
        user = auth.authenticate(session, form.username, form.password)
    except auth.AuthError as exc:
        session.commit()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    tokens = auth.issue_tokens(session, user, request)
    activity.log(
        session,
        action=ActivityAction.LOGIN,
        user=user,
        resource_type=ResourceType.USER,
        resource_id=user.id,
        request=request,
    )
    return tokens


@router.post("/refresh", response_model=TokenPair, summary="Rotate a refresh token")
def refresh(payload: RefreshRequest, session: DbSession, request: Request) -> TokenPair:
    """Exchange a refresh token for a fresh pair.

    The presented token is revoked in the process; reusing one that was already
    rotated revokes every session for that user, on the assumption it leaked.
    """
    try:
        _, tokens = auth.rotate_refresh_token(session, payload.refresh_token, request)
    except auth.AuthError as exc:
        session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=exc.message) from exc
    return tokens


@router.post("/logout", response_model=Message, summary="Sign out")
def logout(
    payload: LogoutRequest,
    session: DbSession,
    user: CurrentUser,
    request: Request,
) -> Message:
    """End the current session, or every session for this account."""
    if payload.all_devices:
        count = auth.revoke_all_for_user(session, user.id)
        detail = f"Signed out of {count} session(s)"
    elif payload.refresh_token:
        auth.revoke_refresh_token(session, payload.refresh_token)
        detail = "Signed out"
    else:
        detail = "Signed out"

    activity.log(
        session,
        action=ActivityAction.LOGOUT,
        user=user,
        resource_type=ResourceType.USER,
        resource_id=user.id,
        request=request,
    )
    return Message(detail=detail)


@router.get("/me", response_model=UserRead, summary="Current user profile")
def read_me(user: CurrentUser) -> User:
    return user


@router.get(
    "/sessions",
    response_model=list[SessionInfo],
    summary="List active sessions",
)
def list_sessions(session: DbSession, user: CurrentUser) -> list[SessionInfo]:
    """Every live refresh token for this account, newest first."""
    now = datetime.now(UTC)
    rows = session.scalars(
        select(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .order_by(RefreshToken.created_at.desc())
    ).all()
    return [
        SessionInfo(
            id=str(row.id),
            created_at=row.created_at,
            expires_at=row.expires_at,
            user_agent=row.user_agent,
            ip_address=str(row.ip_address) if row.ip_address else None,
        )
        for row in rows
    ]


@router.delete(
    "/sessions/{session_id}",
    response_model=Message,
    summary="Revoke one session",
    responses={404: {"description": "No such session for this account"}},
)
def revoke_session(session_id: str, session: DbSession, user: CurrentUser) -> Message:
    row = session.scalar(
        select(RefreshToken).where(RefreshToken.id == session_id, RefreshToken.user_id == user.id)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found")
    row.revoked_at = datetime.now(UTC)
    session.add(row)
    return Message(detail="Session revoked")


@router.post("/change-password", response_model=Message, summary="Change own password")
def change_password(
    payload: PasswordChange,
    session: DbSession,
    user: CurrentUser,
    request: Request,
) -> Message:
    """Change the password and end every other session.

    Existing access tokens stop working too: ``tokens_valid_after`` is moved
    forward, which invalidates anything issued before this moment.
    """
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="New password must differ from the current one"
        )

    user.hashed_password = hash_password(payload.new_password)
    user.tokens_valid_after = datetime.now(UTC)
    session.add(user)
    revoked = auth.revoke_all_for_user(session, user.id)

    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_type=ResourceType.USER,
        resource_id=user.id,
        resource_label=user.username,
        summary="Password changed",
        request=request,
    )
    return Message(detail=f"Password changed; {revoked} session(s) signed out")


# ``hash_token`` is re-exported for tests that need to look up a stored session.
__all__ = ["router", "hash_token"]
