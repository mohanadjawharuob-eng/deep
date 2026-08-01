"""Settings parsing.

These exist because a container that cannot read its own configuration exits
before it can explain why, and the environment Docker Compose supplies is not
the environment a developer has on their machine. Reading settings from the
Python defaults, as the rest of the suite does, exercises none of this.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings

#: Everything ``docker-compose.yml`` passes to the ``api`` service. If a
#: variable is added there, add it here — this is the shape the container
#: actually boots with.
COMPOSE_ENVIRONMENT = {
    "ENVIRONMENT": "development",
    "DEBUG": "false",
    "POSTGRES_HOST": "db",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "archeo",
    "POSTGRES_PASSWORD": "some-password",
    "POSTGRES_DB": "archeo",
    "SECRET_KEY": "a-secret-long-enough-to-be-plausible-0123456789",
    "ACCESS_TOKEN_EXPIRE_MINUTES": "30",
    "REFRESH_TOKEN_EXPIRE_DAYS": "14",
    "CORS_ORIGINS": "http://localhost:5173,http://localhost:3000",
    "FRONTEND_URL": "http://localhost:5173",
    "FIRST_ADMIN_EMAIL": "admin@example.org",
    "FIRST_ADMIN_USERNAME": "admin",
    "FIRST_ADMIN_PASSWORD": "ChangeMeNow!2024",
    "STORAGE_ROOT": "/data/uploads",
    "MAX_UPLOAD_SIZE_MB": "200",
    "THUMBNAIL_SIZES": "200,800",
    "RUN_MIGRATIONS": "true",
    "RUN_SEED": "true",
    "SEED_SAMPLE_DATA": "false",
}


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Isolate from the developer's own .env and exported variables."""
    for key in list(COMPOSE_ENVIRONMENT) + ["DATABASE_URL"]:
        monkeypatch.delenv(key, raising=False)
    # Settings reads ".env" relative to the working directory; point it at an
    # empty directory so a local file cannot mask the values under test.
    monkeypatch.chdir(tmp_path)
    return monkeypatch


class TestComposeEnvironment:
    def test_settings_load_from_the_compose_environment(self, clean_env) -> None:
        """The whole point: these exact variables must not crash the process."""
        for key, value in COMPOSE_ENVIRONMENT.items():
            clean_env.setenv(key, value)

        settings = Settings()

        assert settings.CORS_ORIGINS == ["http://localhost:5173", "http://localhost:3000"]
        assert settings.THUMBNAIL_SIZES == [200, 800]
        assert settings.POSTGRES_HOST == "db"
        assert settings.sqlalchemy_url.startswith("postgresql+psycopg://")


class TestListParsing:
    """pydantic-settings JSON-decodes list-typed variables inside the env source,
    before any validator runs. A comma-separated value — which is what anyone
    writes in a .env file — therefore failed with an unreadable error until the
    fields were annotated ``NoDecode``."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("http://a.org,http://b.org", ["http://a.org", "http://b.org"]),
            (" http://a.org , http://b.org ", ["http://a.org", "http://b.org"]),
            ("http://only.org", ["http://only.org"]),
            ('["http://a.org","http://b.org"]', ["http://a.org", "http://b.org"]),
            ("", []),
        ],
    )
    def test_cors_origins_accepts_both_notations(
        self, clean_env, raw: str, expected: list[str]
    ) -> None:
        clean_env.setenv("CORS_ORIGINS", raw)
        settings = Settings()
        assert settings.CORS_ORIGINS == expected

    def test_cors_origins_defaults_when_unset(self, clean_env) -> None:
        settings = Settings()
        assert settings.CORS_ORIGINS == [
            "http://localhost:5173",
            "http://localhost:3000",
        ]

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("200,800", [200, 800]), ("200,800,1600", [200, 800, 1600]), ("[400]", [400])],
    )
    def test_thumbnail_sizes_are_parsed_as_integers(
        self, clean_env, raw: str, expected: list[int]
    ) -> None:
        clean_env.setenv("THUMBNAIL_SIZES", raw)
        settings = Settings()
        assert settings.THUMBNAIL_SIZES == expected

    def test_malformed_json_array_says_so(self, clean_env) -> None:
        clean_env.setenv("CORS_ORIGINS", '["unterminated')
        with pytest.raises(ValueError, match="JSON array"):
            Settings()


class TestProductionGuards:
    def test_production_refuses_a_default_database_password(self, clean_env) -> None:
        for key, value in COMPOSE_ENVIRONMENT.items():
            clean_env.setenv(key, value)
        clean_env.setenv("ENVIRONMENT", "production")
        clean_env.setenv("POSTGRES_PASSWORD", "postgres")

        with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
            Settings()

    def test_production_refuses_the_default_admin_password(self, clean_env) -> None:
        for key, value in COMPOSE_ENVIRONMENT.items():
            clean_env.setenv(key, value)
        clean_env.setenv("ENVIRONMENT", "production")
        clean_env.setenv("FIRST_ADMIN_PASSWORD", "ChangeMe!2024")

        with pytest.raises(ValueError, match="FIRST_ADMIN_PASSWORD"):
            Settings()

    def test_production_accepts_real_secrets(self, clean_env) -> None:
        for key, value in COMPOSE_ENVIRONMENT.items():
            clean_env.setenv(key, value)
        clean_env.setenv("ENVIRONMENT", "production")

        settings = Settings()
        assert settings.ENVIRONMENT == "production"
