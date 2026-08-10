"""Minting, checking and retiring the invitations that carry a data request.

Everything about the security of the feature is in this module, so that it can
be read in one sitting rather than reconstructed from six endpoints.

The rule the whole design rests on: **an invitation is a capability, not an
account.** Holding one lets you write files to exactly one record. It does not
let you read that record, list anything, see who else was asked, or reach any
other part of the platform. That is why the token can travel through e-mail —
the worst case for a leaked link is an unwanted file attached to one record,
which is recoverable, rather than a session on somebody's archive, which is
not.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_token
from app.models import DataRequest, DataRequestKind, DataRequestStatus

#: Long enough that guessing is not a strategy, short enough to survive being
#: pasted into an e-mail client that likes to break long lines.
TOKEN_BYTES = 32

#: The default life of an invitation. Long enough that somebody who reads mail
#: weekly still catches it; short enough that a forgotten request does not
#: leave a writable door open for a year.
DEFAULT_DAYS = 21
MAX_DAYS = 180

#: The states in which the link still works.
LIVE = (DataRequestStatus.OPEN, DataRequestStatus.SENT, DataRequestStatus.ANSWERED)


def new_token() -> tuple[str, str]:
    """A fresh invitation token and the hash to store for it."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return token, hash_token(token)


def invite_url(token: str) -> str:
    """Where the recipient goes. The token is in the path, not the query.

    A query string is the part of a URL that ends up in referrer headers,
    server access logs and analytics. A path segment ends up in the same access
    logs, so this is not a security boundary — but it keeps the token out of
    every third-party redirect the recipient's mail client performs on the way.
    """
    return f"{settings.FRONTEND_URL.rstrip('/')}/send/{token}"


def expiry(days: int | None = None) -> datetime:
    span = DEFAULT_DAYS if days is None else max(1, min(days, MAX_DAYS))
    return datetime.now(UTC) + timedelta(days=span)


class InviteProblem(Exception):
    """An invitation that cannot be used, with a reason fit to show a stranger.

    The message is deliberately the same shape whatever went wrong, and never
    says whether a link ever existed: "this link is no longer valid" for a
    cancelled request and for a token invented out of thin air alike. Somebody
    probing for live links learns nothing from the difference.
    """


def resolve(session: Session, token: str) -> DataRequest:
    """The request an invitation refers to, or a reason it cannot be used."""
    generic = InviteProblem(
        "This upload link is not valid. It may have expired, been used as many "
        "times as it was allowed, or been withdrawn. Ask whoever sent it for a "
        "new one."
    )

    if not token or len(token) > 512:
        raise generic

    request = session.scalars(
        select(DataRequest).where(DataRequest.token_hash == hash_token(token))
    ).first()
    if request is None:
        raise generic
    if request.status not in LIVE:
        raise generic
    if request.expires_at <= datetime.now(UTC):
        raise generic
    if request.uploads_left <= 0:
        raise generic
    return request


def record_upload(session: Session, request: DataRequest) -> None:
    """One file has arrived. Move the request on, and close it if it is full."""
    now = datetime.now(UTC)
    request.upload_count += 1
    if request.first_upload_at is None:
        request.first_upload_at = now
    if request.status in (DataRequestStatus.OPEN, DataRequestStatus.SENT):
        request.status = DataRequestStatus.ANSWERED
    if request.uploads_left <= 0:
        request.status = DataRequestStatus.CLOSED
        request.closed_at = now
    session.flush()


# --------------------------------------------------------------------------
# The invitation itself
# --------------------------------------------------------------------------
_ASKED_FOR = {
    DataRequestKind.PHOTOGRAPHS: "photographs",
    DataRequestKind.DOCUMENTS: "documents",
    DataRequestKind.DRAWINGS: "drawings",
    DataRequestKind.MODELS_3D: "3D models",
    DataRequestKind.ANYTHING: "files",
}


def asked_for(kind: DataRequestKind) -> str:
    return _ASKED_FOR.get(kind, "files")


def compose(request: DataRequest, token: str, *, organisation: str) -> tuple[str, str, str]:
    """Subject, plain text and HTML for the invitation.

    Written to be read by somebody who has never heard of this platform and did
    not ask to be involved: what is wanted, who wants it, what the link does,
    and when it stops working — in that order, because that is the order the
    questions occur.
    """
    thing = asked_for(request.kind)
    who = request.requested_by.full_name if request.requested_by else organisation
    url = invite_url(token)
    until = request.expires_at.strftime("%d %B %Y")
    greeting = f"Dear {request.recipient_name}," if request.recipient_name else "Hello,"

    subject = f"{thing.capitalize()} needed: {request.record_label}"

    note = f"\n\n{request.message.strip()}\n" if request.message and request.message.strip() else ""

    body = (
        f"{greeting}\n\n"
        f"{who} at {organisation} is asking for the {thing} for "
        f"{request.record_label}.{note}\n"
        f"You can send them here, without creating an account:\n\n"
        f"{url}\n\n"
        f"The link accepts up to {request.max_uploads} file"
        f"{'' if request.max_uploads == 1 else 's'} and stops working on {until}. "
        f"It can only be used to send files for this one record — it does not "
        f"give access to anything else.\n\n"
        f"If you were not expecting this, you can ignore it; nothing happens "
        f"until a file is sent.\n\n"
        f"— {organisation}\n"
    )

    escaped_note = (
        f"<p style='white-space:pre-wrap'>{_escape(request.message.strip())}</p>"
        if request.message and request.message.strip()
        else ""
    )
    html = (
        f"<div style=\"font-family:system-ui,-apple-system,'Segoe UI',sans-serif;"
        f'font-size:15px;line-height:1.55;color:#2b2118;max-width:34rem">'
        f"<p>{_escape(greeting)}</p>"
        f"<p><strong>{_escape(who)}</strong> at {_escape(organisation)} is asking for "
        f"the {thing} for <strong>{_escape(request.record_label)}</strong>.</p>"
        f"{escaped_note}"
        f'<p><a href="{_escape(url)}" style="display:inline-block;background:#8b3a1f;'
        f'color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none">'
        f"Send the {thing}</a></p>"
        f'<p style="font-size:13px;color:#6b5c4d">The link accepts up to '
        f"{request.max_uploads} file{'' if request.max_uploads == 1 else 's'} and stops "
        f"working on {_escape(until)}. It can only be used to send files for this one "
        f"record — it does not give access to anything else.</p>"
        f'<p style="font-size:13px;color:#6b5c4d">If you were not expecting this you can '
        f"ignore it; nothing happens until a file is sent.</p>"
        f'<p style="font-size:13px;color:#6b5c4d">— {_escape(organisation)}</p>'
        f"</div>"
    )
    return subject, body, html


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
