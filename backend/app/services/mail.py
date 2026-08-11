"""Sending e-mail, and knowing whether it can be sent at all.

The platform is designed to run on a laptop in a dig house, which often has no
outbound mail and sometimes no internet. So mail is **optional throughout**:
with no host configured, :func:`send` returns ``False`` and logs it, and every
caller carries on. Nothing in the platform breaks because a message could not
go out — a password reset that cannot be e-mailed is still a reset an
administrator can hand over in person.

What this deliberately does *not* do is fail silently in the other direction.
A configured mailer that cannot connect logs the reason, and :func:`check`
exists so somebody can find that out on purpose, before a colleague is waiting
on an invitation that never arrives.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import settings

logger = logging.getLogger("archeo.mail")


@dataclass(slots=True)
class Result:
    """What happened, in a form both a script and a screen can use."""

    ok: bool
    detail: str

    def __bool__(self) -> bool:
        return self.ok


def _connection() -> smtplib.SMTP | smtplib.SMTP_SSL:
    """Open a connection, in whichever of the two ways the settings ask for."""
    host = settings.SMTP_HOST or ""
    timeout = settings.SMTP_TIMEOUT_SECONDS

    if settings.SMTP_SSL:
        # Implicit TLS: encrypted from the first byte. Port 465.
        return smtplib.SMTP_SSL(host, settings.SMTP_PORT, timeout=timeout)

    server = smtplib.SMTP(host, settings.SMTP_PORT, timeout=timeout)
    if settings.SMTP_STARTTLS:
        # STARTTLS: begins in the clear and upgrades. Port 587, and what Gmail
        # expects. `create_default_context` verifies the certificate — without
        # it the upgrade is theatre that any router in between can undo.
        server.starttls(context=ssl.create_default_context())
    return server


def _explain(error: Exception) -> str:
    """Turn an SMTP failure into something worth reading.

    The library's own messages are accurate and useless: "(535, b'5.7.8
    Username and Password not accepted')" tells somebody who has just pasted a
    Gmail App Password nothing about what they did wrong.
    """
    # Specific first, and the reachability check *last* among the SMTP errors:
    # every one of smtplib's exceptions inherits from OSError, so a branch on
    # OSError placed above them swallows the lot and reports a refused
    # recipient as "cannot reach the server" — sending whoever is debugging to
    # look at their firewall over a typo in an address.
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return (
            "The mail server rejected the username or password.\n"
            "For Gmail this must be a 16-character App Password, not the "
            "password you type into Gmail itself, and two-step verification "
            "has to be switched on for the account first. "
            "See docs/email-setup.md."
        )
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return "The server refused the recipient's address."
    if isinstance(error, smtplib.SMTPSenderRefused):
        return (
            f"The server refused to send as {settings.mail_sender!r}.\n"
            "Gmail will only send as the account itself or an address it has "
            "been told the account may use. Leave MAIL_FROM unset to send as "
            "the account."
        )
    if isinstance(error, ssl.SSLError):
        return (
            f"The encrypted handshake with {settings.SMTP_HOST} failed.\n"
            "Usually this means the port and the encryption do not match: "
            "port 587 wants SMTP_STARTTLS=true, port 465 wants SMTP_SSL=true."
        )
    if isinstance(error, smtplib.SMTPConnectError | TimeoutError | ConnectionError | OSError):
        return (
            f"Could not reach {settings.SMTP_HOST}:{settings.SMTP_PORT}.\n"
            "Either this machine has no internet, or something between here "
            "and there is blocking the port — some networks block outbound "
            "mail on purpose."
        )
    return f"{type(error).__name__}: {error}"


def check() -> Result:
    """Connect and sign in, without sending anything.

    Worth having as its own thing. A guide that ends "now wait and hope" is a
    guide that leaves somebody stuck; this ends with a yes or a no and, when
    it is a no, the reason.
    """
    if not settings.SMTP_HOST:
        return Result(False, "No SMTP_HOST is set, so the platform will not send e-mail.")
    if not settings.mail_sender:
        return Result(
            False, "No SMTP_USERNAME or MAIL_FROM is set, so there is no address to send from."
        )

    try:
        with _connection() as server:
            if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
    except Exception as error:  # noqa: BLE001 - every failure is reportable
        return Result(False, _explain(error))

    return Result(
        True,
        f"Connected to {settings.SMTP_HOST}:{settings.SMTP_PORT} "
        f"and signed in as {settings.SMTP_USERNAME}. "
        f"Mail will be sent from {settings.mail_sender}.",
    )


def send(
    to: str | list[str],
    subject: str,
    body: str,
    *,
    html: str | None = None,
    reply_to: str | None = None,
) -> Result:
    """Send one message.

    Never raises. Mail is a convenience in this platform, not a dependency,
    and a failed invitation must not take down the request that triggered it.
    """
    recipients = [to] if isinstance(to, str) else list(to)
    if not recipients:
        return Result(False, "No recipients")

    if not settings.mail_configured:
        # Not an error. A site machine with no outbound mail is a supported
        # way to run this, and saying so at debug level keeps the logs honest
        # without filling them.
        logger.debug("Mail not configured; %r to %s was not sent", subject, recipients)
        return Result(False, "E-mail is not configured on this server.")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((settings.MAIL_FROM_NAME, settings.mail_sender or ""))
    message["To"] = ", ".join(recipients)
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")

    try:
        with _connection() as server:
            if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.send_message(message)
    except Exception as error:  # noqa: BLE001 - see the docstring
        detail = _explain(error)
        logger.warning("Could not send %r to %s: %s", subject, recipients, detail)
        return Result(False, detail)

    logger.info("Sent %r to %s", subject, recipients)
    return Result(True, f"Sent to {', '.join(recipients)}")


# --------------------------------------------------------------------------
# The message a new colleague gets
# --------------------------------------------------------------------------
def welcome(
    *,
    full_name: str,
    username: str,
    password: str,
    address: str,
    organisation: str,
    role: str,
    invited_by: str | None = None,
) -> tuple[str, str, str]:
    """Subject, plain text and HTML telling somebody their account exists.

    It carries the first password, which is a deliberate and limited choice.
    The password is temporary, the administrator who typed it already knows it,
    and the alternative - a set-your-own-password link - is a token flow this
    platform does not have yet. What that costs is that the password travels
    through e-mail in the clear, so the message says plainly that it should be
    changed, and says it before anything else.
    """
    who = full_name or username
    greeting = f"Dear {who}," if who else "Hello,"

    subject = f"Your {organisation} account"

    body = (
        f"{greeting}\n\n"
        f"{invited_by or organisation} has made you an account on "
        f"{organisation}'s records platform.\n\n"
        f"  Address:   {address}\n"
        f"  Username:  {username}\n"
        f"  Password:  {password}\n\n"
        f"CHANGE THAT PASSWORD once you are in. It was typed by whoever made "
        f"the account and it has travelled through e-mail, so it is not "
        f"private. Your profile page is where you change it.\n\n"
        f"Your account is a {role} account. What you can see and change is set "
        f"per part of the platform, so if something you expect is missing, ask "
        f"whoever made the account rather than assuming it is broken.\n\n"
        f"Every change in the platform is recorded against the person who made "
        f"it, which is the reason you have your own account rather than sharing "
        f"one.\n\n"
        f"- {organisation}\n"
    )

    html = (
        f"<div style=\"font-family:system-ui,-apple-system,'Segoe UI',sans-serif;"
        f'font-size:15px;line-height:1.55;color:#2b2118;max-width:34rem">'
        f"<p>{_escape(greeting)}</p>"
        f"<p><strong>{_escape(invited_by or organisation)}</strong> has made you an "
        f"account on {_escape(organisation)}'s records platform.</p>"
        f'<table style="border-collapse:collapse;margin:1rem 0;font-size:14px">'
        f'<tr><td style="padding:3px 14px 3px 0;color:#6b5c4d">Address</td>'
        f'<td><a href="{_escape(address)}">{_escape(address)}</a></td></tr>'
        f'<tr><td style="padding:3px 14px 3px 0;color:#6b5c4d">Username</td>'
        f"<td><code>{_escape(username)}</code></td></tr>"
        f'<tr><td style="padding:3px 14px 3px 0;color:#6b5c4d">Password</td>'
        f"<td><code>{_escape(password)}</code></td></tr>"
        f"</table>"
        f'<p style="background:#fdf3e3;border-left:3px solid #a67c00;padding:10px 14px">'
        f"<strong>Change that password once you are in.</strong> It was typed by "
        f"whoever made the account and it has travelled through e-mail, so it is "
        f"not private. Your profile page is where you change it.</p>"
        f"<p>Your account is a <strong>{_escape(role)}</strong> account. What you can "
        f"see and change is set per part of the platform, so if something you expect "
        f"is missing, ask whoever made the account rather than assuming it is "
        f"broken.</p>"
        f'<p style="font-size:13px;color:#6b5c4d">Every change is recorded against the '
        f"person who made it, which is the reason you have your own account rather "
        f"than sharing one.</p>"
        f'<p style="font-size:13px;color:#6b5c4d">- {_escape(organisation)}</p>'
        f"</div>"
    )
    return subject, body, html


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
