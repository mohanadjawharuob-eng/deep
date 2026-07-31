"""Password hashing and JWT issuing/verification.

Two token types are issued:

``access``
    Short lived (minutes), sent on every request as a bearer token. Never
    stored server-side.
``refresh``
    Long lived (days), exchanged for a new access token. A SHA-256 hash of the
    token is stored in ``refresh_tokens`` so sessions can be revoked and
    reuse can be detected.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt
from jwt.exceptions import InvalidTokenError

from app.core.config import settings

TokenType = Literal["access", "refresh"]

# bcrypt truncates silently past 72 bytes; reject rather than accept a password
# whose tail is ignored.
_BCRYPT_MAX_BYTES = 72


class PasswordPolicyError(ValueError):
    """Raised when a candidate password fails the complexity policy."""


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------
def validate_password(password: str) -> None:
    """Enforce the password policy, raising :class:`PasswordPolicyError`."""
    problems: list[str] = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        problems.append(f"must be at least {settings.PASSWORD_MIN_LENGTH} characters")
    if len(password.encode("utf-8")) > _BCRYPT_MAX_BYTES:
        problems.append(f"must be at most {_BCRYPT_MAX_BYTES} bytes")
    if not re.search(r"[a-z]", password):
        problems.append("must contain a lowercase letter")
    if not re.search(r"[A-Z]", password):
        problems.append("must contain an uppercase letter")
    if not re.search(r"\d", password):
        problems.append("must contain a digit")
    if problems:
        raise PasswordPolicyError("Password " + "; ".join(problems))


def hash_password(password: str) -> str:
    """Hash a password with bcrypt (salt included in the returned digest)."""
    salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time password check; never raises on malformed hashes."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------
def _create_token(
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, datetime, str]:
    """Return ``(encoded_token, expires_at, jti)``."""
    now = datetime.now(UTC)
    expires_at = now + expires_delta
    jti = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": jti,
    }
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires_at, jti


def create_access_token(
    subject: str | uuid.UUID, role: str, extra_claims: dict[str, Any] | None = None
) -> tuple[str, datetime]:
    """Issue an access token. The role claim is a hint only — never trusted for
    authorisation, which always re-reads the user row."""
    claims = {"role": role, **(extra_claims or {})}
    token, expires_at, _ = _create_token(
        str(subject),
        "access",
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        claims,
    )
    return token, expires_at


def create_refresh_token(subject: str | uuid.UUID) -> tuple[str, datetime, str]:
    """Issue a refresh token; returns ``(token, expires_at, jti)``."""
    return _create_token(
        str(subject), "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )


def decode_token(token: str, expected_type: TokenType | None = None) -> dict[str, Any]:
    """Decode and validate a JWT.

    Raises :class:`jwt.exceptions.InvalidTokenError` when the signature,
    expiry or token type does not check out.
    """
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["exp", "sub", "type", "jti"]},
    )
    if expected_type and payload.get("type") != expected_type:
        raise InvalidTokenError(f"Expected a {expected_type} token, got {payload.get('type')!r}")
    return payload


def hash_token(token: str) -> str:
    """Digest used to store refresh tokens at rest.

    A plain SHA-256 is right here (unlike for passwords): the token is already
    128 bits of server-generated entropy, so there is nothing to brute-force,
    and lookups must stay fast.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
