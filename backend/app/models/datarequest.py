"""Asking somebody outside the platform for a file, and letting them send it.

The problem this solves is mundane and constant: the photographs of a find are
on a colleague's laptop, the permit scan is in the ministry's e-mail, the
survey data is with the contractor. Today that is an e-mail thread, a
WeTransfer link that expires in seven days, and a file that ends up in
somebody's Downloads folder rather than in the archive.

So: a request is a **record with an invitation attached**. It names one record
and one thing being asked for, and it carries a link that grants exactly one
power — write files to that one record. No sign-in, no account, no read access
to anything, and it stops working the moment it expires, is cancelled, or has
been used as many times as it was allowed.

Two decisions worth stating, because they look like oversights otherwise:

**The token is not stored.** Only its hash is, the same way a password is. The
link exists in the invitation e-mail and nowhere else; a stolen database gives
an attacker no working links. The cost is that the platform cannot re-display a
link it has already sent — it can only issue a new one, which is the correct
behaviour anyway.

**A request survives its record being deleted.** ``ondelete="CASCADE"`` would
quietly erase the evidence that a file was asked for and never arrived, which
is exactly the question somebody asks six months later.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import DataRequestKind, DataRequestStatus

if TYPE_CHECKING:
    from app.models.user import User


class DataRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "data_requests"

    # ---------------------------------------------------------------- what
    #: Which record the files will attach themselves to. Exactly one of the
    #: four is set — the same four parents every photograph and document
    #: already hangs from, so an arriving file needs no special case.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sites.id", ondelete="SET NULL"), index=True
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="SET NULL"), index=True
    )
    context_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("excavation_contexts.id", ondelete="SET NULL"), index=True
    )
    #: An accessioned object. The commonest thing a museum needs asked for is a
    #: photograph of an object somebody else has.
    museum_object_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("museum_objects.id", ondelete="SET NULL"), index=True
    )

    #: What the record was called when the request was made. Kept as text so
    #: the list still reads sensibly after a record is renamed or removed —
    #: "the photographs of A-102" is what the recipient was told, whatever
    #: A-102 is called now.
    record_label: Mapped[str] = mapped_column(String(300), nullable=False)

    kind: Mapped[DataRequestKind] = mapped_column(
        # ``values_callable`` throughout, as everywhere else in this codebase:
        # without it SQLAlchemy stores the member *name* while the migration
        # created the type from the member *values*, and the two disagree on
        # the first insert against a real database.
        Enum(
            DataRequestKind,
            name="data_request_kind",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=DataRequestKind.PHOTOGRAPHS,
    )
    #: The ask, in the requester's own words. Goes into the e-mail verbatim.
    message: Mapped[str | None] = mapped_column(Text)

    # ------------------------------------------------------------- to whom
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    recipient_name: Mapped[str | None] = mapped_column(String(200))

    # ------------------------------------------------------------ the link
    #: SHA-256 of the token. See the module docstring.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: How many files this invitation may deliver in total. A photographer
    #: sending a set needs more than one; a permit scan needs one.
    max_uploads: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    upload_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --------------------------------------------------------------- state
    status: Mapped[DataRequestStatus] = mapped_column(
        Enum(
            DataRequestStatus,
            name="data_request_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=DataRequestStatus.OPEN,
        index=True,
    )
    #: Why the invitation could not be delivered, when it could not. Shown to
    #: the requester, because "sent" and "not sent" are the difference between
    #: waiting and chasing.
    delivery_note: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_upload_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    requested_by: Mapped[User | None] = relationship("User", lazy="joined")

    __table_args__ = (
        # The two questions the list screen asks: "what am I still waiting
        # for" and "what is about to expire".
        Index("ix_data_requests_status_expiry", "status", "expires_at"),
    )

    @property
    def parent_ids(self) -> dict[str, uuid.UUID | None]:
        return {
            "project_id": self.project_id,
            "site_id": self.site_id,
            "artifact_id": self.artifact_id,
            "context_id": self.context_id,
            "museum_object_id": self.museum_object_id,
        }

    @property
    def uploads_left(self) -> int:
        return max(0, self.max_uploads - self.upload_count)
