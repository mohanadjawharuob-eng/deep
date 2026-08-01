"""Test fixtures.

Tests run against a real PostgreSQL with PostGIS, not SQLite: the schema uses
geometry columns, JSONB, arrays and native enums, none of which SQLite can
model. A throwaway database is created once per session and dropped afterwards.

Point ``TEST_DATABASE_URL`` at a server you control, or let it default to the
one in ``.env``/the environment with ``_test`` appended to the database name.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

# Must precede any import of application settings, which are read once and
# cached. bcrypt at the production work factor costs ~0.3 s per hash, and the
# suite creates hundreds of users; the minimum factor keeps the tests honest
# about the hashing path while making them fast enough to run on every save.
os.environ.setdefault("BCRYPT_ROUNDS", "4")

# Likewise: the storage service builds its root from the settings at import
# time, so uploads have to be redirected before that happens. Without this the
# suite would write into whatever ``STORAGE_ROOT`` a developer's ``.env`` points
# at, which is their real uploads directory.
os.environ.setdefault("STORAGE_ROOT", str(Path(tempfile.gettempdir()) / "archeo-test-uploads"))

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.models import Module, ModuleLevel, User, UserRole
from app.services import access


def _test_database_url() -> str:
    explicit = os.getenv("TEST_DATABASE_URL")
    if explicit:
        return explicit
    url = make_url(settings.sqlalchemy_url)
    return str(url.set(database=f"{url.database}_test"))


TEST_URL = _test_database_url()


@pytest.fixture(scope="session", autouse=True)
def storage_root() -> Iterator[Path]:
    """Start from an empty uploads tree and leave nothing behind.

    Content-addressed storage means a file left over from a previous run would
    be silently deduplicated against, so a test asserting that bytes were
    written could pass without anything having been written.
    """
    root = Path(os.environ["STORAGE_ROOT"])
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="session")
def engine():
    """Create the test database, build the schema, drop it at the end."""
    url = make_url(TEST_URL)
    admin_url = url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    with admin_engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{url.database}"'))

    test_engine = create_engine(TEST_URL, poolclass=None)
    with test_engine.connect() as connection:
        # The schema needs PostGIS present before any geometry column is made.
        for extension in ("postgis", "pg_trgm", "unaccent", "btree_gin"):
            connection.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{extension}"'))
        connection.commit()

    Base.metadata.create_all(test_engine)

    yield test_engine

    test_engine.dispose()
    with admin_engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
    admin_engine.dispose()


@pytest.fixture
def db(engine) -> Iterator[Session]:
    """A session wrapped in a transaction that is rolled back after each test.

    Every test therefore starts from the same clean schema without paying to
    recreate it.
    """
    connection = engine.connect()
    transaction = connection.begin()
    # ``create_savepoint`` makes the session join the fixture's transaction via
    # SAVEPOINTs, so an endpoint calling ``commit()`` releases its savepoint
    # rather than ending the outer transaction — the rollback below still undoes
    # everything the test did.
    session = sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )()
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    """A test client whose requests all use the rolled-back session."""
    from app.api.deps import get_db
    from app.main import app

    def override_get_db() -> Iterator[Session]:
        # Mirrors the real dependency, including the commit — without it,
        # writes would sit unflushed in the session and a later ``refresh``
        # would silently discard them. The savepoint mode set on the session
        # keeps that commit from ending the fixture's outer transaction.
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_user(
    db: Session,
    *,
    email: str = "user@example.org",
    username: str = "user",
    role: UserRole = UserRole.STUDENT,
    password: str = "TestPassword1",
    is_active: bool = True,
    modules: dict[Module, ModuleLevel] | None = None,
    grant_defaults: bool = True,
) -> User:
    """Create a user with the module access their role implies.

    ``modules`` grants beyond that default — pass it to build the cross-module
    users the permission model exists for, e.g. an archaeology editor who is
    only a viewer in the museum. Set ``grant_defaults=False`` when the point of
    the test is somebody with *no* archaeology access, which the role default
    would otherwise hand them.
    """
    user = User(
        email=email,
        username=username,
        full_name=username.replace(".", " ").title(),
        hashed_password=hash_password(password),
        role=role,
        is_active=is_active,
        is_verified=True,
    )
    db.add(user)
    db.flush()

    if grant_defaults:
        access.grant_defaults(db, user)
    for module, level in (modules or {}).items():
        access.grant(db, user, module, level)
    return user


@pytest.fixture
def admin(db: Session) -> User:
    return make_user(db, email="admin@example.org", username="admin", role=UserRole.ADMIN)


@pytest.fixture
def researcher(db: Session) -> User:
    return make_user(
        db, email="researcher@example.org", username="researcher", role=UserRole.RESEARCHER
    )


@pytest.fixture
def student(db: Session) -> User:
    return make_user(db, email="student@example.org", username="student", role=UserRole.STUDENT)


@pytest.fixture
def visitor(db: Session) -> User:
    return make_user(db, email="visitor@example.org", username="visitor", role=UserRole.VISITOR)


def auth_headers(client: TestClient, identifier: str, password: str = "TestPassword1") -> dict:
    """Sign in and return an ``Authorization`` header."""
    response = client.post(
        "/api/v1/auth/login", json={"identifier": identifier, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
