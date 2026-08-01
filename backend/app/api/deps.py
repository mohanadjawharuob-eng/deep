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
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import Capability, has_capability, has_module_access
from app.core.security import decode_token
from app.db.session import SessionLocal
from app.models.enums import Module, ModuleLevel, UserRole
from app.models.user import User

#: Two ways to present the same credential, both reading ``Authorization:
#: Bearer <token>``.
#:
#: ``HTTPBearer`` is for clients that already hold a token. ``OAuth2PasswordBearer``
#: exists so the interactive documentation's *Authorize* dialog can offer a
#: username and password box and fetch the token itself — without it the dialog
#: demands a raw JWT, which nobody has to hand when they first open the page.
#:
#: ``auto_error=False`` on both so the optional dependency can tell "no token"
#: from "bad token" instead of the scheme raising 403 for either.
bearer_scheme = HTTPBearer(auto_error=False, description="Paste a JWT access token")
password_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/token",
    auto_error=False,
    description="Sign in with an e-mail address or username and a password",
)


def _presented_token(
    credentials: HTTPAuthorizationCredentials | None, password_token: str | None
) -> str | None:
    """The token from whichever scheme the client used.

    Both read the same header, so at most one is populated per request.
    """
    if credentials is not None:
        return credentials.credentials
    return password_token


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
    password_token: Annotated[str | None, Depends(password_scheme)] = None,
) -> User | None:
    """The signed-in user, or ``None`` for anonymous visitors.

    A malformed or expired token is still an error: silently treating it as
    anonymous would hide expiry from the client and mask token bugs.
    """
    token = _presented_token(credentials, password_token)
    if token is None:
        return None
    return _user_from_token(session, token)


CurrentUserOptional = Annotated[User | None, Depends(current_user_optional)]


def current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    password_token: Annotated[str | None, Depends(password_scheme)] = None,
) -> User:
    """A signed-in, active user; raises 401 otherwise."""
    token = _presented_token(credentials, password_token)
    if token is None:
        raise CREDENTIALS_EXCEPTION
    return _user_from_token(session, token)


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


def require_capability(capability: Capability, module: Module = Module.ARCHAEOLOGY):
    """Dependency factory enforcing a capability within one module."""

    def dependency(user: CurrentUser) -> User:
        if not has_capability(user, capability, module):
            action = capability.value.replace("_", " ")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Your access to the {module.value.replace('_', ' ')} module "
                    f"does not permit: {action}"
                ),
            )
        return user

    return dependency


def require_module(module: Module, minimum: ModuleLevel):
    """Dependency factory enforcing a minimum level in one module."""

    def dependency(user: CurrentUser) -> User:
        if not has_module_access(user, module, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This action needs {minimum.value} access or higher in the "
                    f"{module.value.replace('_', ' ')} module"
                ),
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
