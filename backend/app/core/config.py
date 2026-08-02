"""Application settings.

All configuration comes from environment variables (or a local ``.env`` file)
so the same image can be promoted from development to production untouched.
"""

from __future__ import annotations

import json
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application -----------------------------------------------------
    PROJECT_NAME: str = "Archaeological Research & Heritage Management Platform"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: Literal["development", "staging", "production", "test"] = "development"
    DEBUG: bool = False
    #: Public base URL of the frontend; QR codes and e-mail links point here.
    FRONTEND_URL: str = "http://localhost:5173"

    # --- Database --------------------------------------------------------
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "archeo"
    POSTGRES_PASSWORD: str = "archeo"
    POSTGRES_DB: str = "archeo"
    #: Set explicitly to override the values assembled above.
    DATABASE_URL: str | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO: bool = False

    # --- Security --------------------------------------------------------
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    #: bcrypt work factor. 12 is a sane 2020s default; raise as hardware improves.
    BCRYPT_ROUNDS: int = 12
    PASSWORD_MIN_LENGTH: int = 10
    #: Origins allowed by CORS, as ``a,b`` or as a JSON array.
    #:
    #: ``NoDecode`` is essential: without it pydantic-settings runs json.loads
    #: on any list-typed environment variable *inside the source*, before field
    #: validators are reached, so a plain comma-separated value fails to parse
    #: and the process exits before it can explain itself. NoDecode hands the
    #: raw string to the validator below instead.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    # --- First administrator ---------------------------------------------
    # Created by ``scripts/seed.py`` so a fresh deployment is usable at once.
    FIRST_ADMIN_EMAIL: str = "admin@example.org"
    FIRST_ADMIN_PASSWORD: str = "ChangeMe!2024"
    FIRST_ADMIN_USERNAME: str = "admin"

    # --- E-mail ----------------------------------------------------------
    # Used for password resets, project invitations and the data-request
    # correspondence. All optional: with no host configured the platform runs
    # perfectly well and simply does not send anything, which is the right
    # behaviour for a machine in a dig house with no outbound mail.
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    #: For Gmail this is an **App Password**, not the account password. See
    #: docs/email-setup.md. It belongs in .env on the machine that runs the
    #: platform, and nowhere else — .env is git-ignored for this reason.
    SMTP_PASSWORD: str | None = None
    #: STARTTLS on port 587 is what Gmail and most providers want. Implicit
    #: TLS on 465 is the alternative; setting both is a configuration error
    #: rather than belt and braces, and is refused below.
    SMTP_STARTTLS: bool = True
    SMTP_SSL: bool = False
    #: What recipients see in the From line. Defaults to the username, because
    #: Gmail rejects a From address the account is not allowed to send as.
    MAIL_FROM: str | None = None
    MAIL_FROM_NAME: str = "Stratum"
    SMTP_TIMEOUT_SECONDS: int = 20

    # --- Storage ---------------------------------------------------------
    #: "local" today; the storage service is an interface so S3/GCS can drop in.
    STORAGE_BACKEND: Literal["local"] = "local"
    STORAGE_ROOT: Path = Path("/data/uploads")
    MAX_UPLOAD_SIZE_MB: int = 200
    THUMBNAIL_SIZES: Annotated[list[int], NoDecode] = [200, 800]

    @field_validator("SMTP_PASSWORD", mode="before")
    @classmethod
    def _ungroup_app_password(cls, value: object) -> object:
        """Accept a Gmail App Password pasted exactly as Google shows it.

        Google displays the password in four groups of four — "abcd efgh ijkl
        mnop" — and the spaces are for reading, not part of the password. That
        is not obvious, and pasting what is on the screen fails with "Username
        and Password not accepted", which sounds like the wrong password
        rather than the right one with four extra characters.

        The rewrite is deliberately narrow: exactly four groups of exactly
        four, nothing else. A provider whose password genuinely contains
        spaces keeps it.
        """
        if not isinstance(value, str):
            return value
        groups = value.split(" ")
        if len(groups) == 4 and all(len(group) == 4 and group.isalnum() for group in groups):
            return "".join(groups)
        return value

    @field_validator("CORS_ORIGINS", "THUMBNAIL_SIZES", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept both ``a,b`` and JSON array syntax for list-valued settings.

        Comma-separated is what a person writes in a ``.env`` file or a Compose
        environment block, so it has to work; JSON is what pydantic-settings
        documents, so it has to keep working.
        """
        if not isinstance(value, str):
            return value

        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Value looks like a JSON array but could not be parsed: {exc}"
                ) from exc
        return [item.strip() for item in text.split(",") if item.strip()]

    @model_validator(mode="after")
    def _check_production_secrets(self) -> Settings:
        if self.ENVIRONMENT == "production":
            if not self.DATABASE_URL and self.POSTGRES_PASSWORD in {"archeo", "postgres", ""}:
                raise ValueError("POSTGRES_PASSWORD must be changed in production")
            if self.FIRST_ADMIN_PASSWORD == "ChangeMe!2024":
                raise ValueError("FIRST_ADMIN_PASSWORD must be changed in production")

        # Both at once is not belt and braces: STARTTLS upgrades a plain
        # connection, implicit TLS wraps it from the first byte, and a client
        # doing both talks TLS inside TLS to a server expecting neither. The
        # symptom is a timeout with no explanation, so it is refused here
        # where the reason can be given.
        if self.SMTP_SSL and self.SMTP_STARTTLS:
            raise ValueError(
                "SMTP_SSL and SMTP_STARTTLS cannot both be on. Use STARTTLS on "
                "port 587 (what Gmail wants), or SSL on port 465 — not both."
            )
        return self

    @property
    def mail_sender(self) -> str | None:
        """The address mail is sent from, falling back to the account itself."""
        return self.MAIL_FROM or self.SMTP_USERNAME

    @property
    def mail_configured(self) -> bool:
        """Whether there is enough here to send anything at all."""
        return bool(self.SMTP_HOST and self.mail_sender)

    @property
    def sqlalchemy_url(self) -> str:
        """Connection URL used by both the app and Alembic."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
