"""Token payloads exchanged by the authentication endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.user import UserRead


class LoginRequest(BaseModel):
    """Login accepts either the e-mail address or the username."""

    identifier: str = Field(description="E-mail address or username", max_length=320)
    password: str = Field(max_length=72)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime = Field(description="Expiry of the access token (UTC)")
    expires_in: int = Field(description="Seconds until the access token expires")


class LoginResponse(TokenPair):
    """Login returns the profile too, so the client needs one request."""

    user: UserRead


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(
        default=None,
        description="Session to end. Omit to end only the current one.",
    )
    all_devices: bool = Field(default=False, description="Revoke every refresh token for this user")


class SessionInfo(BaseModel):
    """One active login, as shown on the account's security page."""

    id: str
    created_at: datetime
    expires_at: datetime
    user_agent: str | None = None
    ip_address: str | None = None
    is_current: bool = False
