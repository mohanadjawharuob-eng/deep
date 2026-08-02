"""Granting and revoking module access.

Access is deliberately explicit: a user reaches a module because somebody gave
them a row, not because their job title implies it. The one exception is the
platform administrator, who holds every module by definition and needs no rows.

New accounts are seeded with the access their signup role implies, in the
modules listed in :data:`~app.core.permissions.SEEDED_MODULES` — archaeology
and the activity hub — so that registering gets somebody as far as recording
work and putting a date in the shared calendar without an administrator having
to act first. Everything beyond that is granted deliberately.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import DEFAULT_MODULE_ACCESS, SEEDED_MODULES
from app.models.enums import Module, ModuleLevel, UserRole
from app.models.user import User, UserModuleAccess


def grant(
    session: Session,
    user: User,
    module: Module,
    level: ModuleLevel,
    *,
    granted_by: User | None = None,
    note: str | None = None,
) -> UserModuleAccess:
    """Give ``user`` a level in ``module``, replacing any level they held.

    Returns the row so the caller can log what changed. Idempotent: granting
    the level someone already holds is not an error and writes nothing new.
    """
    existing = session.scalar(
        select(UserModuleAccess).where(
            UserModuleAccess.user_id == user.id,
            UserModuleAccess.module == module,
        )
    )
    if existing is not None:
        existing.level = level
        if granted_by is not None:
            existing.granted_by_id = granted_by.id
        if note is not None:
            existing.note = note
        session.flush()
        return existing

    row = UserModuleAccess(
        user_id=user.id,
        module=module,
        level=level,
        granted_by_id=granted_by.id if granted_by is not None else None,
        note=note,
    )
    session.add(row)
    session.flush()
    # The relationship is eagerly loaded, so a permission check later in this
    # same request would otherwise still see the pre-grant collection.
    session.refresh(user, ["module_access"])
    return row


def revoke(session: Session, user: User, module: Module) -> bool:
    """Remove a user's access to a module. True if anything was removed."""
    existing = session.scalar(
        select(UserModuleAccess).where(
            UserModuleAccess.user_id == user.id,
            UserModuleAccess.module == module,
        )
    )
    if existing is None:
        return False
    session.delete(existing)
    session.flush()
    session.refresh(user, ["module_access"])
    return True


def grant_defaults(session: Session, user: User, *, granted_by: User | None = None) -> None:
    """Give a newly created account the access its role implies.

    Administrators get nothing here — they hold every module implicitly, and
    writing rows for them would make revoking one look meaningful when it is
    not.
    """
    if user.role is UserRole.ADMIN:
        return
    level = DEFAULT_MODULE_ACCESS.get(user.role)
    if level is None:
        return
    for module in SEEDED_MODULES:
        grant(
            session,
            user,
            module,
            level,
            granted_by=granted_by,
            note="Granted automatically when the account was created",
        )


def current_access(session: Session, user_id: uuid.UUID) -> dict[Module, ModuleLevel]:
    """Every module a user can reach, and at what level."""
    rows = session.scalars(
        select(UserModuleAccess).where(UserModuleAccess.user_id == user_id)
    ).all()
    return {row.module: row.level for row in rows}
