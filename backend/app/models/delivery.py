"""Files prepared for somebody to collect.

Everything the platform holds is behind an account, which is right, and is
wrong for the commonest request an institution actually gets: *send me the
photographs of the jar and the finds register*. The person asking is a ministry
officer, a visiting specialist, a journalist. They will not be given an account
and should not need one.

So a delivery is a **bundle with a door of its own**. Somebody inside picks the
files, the platform writes them to the assigned disk under names a person can
read, zips them, and sends the recipient a link with a token in it. The link
expires. Nothing about the rest of the archive is reachable through it.

Two things this deliberately does not do.

**It does not write to anybody else's computer.** There is no mechanism by
which a web platform can put a folder on somebody's desktop, and any design
that appears to is lying about where the file went. What it does is put the
folder on the disk the institution assigned, and tell the person where to get
it. On the same machine that folder *is* local — which is the part that was
actually wanted.

**It does not move or copy the archive's own files.** The bundle is a second
copy made for sending. Deleting a delivery deletes the bundle and nothing else.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import DeliveryStatus

if TYPE_CHECKING:
    from app.models.user import User


class Delivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One bundle of files, prepared for one person."""

    __tablename__ = "deliveries"

    #: What this is, in the sender's words. Appears in the e-mail, on the
    #: collection page, and as the name of the folder on disk - one phrase
    #: doing three jobs, so it is worth asking for rather than generating.
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    to_name: Mapped[str] = mapped_column(String(200), nullable=False)
    to_email: Mapped[str] = mapped_column(String(320), nullable=False)

    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(
            DeliveryStatus,
            name="delivery_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=DeliveryStatus.PREPARING,
        index=True,
    )

    #: What went in, as recorded at the time. Kept as identifiers rather than
    #: rows in a join table because the question later is "what did we send
    #: them", and that has to survive one of the photographs being deleted.
    photograph_ids: Mapped[list | None] = mapped_column(JSONB)
    document_ids: Mapped[list | None] = mapped_column(JSONB)
    sheet_ids: Mapped[list | None] = mapped_column(JSONB)

    #: The folder on the assigned disk, and the zip beside it. Both relative to
    #: the storage root, so moving the disk does not invalidate the record.
    folder_path: Mapped[str | None] = mapped_column(String(500))
    zip_path: Mapped[str | None] = mapped_column(String(500))
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Files the database knew about and the disk did not, named rather than
    #: silently dropped: a bundle that is quietly short is worse than one that
    #: says what is missing.
    missing: Mapped[list | None] = mapped_column(JSONB)

    #: The secret in the link. Long, random, and the only thing standing
    #: between the internet and this bundle - so it is never logged and never
    #: shown in a listing.
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Whether the recipient was told. False when mail is not configured, which
    #: is common on these installations and must not look like a failure.
    notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Delivery {self.title!r} to {self.to_email}>"
