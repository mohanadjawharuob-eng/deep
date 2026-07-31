"""Application settings.

All configuration comes from environment variables (or a local ``.env`` file)
so the same image can be promoted from development to production untouched.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    #: Comma-separated list of origins allowed by CORS.
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # --- First administrator ---------------------------------------------
    # Created by ``scripts/seed.py`` so a fresh deployment is usable at once.
    FIRST_ADMIN_EMAIL: str = "admin@example.org"
    FIRST_ADMIN_PASSWORD: str = "ChangeMe!2024"
    FIRST_ADMIN_USERNAME: str = "admin"

    # --- Storage ---------------------------------------------------------
    #: "local" today; the storage service is an interface so S3/GCS can drop in.
    STORAGE_BACKEND: Literal["local"] = "local"
    STORAGE_ROOT: Path = Path("/data/uploads")
    MAX_UPLOAD_SIZE_MB: int = 200
    THUMBNAIL_SIZES: list[int] = [200, 800]

    @field_validator("CORS_ORIGINS", "THUMBNAIL_SIZES", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept both ``a,b`` and JSON list syntax for list-valued env vars."""
        if isinstance(value, str) and not value.strip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _check_production_secrets(self) -> Settings:
        if self.ENVIRONMENT == "production":
            if not self.DATABASE_URL and self.POSTGRES_PASSWORD in {"archeo", "postgres", ""}:
                raise ValueError("POSTGRES_PASSWORD must be changed in production")
            if self.FIRST_ADMIN_PASSWORD == "ChangeMe!2024":
                raise ValueError("FIRST_ADMIN_PASSWORD must be changed in production")
        return self

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
