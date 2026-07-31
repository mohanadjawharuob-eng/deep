"""User and authentication schemas."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import PasswordPolicyError, validate_password
from app.models.enums import UserRole
from app.schemas.common import ORMModel

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,64}$")
_ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


def _check_password(value: str) -> str:
    try:
        validate_password(value)
    except PasswordPolicyError as exc:
        raise ValueError(str(exc)) from exc
    return value


class UserBase(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=64)
    full_name: str = Field(min_length=1, max_length=200)
    institution: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    position: str | None = Field(default=None, max_length=120)
    orcid: str | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)
    bio: str | None = None
    phone: str | None = Field(default=None, max_length=40)

    @field_validator("username")
    @classmethod
    def _valid_username(cls, value: str) -> str:
        if not _USERNAME_RE.match(value):
            raise ValueError(
                "Username may contain only letters, digits, dot, underscore and hyphen"
            )
        return value.lower()

    @field_validator("orcid")
    @classmethod
    def _valid_orcid(cls, value: str | None) -> str | None:
        if value and not _ORCID_RE.match(value):
            raise ValueError("ORCID must look like 0000-0002-1825-0097")
        return value

    @field_validator("country")
    @classmethod
    def _upper_country(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class UserCreate(UserBase):
    """Self-service registration.

    The role is deliberately absent: anyone may sign up, but only an
    administrator can grant a role above the default. Accepting a role here
    would be a privilege-escalation hole.
    """

    password: str = Field(min_length=10, max_length=72)

    _validate_password = field_validator("password")(_check_password)


class UserCreateAdmin(UserCreate):
    """Administrator-side creation, where the role *can* be set."""

    role: UserRole = UserRole.STUDENT
    is_active: bool = True
    is_verified: bool = True


class UserUpdate(BaseModel):
    """Fields a user may change about themselves."""

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    institution: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    position: str | None = Field(default=None, max_length=120)
    orcid: str | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)
    bio: str | None = None
    phone: str | None = Field(default=None, max_length=40)
    locale: str | None = Field(default=None, max_length=10)
    theme: str | None = Field(default=None, pattern="^(light|dark|system)$")

    @field_validator("orcid")
    @classmethod
    def _valid_orcid(cls, value: str | None) -> str | None:
        if value and not _ORCID_RE.match(value):
            raise ValueError("ORCID must look like 0000-0002-1825-0097")
        return value


class UserUpdateAdmin(UserUpdate):
    """Additional fields only an administrator may change."""

    email: EmailStr | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    is_verified: bool | None = None


class UserPublic(ORMModel):
    """A user as seen by other users — no contact details."""

    id: uuid.UUID
    username: str
    full_name: str
    role: UserRole
    institution: str | None = None
    position: str | None = None
    orcid: str | None = None
    avatar_path: str | None = None


class UserRead(UserPublic):
    """Full profile: the user themselves, or an administrator.

    ``email`` is a plain ``str`` here, not ``EmailStr``: input is validated on
    the way in, and re-validating on the way out only means a row that predates
    a stricter rule turns a successful read into a 500.
    """

    email: str
    department: str | None = None
    country: str | None = None
    bio: str | None = None
    phone: str | None = None
    locale: str
    theme: str
    is_active: bool
    is_verified: bool
    last_login_at: datetime | None = None
    created_at: datetime


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=72)

    _validate_password = field_validator("new_password")(_check_password)


class PasswordReset(BaseModel):
    """Administrative reset — no current password required."""

    new_password: str = Field(min_length=10, max_length=72)

    _validate_password = field_validator("new_password")(_check_password)
