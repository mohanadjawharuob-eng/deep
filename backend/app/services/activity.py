"""Writing the audit trail.

Endpoints call :func:`log` rather than constructing rows themselves, so that
every entry carries the same shape and the request context (IP, user agent,
request id) is picked up automatically.
"""

from __future__ import annotations

import ipaddress
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.audit import ActivityLog
from app.models.enums import ActivityAction, ResourceType
from app.models.user import User


def client_ip(request: Request | None) -> str | None:
    """The caller's IP address, or ``None`` if it is not a usable address.

    ``ip_address`` is a PostgreSQL ``INET`` column, which rejects anything that
    is not an address — a Unix socket, a test client, or a proxy that put a
    hostname in ``X-Forwarded-For`` would otherwise turn an audit entry into a
    failed request. Validating here means a strange client cannot break the
    write it is being logged for.
    """
    if request is None:
        return None

    candidate = request.client.host if request.client else None
    # ``X-Forwarded-For`` is only meaningful behind a proxy we control; the
    # left-most entry is the original client when the chain is trusted.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        candidate = forwarded.split(",")[0].strip()

    if not candidate:
        return None
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def request_context(request: Request | None) -> dict[str, Any]:
    """Extract the auditable parts of a request."""
    if request is None:
        return {}
    return {
        "ip_address": client_ip(request),
        "user_agent": request.headers.get("user-agent", "")[:400] or None,
        "request_id": getattr(request.state, "request_id", None),
    }


def log(
    session: Session,
    *,
    action: ActivityAction,
    user: User | None = None,
    resource_type: ResourceType | None = None,
    resource_id: uuid.UUID | None = None,
    resource_label: str | None = None,
    changes: dict[str, Any] | None = None,
    summary: str | None = None,
    request: Request | None = None,
) -> ActivityLog:
    """Append one entry. The caller owns the transaction."""
    entry = ActivityLog(
        action=action,
        user_id=user.id if user else None,
        user_label=(user.full_name or user.username) if user else None,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_label=resource_label,
        changes=changes,
        summary=summary,
        **request_context(request),
    )
    session.add(entry)
    return entry


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Field-level changes between two snapshots, for the ``changes`` column.

    Values are coerced to strings because the column is JSONB and the inputs
    may contain dates, UUIDs and Decimals that JSON cannot represent directly.
    """
    changed: dict[str, dict[str, Any]] = {}
    for key in set(before) | set(after):
        old, new = before.get(key), after.get(key)
        if old != new:
            changed[key] = {
                "old": None if old is None else str(old),
                "new": None if new is None else str(new),
            }
    return changed
