"""Tests for the user directory and administration endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User, UserRole
from app.services import mail
from tests.conftest import auth_headers, make_user


class TestDirectory:
    def test_listing_requires_authentication(self, client: TestClient) -> None:
        assert client.get("/api/v1/users").status_code == 401

    def test_listing_omits_contact_details(
        self, client: TestClient, db: Session, student: User, researcher: User
    ) -> None:
        response = client.get("/api/v1/users", headers=auth_headers(client, "student"))
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 2
        for item in body["items"]:
            assert "email" not in item and "phone" not in item

    def test_search_and_role_filter(
        self, client: TestClient, db: Session, student: User, researcher: User
    ) -> None:
        headers = auth_headers(client, "student")
        by_role = client.get("/api/v1/users?role=researcher", headers=headers).json()
        assert [item["username"] for item in by_role["items"]] == ["researcher"]

        by_name = client.get("/api/v1/users?q=stud", headers=headers).json()
        assert by_name["total"] == 1

    def test_pagination(self, client: TestClient, db: Session, student: User) -> None:
        for index in range(5):
            make_user(db, email=f"u{index}@x.org", username=f"user{index}")
        headers = auth_headers(client, "student")
        page = client.get("/api/v1/users?limit=2&offset=0", headers=headers).json()
        assert len(page["items"]) == 2
        assert page["total"] == 6


class TestProfile:
    def test_user_updates_own_profile(self, client: TestClient, db: Session, student: User) -> None:
        response = client.patch(
            "/api/v1/users/me",
            json={"full_name": "Renamed Student", "theme": "dark", "orcid": "0000-0002-1825-0097"},
            headers=auth_headers(client, "student"),
        )
        assert response.status_code == 200
        assert response.json()["full_name"] == "Renamed Student"
        assert response.json()["theme"] == "dark"

    def test_profile_update_cannot_change_role(
        self, client: TestClient, db: Session, student: User
    ) -> None:
        client.patch(
            "/api/v1/users/me",
            json={"role": "admin"},
            headers=auth_headers(client, "student"),
        )
        db.refresh(student)
        assert student.role is UserRole.STUDENT

    def test_invalid_orcid_is_rejected(
        self, client: TestClient, db: Session, student: User
    ) -> None:
        response = client.patch(
            "/api/v1/users/me",
            json={"orcid": "not-an-orcid"},
            headers=auth_headers(client, "student"),
        )
        assert response.status_code == 422

    def test_user_cannot_read_another_users_full_record(
        self, client: TestClient, db: Session, student: User, researcher: User
    ) -> None:
        response = client.get(
            f"/api/v1/users/{researcher.id}", headers=auth_headers(client, "student")
        )
        assert response.status_code == 404

    def test_user_can_read_their_own_full_record(
        self, client: TestClient, db: Session, student: User
    ) -> None:
        response = client.get(
            f"/api/v1/users/{student.id}", headers=auth_headers(client, "student")
        )
        assert response.status_code == 200
        assert response.json()["email"] == "student@example.org"


class TestAdministration:
    def test_only_admins_may_create_users(
        self, client: TestClient, db: Session, researcher: User
    ) -> None:
        response = client.post(
            "/api/v1/users",
            json={
                "email": "new@x.org",
                "username": "newbie",
                "full_name": "New Bie",
                "password": "ValidPassword1",
                "role": "researcher",
            },
            headers=auth_headers(client, "researcher"),
        )
        assert response.status_code == 403

    def test_admin_creates_a_user_with_a_role(
        self, client: TestClient, db: Session, admin: User
    ) -> None:
        response = client.post(
            "/api/v1/users",
            json={
                "email": "new@x.org",
                "username": "newbie",
                "full_name": "New Bie",
                "password": "ValidPassword1",
                "role": "researcher",
            },
            headers=auth_headers(client, "admin"),
        )
        assert response.status_code == 201
        # Creating an account answers with the account *and* what happened to
        # the welcome message, because those are two different outcomes and an
        # administrator needs both.
        assert response.json()["user"]["role"] == "researcher"

    def test_admin_promotes_a_user(
        self, client: TestClient, db: Session, admin: User, student: User
    ) -> None:
        response = client.patch(
            f"/api/v1/users/{student.id}",
            json={"role": "researcher"},
            headers=auth_headers(client, "admin"),
        )
        assert response.status_code == 200
        db.refresh(student)
        assert student.role is UserRole.RESEARCHER

    def test_cannot_demote_the_last_administrator(
        self, client: TestClient, db: Session, admin: User
    ) -> None:
        response = client.patch(
            f"/api/v1/users/{admin.id}",
            json={"role": "student"},
            headers=auth_headers(client, "admin"),
        )
        assert response.status_code == 400
        assert "last active administrator" in response.json()["detail"]

    def test_can_demote_an_administrator_when_another_remains(
        self, client: TestClient, db: Session, admin: User
    ) -> None:
        second = make_user(db, email="a2@x.org", username="admin2", role=UserRole.ADMIN)
        response = client.patch(
            f"/api/v1/users/{second.id}",
            json={"role": "researcher"},
            headers=auth_headers(client, "admin"),
        )
        assert response.status_code == 200

    def test_admin_cannot_deactivate_themselves(
        self, client: TestClient, db: Session, admin: User
    ) -> None:
        response = client.delete(f"/api/v1/users/{admin.id}", headers=auth_headers(client, "admin"))
        assert response.status_code == 400

    def test_deactivation_ends_the_users_sessions(
        self, client: TestClient, db: Session, admin: User, student: User
    ) -> None:
        student_headers = auth_headers(client, "student")
        assert client.get("/api/v1/auth/me", headers=student_headers).status_code == 200

        client.delete(f"/api/v1/users/{student.id}", headers=auth_headers(client, "admin"))

        assert client.get("/api/v1/auth/me", headers=student_headers).status_code == 401
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"identifier": "student", "password": "TestPassword1"},
            ).status_code
            == 401
        )

    def test_admin_password_reset_signs_the_user_out(
        self, client: TestClient, db: Session, admin: User, student: User
    ) -> None:
        student_headers = auth_headers(client, "student")
        response = client.post(
            f"/api/v1/users/{student.id}/reset-password",
            json={"new_password": "AdminSetPass1"},
            headers=auth_headers(client, "admin"),
        )
        assert response.status_code == 200
        assert client.get("/api/v1/auth/me", headers=student_headers).status_code == 401
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"identifier": "student", "password": "AdminSetPass1"},
            ).status_code
            == 200
        )

    def test_reset_clears_a_lockout(
        self, client: TestClient, db: Session, admin: User, student: User
    ) -> None:
        for _ in range(8):
            client.post(
                "/api/v1/auth/login",
                json={"identifier": "student", "password": "WrongPassword1"},
            )
        client.post(
            f"/api/v1/users/{student.id}/reset-password",
            json={"new_password": "AdminSetPass1"},
            headers=auth_headers(client, "admin"),
        )
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"identifier": "student", "password": "AdminSetPass1"},
            ).status_code
            == 200
        )


# --------------------------------------------------------------------------
# Telling somebody their account exists
# --------------------------------------------------------------------------
class TestWelcomeEmail:
    """The account is made whether or not the message goes out.

    Which of the two happened is the thing an administrator has to know: one
    who believes somebody was told their password will not tell them, and the
    person then cannot get in and does not know why.
    """

    def test_creating_an_account_says_what_happened_to_the_message(
        self, client: TestClient, admin: User
    ) -> None:
        response = client.post(
            "/api/v1/users",
            json={
                "full_name": "Mohand Jawhar",
                "username": "mjawhar",
                "email": "mjawhar@example.org",
                "password": "TrowelAndTape7",
                "role": "student",
            },
            headers=auth_headers(client, "admin"),
        )
        assert response.status_code == 201, response.text
        body = response.json()

        assert body["user"]["username"] == "mjawhar"
        # No SMTP in tests, which is the same as a site machine with no
        # outbound mail. The account exists regardless, and the note says so.
        assert body["welcome_email_sent"] is False
        assert "account was made" in body["welcome_email_note"]

        signed_in = client.post(
            "/api/v1/auth/login",
            json={"identifier": "mjawhar", "password": "TrowelAndTape7"},
        )
        assert signed_in.status_code == 200, signed_in.text

    def test_the_message_can_be_declined(self, client: TestClient, admin: User) -> None:
        response = client.post(
            "/api/v1/users",
            json={
                "full_name": "Quiet Person",
                "username": "quiet",
                "email": "quiet@example.org",
                "password": "TrowelAndTape7",
                "send_welcome_email": False,
            },
            headers=auth_headers(client, "admin"),
        )
        assert response.status_code == 201, response.text
        assert response.json()["welcome_email_sent"] is False
        assert "as asked" in response.json()["welcome_email_note"]

    def test_the_message_carries_the_details_and_says_to_change_the_password(self) -> None:
        subject, body, html = mail.welcome(
            full_name="Mohand Jawhar",
            username="mjawhar",
            password="TrowelAndTape7",
            address="http://localhost:5173",
            organisation="Department of Antiquities",
            role="student",
            invited_by="A. Director",
        )

        assert "Department of Antiquities" in subject
        for text in (body, html):
            assert "mjawhar" in text
            assert "TrowelAndTape7" in text
            assert "http://localhost:5173" in text
            # The password has travelled through e-mail in the clear, and the
            # message has to say so rather than imply the account is secure.
            assert "change" in text.lower()

    def test_a_name_cannot_smuggle_markup_into_the_message(self) -> None:
        _, _, html = mail.welcome(
            full_name="<script>alert(1)</script>",
            username="x",
            password="p",
            address="http://localhost",
            organisation="Dept & Co",
            role="student",
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "&amp;" in html


class TestValidationMessages:
    """A refused password says which rule it broke.

    The reasons live in `errors`, not in `detail` - a client that reads only
    `detail` shows "Validation failed", which is true, useless, and
    indistinguishable from a bug in the platform.
    """

    def test_a_weak_password_names_the_rule_it_broke(self, client: TestClient, admin: User) -> None:
        response = client.post(
            "/api/v1/users",
            json={
                "full_name": "Weak Password",
                "username": "weak",
                "email": "weak@example.org",
                "password": "1234567890",
            },
            headers=auth_headers(client, "admin"),
        )
        assert response.status_code == 422

        body = response.json()
        assert body["errors"], "the reasons must be in the response, not only the log"
        combined = " ".join(item["message"] for item in body["errors"])
        assert "lowercase" in combined
        assert "uppercase" in combined
        assert any(item["field"] == "password" for item in body["errors"])
