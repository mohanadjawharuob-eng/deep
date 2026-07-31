"""Declarative base plus the mixins shared by every table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# Deterministic constraint names keep Alembic autogenerate readable and its
# migrations reversible (anonymous constraints cannot be dropped by name).
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """UUID surrogate keys.

    Chosen over serial integers because record identifiers end up in QR codes
    and public URLs, where sequential IDs leak collection size and invite
    enumeration.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    """``created_at`` / ``updated_at`` maintained by the database clock."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class OwnedRecordMixin:
    """Ownership and visibility, required of every content record.

    The specification asks that each record carry an owner, editor/viewer lists
    and a public/private flag. Owner and visibility live here; editors and
    viewers are rows in ``record_permissions`` so grants can be made per record
    without widening every table.

    ``owner_id`` is nullable and ``ON DELETE SET NULL``: deleting a user must
    never cascade away excavation data.
    """

    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    @declared_attr
    @classmethod
    def owner_id(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(
            PGUUID(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        )
