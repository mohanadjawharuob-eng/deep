"""Unit tests for password hashing and JWT handling."""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest

from app.core import security
from app.core.config import settings


class TestPasswordPolicy:
    @pytest.mark.parametrize(
        "password",
        ["ValidPassword1", "aB3" + "x" * 10, "Corr3ct-Horse-Battery"],
    )
    def test_accepts_compliant_passwords(self, password: str) -> None:
        security.validate_password(password)

    @pytest.mark.parametrize(
        ("password", "reason"),
        [
            ("Short1a", "too short"),
            ("alllowercase1", "no uppercase"),
            ("ALLUPPERCASE1", "no lowercase"),
            ("NoDigitsHere", "no digit"),
            ("A1" + "b" * 80, "over the bcrypt byte limit"),
        ],
    )
    def test_rejects_weak_passwords(self, password: str, reason: str) -> None:
        with pytest.raises(security.PasswordPolicyError):
            security.validate_password(password)


class TestPasswordHashing:
    def test_round_trip(self) -> None:
        digest = security.hash_password("ValidPassword1")
        assert security.verify_password("ValidPassword1", digest)
        assert not security.verify_password("ValidPassword2", digest)

    def test_salts_differ_between_hashes(self) -> None:
        first = security.hash_password("ValidPassword1")
        second = security.hash_password("ValidPassword1")
        assert first != second, "identical passwords must not produce identical digests"

    def test_malformed_hash_is_rejected_not_raised(self) -> None:
        assert not security.verify_password("anything", "not-a-bcrypt-hash")
        assert not security.verify_password("anything", "")


class TestTokens:
    def test_access_token_carries_subject_and_role(self) -> None:
        token, expires_at = security.create_access_token("user-123", "researcher")
        payload = security.decode_token(token, expected_type="access")
        assert payload["sub"] == "user-123"
        assert payload["role"] == "researcher"
        assert payload["type"] == "access"
        assert expires_at.timestamp() == pytest.approx(payload["exp"], abs=1)

    def test_refresh_token_type_is_enforced(self) -> None:
        refresh, _, _ = security.create_refresh_token("user-123")
        with pytest.raises(jwt.InvalidTokenError):
            security.decode_token(refresh, expected_type="access")
        assert security.decode_token(refresh, expected_type="refresh")["sub"] == "user-123"

    def test_each_token_has_a_unique_id(self) -> None:
        _, _, first = security.create_refresh_token("user-123")
        _, _, second = security.create_refresh_token("user-123")
        assert first != second

    def test_tampered_signature_is_rejected(self) -> None:
        token, _ = security.create_access_token("user-123", "student")
        header, payload, signature = token.split(".")
        forged = f"{header}.{payload}.{'A' * len(signature)}"
        with pytest.raises(jwt.InvalidTokenError):
            security.decode_token(forged)

    def test_token_signed_with_another_key_is_rejected(self) -> None:
        forged = jwt.encode(
            {"sub": "user-123", "type": "access", "exp": 9999999999, "jti": "x"},
            "a-different-secret",
            algorithm=settings.JWT_ALGORITHM,
        )
        with pytest.raises(jwt.InvalidTokenError):
            security.decode_token(forged)

    def test_expired_token_is_rejected(self) -> None:
        token, _, _ = security._create_token("user-123", "access", timedelta(seconds=-1))
        with pytest.raises(jwt.ExpiredSignatureError):
            security.decode_token(token)

    def test_alg_none_is_rejected(self) -> None:
        """The classic JWT downgrade attack must not work."""
        forged = jwt.encode(
            {"sub": "user-123", "type": "access", "exp": 9999999999, "jti": "x"},
            key="",
            algorithm="none",
        )
        with pytest.raises(jwt.InvalidTokenError):
            security.decode_token(forged)

    def test_token_missing_required_claims_is_rejected(self) -> None:
        forged = jwt.encode(
            {"sub": "user-123"}, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        )
        with pytest.raises(jwt.MissingRequiredClaimError):
            security.decode_token(forged)

    def test_token_hash_is_stable_and_distinct(self) -> None:
        assert security.hash_token("abc") == security.hash_token("abc")
        assert security.hash_token("abc") != security.hash_token("abd")
        assert len(security.hash_token("abc")) == 64
