"""Authentication workflows: login, refresh rotation and revocation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_token,
    verify_password,
)
from app.models.enums import ActivityAction
from app.models.user import RefreshToken, User
from app.schemas.auth import TokenPair
from app.services import activity

#: Lock an account after this many consecutive failures…
MAX_FAILED_LOGINS = 8
#: …for this long. Long enough to make online guessing pointless, short enough
#: that a locked-out researcher is not blocked for a whole field day.
LOCKOUT_DURATION = timedelta(minutes=15)


class AuthError(Exception):
    """Authentication failed. The message is safe to show to the client."""

    def __init__(self, message: str = "Incorrect credentials", code: str = "invalid_credentials"):
        super().__init__(message)
        self.message = message
        self.code = code


def get_user_by_identifier(session: Session, identifier: str) -> User | None:
    """Look a user up by e-mail or username, both case-insensitively."""
    normalised = identifier.strip().lower()
    return session.scalar(
        select(User).where(
            or_(func.lower(User.email) == normalised, func.lower(User.username) == normalised)
        )
    )


def authenticate(session: Session, identifier: str, password: str) -> User:
    """Verify credentials, applying lockout and updating the failure counter.

    Failures are reported with one generic message so the endpoint cannot be
    used to discover which e-mail addresses are registered.
    """
    user = get_user_by_identifier(session, identifier)

    if user is None:
        # Spend roughly the same time as a real check would, so response
        # timing does not reveal whether the account exists.
        verify_password(password, "$2b$12$" + "." * 53)
        raise AuthError()

    now = datetime.now(UTC)
    if user.locked_until is not None and user.locked_until > now:
        remaining = int((user.locked_until - now).total_seconds() // 60) + 1
        raise AuthError(
            f"Account temporarily locked after repeated failed logins. "
            f"Try again in {remaining} minute(s).",
            code="account_locked",
        )

    if not verify_password(password, user.hashed_password):
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = now + LOCKOUT_DURATION
            user.failed_login_count = 0
        session.add(user)
        raise AuthError()

    if not user.is_active:
        raise AuthError("This account has been deactivated.", code="account_inactive")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    session.add(user)
    return user


def issue_tokens(session: Session, user: User, request: Request | None = None) -> TokenPair:
    """Mint an access/refresh pair and record the refresh token's session."""
    access_token, access_expires = create_access_token(user.id, user.role.value)
    refresh_token, refresh_expires, jti = create_refresh_token(user.id)

    context = activity.request_context(request)
    session.add(
        RefreshToken(
            user_id=user.id,
            jti=jti,
            token_hash=hash_token(refresh_token),
            expires_at=refresh_expires,
            user_agent=context.get("user_agent"),
            ip_address=context.get("ip_address"),
        )
    )

    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=access_expires,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def rotate_refresh_token(
    session: Session, raw_token: str, request: Request | None = None
) -> tuple[User, TokenPair]:
    """Exchange a refresh token for a new pair, invalidating the old one.

    Rotation makes stolen refresh tokens short-lived. Presenting a token that
    was already rotated means either a replay or a leak, so the whole family of
    sessions for that user is revoked and the event is logged.
    """
    stored = session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token))
    )
    if stored is None:
        raise AuthError("Unknown refresh token.", code="invalid_refresh_token")

    now = datetime.now(UTC)

    if stored.revoked_at is not None:
        revoke_all_for_user(session, stored.user_id)
        activity.log(
            session,
            action=ActivityAction.LOGIN_FAILED,
            summary="Reuse of a revoked refresh token; all sessions revoked.",
            request=request,
        )
        raise AuthError("Refresh token has been revoked.", code="revoked_refresh_token")

    if stored.expires_at <= now:
        raise AuthError("Refresh token has expired.", code="expired_refresh_token")

    user = session.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise AuthError("This account has been deactivated.", code="account_inactive")

    if user.tokens_valid_after is not None and stored.created_at < user.tokens_valid_after:
        raise AuthError("Session ended; please sign in again.", code="session_expired")

    tokens = issue_tokens(session, user, request)
    stored.revoked_at = now
    session.flush()
    successor = session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(tokens.refresh_token))
    )
    if successor is not None:
        stored.replaced_by_id = successor.id
    session.add(stored)
    return user, tokens


def revoke_refresh_token(session: Session, raw_token: str) -> bool:
    """Revoke one session. Returns ``False`` if the token was unknown."""
    stored = session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token))
    )
    if stored is None:
        return False
    if stored.revoked_at is None:
        stored.revoked_at = datetime.now(UTC)
        session.add(stored)
    return True


def revoke_all_for_user(session: Session, user_id) -> int:
    """Revoke every live session for a user; returns how many were revoked."""
    now = datetime.now(UTC)
    tokens = session.scalars(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
    ).all()
    for token in tokens:
        token.revoked_at = now
        session.add(token)
    return len(tokens)


def prune_expired_tokens(session: Session, older_than_days: int = 30) -> int:
    """Delete refresh tokens that expired long ago. Run from a cron job."""
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    tokens = session.scalars(select(RefreshToken).where(RefreshToken.expires_at < cutoff)).all()
    for token in tokens:
        session.delete(token)
    return len(tokens)
