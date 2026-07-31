"""End-to-end tests for the authentication endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_token
from app.models import ActivityAction, ActivityLog, RefreshToken, User
from tests.conftest import auth_headers, make_user

REGISTRATION = {
    "email": "New.Person@Example.org",
    "username": "NewPerson",
    "full_name": "New Person",
    "password": "ValidPassword1",
    "institution": "Test University",
}


class TestRegistration:
    def test_creates_a_student_account(self, client: TestClient, db: Session) -> None:
        response = client.post("/api/v1/auth/register", json=REGISTRATION)
        assert response.status_code == 201, response.text
        body = response.json()
        # E-mail and username are normalised to lower case so lookups match.
        assert body["email"] == "new.person@example.org"
        assert body["username"] == "newperson"
        assert body["role"] == "student"
        assert "password" not in body and "hashed_password" not in body

    def test_cannot_self_assign_a_role(self, client: TestClient, db: Session) -> None:
        response = client.post("/api/v1/auth/register", json={**REGISTRATION, "role": "admin"})
        assert response.status_code == 201
        assert response.json()["role"] == "student", "role in the body must be ignored"

    def test_rejects_duplicate_email(self, client: TestClient, db: Session) -> None:
        client.post("/api/v1/auth/register", json=REGISTRATION)
        response = client.post(
            "/api/v1/auth/register", json={**REGISTRATION, "username": "someoneelse"}
        )
        assert response.status_code == 409

    def test_rejects_duplicate_username_case_insensitively(
        self, client: TestClient, db: Session
    ) -> None:
        client.post("/api/v1/auth/register", json=REGISTRATION)
        response = client.post(
            "/api/v1/auth/register",
            json={**REGISTRATION, "email": "other@example.org", "username": "NEWPERSON"},
        )
        assert response.status_code == 409

    def test_rejects_weak_password(self, client: TestClient) -> None:
        response = client.post("/api/v1/auth/register", json={**REGISTRATION, "password": "weak"})
        assert response.status_code == 422

    def test_rejects_invalid_username_characters(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/register", json={**REGISTRATION, "username": "bad name!"}
        )
        assert response.status_code == 422


class TestLogin:
    def test_login_with_email_and_with_username(
        self, client: TestClient, db: Session, student: User
    ) -> None:
        for identifier in ("student@example.org", "student", "STUDENT@EXAMPLE.ORG"):
            response = client.post(
                "/api/v1/auth/login",
                json={"identifier": identifier, "password": "TestPassword1"},
            )
            assert response.status_code == 200, identifier
            body = response.json()
            assert body["token_type"] == "bearer"
            assert body["user"]["username"] == "student"
            assert body["access_token"] and body["refresh_token"]

    def test_wrong_password_is_rejected(self, client: TestClient, student: User) -> None:
        response = client.post(
            "/api/v1/auth/login",
            json={"identifier": "student", "password": "WrongPassword1"},
        )
        assert response.status_code == 401

    def test_unknown_and_wrong_password_give_the_same_message(
        self, client: TestClient, student: User
    ) -> None:
        """User enumeration must not be possible from the login response."""
        unknown = client.post(
            "/api/v1/auth/login",
            json={"identifier": "nobody@example.org", "password": "TestPassword1"},
        )
        wrong = client.post(
            "/api/v1/auth/login",
            json={"identifier": "student", "password": "WrongPassword1"},
        )
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json()["detail"] == wrong.json()["detail"]

    def test_inactive_account_cannot_sign_in(self, client: TestClient, db: Session) -> None:
        make_user(db, email="gone@example.org", username="gone", is_active=False)
        response = client.post(
            "/api/v1/auth/login",
            json={"identifier": "gone", "password": "TestPassword1"},
        )
        assert response.status_code == 401
        assert "deactivated" in response.json()["detail"].lower()

    def test_repeated_failures_lock_the_account(
        self, client: TestClient, db: Session, student: User
    ) -> None:
        for _ in range(8):
            client.post(
                "/api/v1/auth/login",
                json={"identifier": "student", "password": "WrongPassword1"},
            )
        # The correct password is now refused too, until the lock expires.
        response = client.post(
            "/api/v1/auth/login",
            json={"identifier": "student", "password": "TestPassword1"},
        )
        assert response.status_code == 401
        assert "locked" in response.json()["detail"].lower()

    def test_successful_login_clears_the_failure_counter(
        self, client: TestClient, db: Session, student: User
    ) -> None:
        for _ in range(3):
            client.post(
                "/api/v1/auth/login",
                json={"identifier": "student", "password": "WrongPassword1"},
            )
        client.post(
            "/api/v1/auth/login",
            json={"identifier": "student", "password": "TestPassword1"},
        )
        db.refresh(student)
        assert student.failed_login_count == 0
        assert student.last_login_at is not None

    def test_login_is_recorded_in_the_activity_log(
        self, client: TestClient, db: Session, student: User
    ) -> None:
        client.post(
            "/api/v1/auth/login",
            json={"identifier": "student", "password": "TestPassword1"},
        )
        entry = db.scalar(select(ActivityLog).where(ActivityLog.action == ActivityAction.LOGIN))
        assert entry is not None and entry.user_id == student.id

    def test_failed_login_is_recorded(self, client: TestClient, db: Session, student: User) -> None:
        client.post(
            "/api/v1/auth/login",
            json={"identifier": "student", "password": "WrongPassword1"},
        )
        entry = db.scalar(
            select(ActivityLog).where(ActivityLog.action == ActivityAction.LOGIN_FAILED)
        )
        assert entry is not None


class TestProtectedRoutes:
    def test_me_requires_a_token(self, client: TestClient) -> None:
        assert client.get("/api/v1/auth/me").status_code == 401

    def test_me_returns_the_signed_in_user(
        self, client: TestClient, db: Session, researcher: User
    ) -> None:
        headers = auth_headers(client, "researcher")
        response = client.get("/api/v1/auth/me", headers=headers)
        assert response.status_code == 200
        assert response.json()["username"] == "researcher"
        assert response.json()["role"] == "researcher"

    def test_garbage_token_is_rejected(self, client: TestClient) -> None:
        response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
        assert response.status_code == 401

    def test_refresh_token_is_not_accepted_as_an_access_token(
        self, client: TestClient, db: Session, student: User
    ) -> None:
        login = client.post(
            "/api/v1/auth/login",
            json={"identifier": "student", "password": "TestPassword1"},
        ).json()
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {login['refresh_token']}"},
        )
        assert response.status_code == 401

    def test_deactivating_a_user_invalidates_their_token(
        self, client: TestClient, db: Session, student: User
    ) -> None:
        headers = auth_headers(client, "student")
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

        student.is_active = False
        db.add(student)
        db.flush()

        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


class TestRefreshRotation:
    def test_refresh_returns_a_new_pair_and_revokes_the_old(
        self, client: TestClient, db: Session, student: User
    ) -> None:
        login = client.post(
            "/api/v1/auth/login",
            json={"identifier": "student", "password": "TestPassword1"},
        ).json()

        response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
        )
        assert response.status_code == 200
        rotated = response.json()
        assert rotated["refresh_token"] != login["refresh_token"]

        old = db.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_token(login["refresh_token"])
            )
        )
        assert old is not None and old.revoked_at is not None
        assert old.replaced_by_id is not None, "rotation should record the successor"

    def test_reusing_a_rotated_token_revokes_every_session(
        self, client: TestClient, db: Session, student: User
    ) -> None:
        login = client.post(
            "/api/v1/auth/login",
            json={"identifier": "student", "password": "TestPassword1"},
        ).json()
        rotated = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
        ).json()

        # Replay the token that was already exchanged.
        replay = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})
        assert replay.status_code == 401

        # The successor must be dead too — that is the point of the tripwire.
        followup = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
        )
        assert followup.status_code == 401

    def test_unknown_refresh_token_is_rejected(self, client: TestClient) -> None:
        response = client.post("/api/v1/auth/refresh", json={"refresh_token": "does-not-exist"})
        assert response.status_code == 401

    def test_expired_refresh_token_is_rejected(
        self, client: TestClient, db: Session, student: User
    ) -> None:
        login = client.post(
            "/api/v1/auth/login",
            json={"identifier": "student", "password": "TestPassword1"},
        ).json()
        stored = db.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_token(login["refresh_token"])
            )
        )
        stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.add(stored)
        db.flush()

        response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
        )
        assert response.status_code == 401


class TestSessions:
    def test_sessions_are_listed_and_can_be_revoked(
        self, client: TestClient, db: Session, student: User
    ) -> None:
        headers = auth_headers(client, "student")
        auth_headers(client, "student")  # a second "device"

        listing = client.get("/api/v1/auth/sessions", headers=headers)
        assert listing.status_code == 200
        sessions = listing.json()
        assert len(sessions) == 2

        revoked = client.delete(f"/api/v1/auth/sessions/{sessions[0]['id']}", headers=headers)
        assert revoked.status_code == 200
        assert len(client.get("/api/v1/auth/sessions", headers=headers).json()) == 1

    def test_cannot_revoke_another_users_session(
        self, client: TestClient, db: Session, student: User, researcher: User
    ) -> None:
        victim_headers = auth_headers(client, "researcher")
        victim_session = client.get("/api/v1/auth/sessions", headers=victim_headers).json()[0]

        attacker_headers = auth_headers(client, "student")
        response = client.delete(
            f"/api/v1/auth/sessions/{victim_session['id']}", headers=attacker_headers
        )
        assert response.status_code == 404

    def test_logout_all_devices(self, client: TestClient, db: Session, student: User) -> None:
        headers = auth_headers(client, "student")
        auth_headers(client, "student")

        response = client.post("/api/v1/auth/logout", json={"all_devices": True}, headers=headers)
        assert response.status_code == 200
        assert client.get("/api/v1/auth/sessions", headers=headers).json() == []


class TestPasswordChange:
    def test_changes_password_and_ends_other_sessions(
        self, client: TestClient, db: Session, student: User
    ) -> None:
        headers = auth_headers(client, "student")
        response = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "TestPassword1", "new_password": "BrandNewPass9"},
            headers=headers,
        )
        assert response.status_code == 200

        assert (
            client.post(
                "/api/v1/auth/login",
                json={"identifier": "student", "password": "TestPassword1"},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"identifier": "student", "password": "BrandNewPass9"},
            ).status_code
            == 200
        )

    def test_rejects_wrong_current_password(
        self, client: TestClient, db: Session, student: User
    ) -> None:
        headers = auth_headers(client, "student")
        response = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "NotTheOne1", "new_password": "BrandNewPass9"},
            headers=headers,
        )
        assert response.status_code == 400

    def test_rejects_reusing_the_same_password(
        self, client: TestClient, db: Session, student: User
    ) -> None:
        headers = auth_headers(client, "student")
        response = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "TestPassword1", "new_password": "TestPassword1"},
            headers=headers,
        )
        assert response.status_code == 400


class TestEmailHandling:
    def test_login_works_for_addresses_the_input_validator_would_reject(
        self, client: TestClient, db: Session
    ) -> None:
        """Reading a profile must never fail on a value already in the database.

        Institutional deployments use internal domains such as ``.local``,
        which ``EmailStr`` rejects. Those addresses can still reach the table
        (imports, direct inserts, a stricter validator arriving later), and a
        read path that re-validates would turn every login into a 500.
        """
        make_user(db, email="curator@museum.local", username="curator")

        response = client.post(
            "/api/v1/auth/login",
            json={"identifier": "curator@museum.local", "password": "TestPassword1"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["user"]["email"] == "curator@museum.local"

    def test_registration_still_rejects_such_addresses(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/register",
            json={**REGISTRATION, "email": "someone@museum.local"},
        )
        assert response.status_code == 422
