"""Sending e-mail, and the settings behind it.

Mail is optional throughout: a machine in a dig house with no outbound mail is
a supported way to run the platform. So the tests here are mostly about
failing *usefully* — a message that cannot be sent must not take down the
request that triggered it, and a misconfiguration must say what is wrong
rather than time out.
"""

from __future__ import annotations

import smtplib
import ssl
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import Settings
from app.services import mail


class TestAppPasswordPasting:
    """Google shows an App Password in four groups of four.

    The spaces are for reading and are not part of the password, which is not
    obvious — and pasting what is on the screen fails with "Username and
    Password not accepted", a message that sounds like the wrong password
    rather than the right one with four extra characters in it.
    """

    def test_the_grouped_form_google_shows_is_accepted(self) -> None:
        assert Settings(SMTP_PASSWORD="abcd efgh ijkl mnop").SMTP_PASSWORD == "abcdefghijklmnop"

    def test_the_plain_form_is_left_alone(self) -> None:
        assert Settings(SMTP_PASSWORD="abcdefghijklmnop").SMTP_PASSWORD == "abcdefghijklmnop"

    @pytest.mark.parametrize(
        "given",
        [
            "my real pass word",  # a genuine passphrase
            "ab cd ef gh",  # four groups, but not of four
            "abcd efgh ijkl mno",  # last group short
            "abcd efgh ijkl",  # only three groups
            "abcd efgh ijkl mnop qrst",  # five
        ],
    )
    def test_anything_that_is_not_that_exact_shape_is_kept(self, given: str) -> None:
        """Narrow on purpose. A provider whose passwords contain spaces must
        not have them silently removed."""
        assert given == Settings(SMTP_PASSWORD=given).SMTP_PASSWORD


class TestSettings:
    def test_both_kinds_of_encryption_at_once_is_refused(self) -> None:
        """Not belt and braces: STARTTLS upgrades a plain connection, implicit
        TLS wraps it from the first byte, and doing both talks TLS inside TLS
        to a server expecting neither. The symptom is an unexplained timeout,
        so it is refused where the reason can be given."""
        with pytest.raises(ValueError, match="cannot both be on"):
            Settings(SMTP_SSL=True, SMTP_STARTTLS=True)

    def test_mail_is_sent_from_the_account_unless_told_otherwise(self) -> None:
        """Gmail refuses a From address the account may not send as, so the
        account itself is the only safe default."""
        settings = Settings(SMTP_USERNAME="store@example.org")

        assert settings.mail_sender == "store@example.org"

    def test_an_explicit_from_address_wins(self) -> None:
        settings = Settings(SMTP_USERNAME="robot@example.org", MAIL_FROM="records@museum.org")

        assert settings.mail_sender == "records@museum.org"

    def test_nothing_configured_means_nothing_is_sent(self) -> None:
        assert Settings().mail_configured is False


class TestSending:
    def test_an_unconfigured_platform_reports_rather_than_raises(self) -> None:
        """A password reset that cannot be e-mailed is still a reset an
        administrator can hand over in person. It must not become a 500."""
        with patch.object(mail, "settings", Settings()):
            result = mail.send("someone@example.org", "Hello", "Body")

        assert result.ok is False
        assert "not configured" in result.detail

    def test_a_rejected_password_is_explained_in_words(self) -> None:
        """ "(535, b'5.7.8 Username and Password not accepted')" tells somebody
        who has just pasted an App Password nothing about what they did."""
        configured = Settings(
            SMTP_HOST="smtp.example.org",
            SMTP_USERNAME="a@example.org",
            SMTP_PASSWORD="abcdefghijklmnop",
        )
        server = MagicMock()
        server.__enter__.return_value = server
        server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"nope")

        with (
            patch.object(mail, "settings", configured),
            patch.object(mail, "_connection", return_value=server),
        ):
            result = mail.check()

        assert result.ok is False
        assert "App Password" in result.detail

    def test_an_unreachable_server_names_the_address_it_tried(self) -> None:
        configured = Settings(
            SMTP_HOST="smtp.example.org",
            SMTP_USERNAME="a@example.org",
            SMTP_PASSWORD="abcdefghijklmnop",
        )

        with (
            patch.object(mail, "settings", configured),
            patch.object(mail, "_connection", side_effect=TimeoutError()),
        ):
            result = mail.check()

        assert result.ok is False
        assert "smtp.example.org:587" in result.detail

    def test_a_failure_to_send_is_reported_not_raised(self) -> None:
        configured = Settings(
            SMTP_HOST="smtp.example.org",
            SMTP_USERNAME="a@example.org",
            SMTP_PASSWORD="abcdefghijklmnop",
        )
        server = MagicMock()
        server.__enter__.return_value = server
        server.send_message.side_effect = smtplib.SMTPRecipientsRefused({})

        with (
            patch.object(mail, "settings", configured),
            patch.object(mail, "_connection", return_value=server),
        ):
            result = mail.send("nobody@example.org", "Hello", "Body")

        assert result.ok is False
        assert "refused the recipient" in result.detail

    def test_a_refused_sender_names_the_address_it_tried_to_send_as(self) -> None:
        """Gmail refuses a From address the account may not send as, and the
        fix is to unset MAIL_FROM — which nobody guesses from "sender
        refused"."""
        configured = Settings(
            SMTP_HOST="smtp.example.org",
            SMTP_USERNAME="robot@example.org",
            SMTP_PASSWORD="abcdefghijklmnop",
            MAIL_FROM="someone.else@museum.org",
        )
        server = MagicMock()
        server.__enter__.return_value = server
        server.send_message.side_effect = smtplib.SMTPSenderRefused(553, b"no", "x")

        with (
            patch.object(mail, "settings", configured),
            patch.object(mail, "_connection", return_value=server),
        ):
            result = mail.send("a@example.org", "Hello", "Body")

        assert "someone.else@museum.org" in result.detail
        assert "MAIL_FROM" in result.detail

    def test_a_handshake_failure_points_at_the_port(self) -> None:
        """Port 465 with STARTTLS, or 587 with SSL, fails in the handshake —
        and "SSLError" tells nobody which of the two they got wrong."""
        configured = Settings(
            SMTP_HOST="smtp.example.org",
            SMTP_USERNAME="a@example.org",
            SMTP_PASSWORD="abcdefghijklmnop",
        )

        with (
            patch.object(mail, "settings", configured),
            patch.object(mail, "_connection", side_effect=ssl.SSLError("wrong version number")),
        ):
            result = mail.check()

        assert "587" in result.detail and "465" in result.detail

    def test_every_smtp_error_is_an_oserror_so_order_matters(self) -> None:
        """The reason the branches in `_explain` are ordered the way they are.
        A blanket OSError branch above the specific ones reports a refused
        recipient as "cannot reach the server", which sends whoever is
        debugging to look at their firewall over a typo in an address."""
        assert issubclass(smtplib.SMTPException, OSError)

    def test_a_sent_message_carries_the_name_and_the_address(self) -> None:
        configured = Settings(
            SMTP_HOST="smtp.example.org",
            SMTP_USERNAME="store@example.org",
            MAIL_FROM_NAME="Stratum",
        )
        server = MagicMock()
        server.__enter__.return_value = server

        with (
            patch.object(mail, "settings", configured),
            patch.object(mail, "_connection", return_value=server),
        ):
            result = mail.send("curator@example.org", "Kit is overdue", "Two items.")

        assert result.ok is True
        message = server.send_message.call_args.args[0]
        assert message["From"] == "Stratum <store@example.org>"
        assert message["To"] == "curator@example.org"
        assert message["Subject"] == "Kit is overdue"

    def test_several_recipients_go_on_one_message(self) -> None:
        configured = Settings(SMTP_HOST="smtp.example.org", SMTP_USERNAME="store@example.org")
        server = MagicMock()
        server.__enter__.return_value = server

        with (
            patch.object(mail, "settings", configured),
            patch.object(mail, "_connection", return_value=server),
        ):
            mail.send(["a@example.org", "b@example.org"], "Notice", "Body")

        assert server.send_message.call_args.args[0]["To"] == "a@example.org, b@example.org"

    def test_the_result_reads_as_a_boolean(self) -> None:
        """Callers say `if mail.send(...)`, so the object has to behave."""
        assert bool(mail.Result(True, "")) is True
        assert bool(mail.Result(False, "")) is False
