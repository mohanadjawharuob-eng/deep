"""FastAPI dependencies: database sessions and the current user.

Three levels of authentication are offered, and endpoints pick the one that
matches their access rules:

``get_db``
    A request-scoped session, committed on success and rolled back on error.
``current_user_optional``
    The signed-in user, or ``None``. Used by public endpoints that show more
    to a signed-in visitor.
``current_user``
    A signed-in, active user; 401 otherwise.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.core.permissions import Capability, has_capability
from app.core.security import decode_token
from app.db.session import SessionLocal
from app.models.enums import UserRole
from app.models.user import User

#: ``auto_error=False`` so the optional dependency can distinguish "no token"
#: from "bad token" instead of the scheme raising 403 for both.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_db() -> Iterator[Session]:
    """One session per request, in a transaction the endpoint never manages."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db)]


def _user_from_token(session: Session, token: str) -> User:
    try:
        payload = decode_token(token, expected_type="access")
    except InvalidTokenError as exc:
        raise CREDENTIALS_EXCEPTION from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise CREDENTIALS_EXCEPTION from exc

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise CREDENTIALS_EXCEPTION

    # A password change or forced logout invalidates tokens issued earlier,
    # without needing a blacklist.
    issued_at = payload.get("iat")
    if user.tokens_valid_after is not None and issued_at is not None:
        cutoff = user.tokens_valid_after
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=UTC)
        if issued_at < cutoff.timestamp():
            raise CREDENTIALS_EXCEPTION

    return user


def current_user_optional(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User | None:
    """The signed-in user, or ``None`` for anonymous visitors.

    A malformed or expired token is still an error: silently treating it as
    anonymous would hide expiry from the client and mask token bugs.
    """
    if credentials is None:
        return None
    return _user_from_token(session, credentials.credentials)


CurrentUserOptional = Annotated[User | None, Depends(current_user_optional)]


def current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    """A signed-in, active user; raises 401 otherwise."""
    if credentials is None:
        raise CREDENTIALS_EXCEPTION
    return _user_from_token(session, credentials.credentials)


CurrentUser = Annotated[User, Depends(current_user)]


def require_role(minimum: UserRole):
    """Dependency factory enforcing a minimum global role."""

    def dependency(user: CurrentUser) -> User:
        if user.role < minimum:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the {minimum.value} role or higher",
            )
        return user

    return dependency


def require_capability(capability: Capability):
    """Dependency factory enforcing a global capability."""

    def dependency(user: CurrentUser) -> User:
        if not has_capability(user, capability):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your role does not permit: {capability.value.replace('_', ' ')}",
            )
        return user

    return dependency


#: Common shorthands.
RequireStudent = Annotated[User, Depends(require_role(UserRole.STUDENT))]
RequireResearcher = Annotated[User, Depends(require_role(UserRole.RESEARCHER))]
RequireAdmin = Annotated[User, Depends(require_role(UserRole.ADMIN))]


def get_request(request: Request) -> Request:
    """Expose the raw request to endpoints that write audit entries."""
    return request
