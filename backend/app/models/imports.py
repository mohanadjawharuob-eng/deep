"""Spreadsheet imports, kept as records rather than as a moment.

An import is not a button press; it is an event with consequences that somebody
will ask about months later — *where did these four hundred objects come from,
and who decided that the column headed "Loc." was the storage location?*

So the batch persists: the file as uploaded, the mapping a person approved, the
counts, and the identifiers of everything it created. That last part is what
makes an import undoable and auditable; without it, a mistaken run is
indistinguishable from ordinary cataloguing the moment it finishes.
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
from app.models.enums import ImportStatus

if TYPE_CHECKING:
    from app.models.user import User


class ImportBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One spreadsheet, on its way in."""

    __tablename__ = "import_batches"

    #: Which layout the columns are mapped onto — "museum_object" today.
    record_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)

    #: What the file was called when it arrived. Shown back to the user, so it
    #: is stored as given rather than as the sanitised name on disk.
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Content-addressed path in the file store.
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Which sheet, and which row holds the headings. Both are decisions a
    #: person makes on the analysis screen, and both change what the columns
    #: are, so they belong to the batch and not to a request.
    sheet_name: Mapped[str | None] = mapped_column(String(200))
    header_row: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    #: Column headings as found, in file order.
    columns: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: ``{column heading: field name or null}``, as approved by a person. Null
    #: means the column is deliberately not imported, which is a decision worth
    #: recording as much as a mapping is.
    mapping: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: Values applied to every row — the collection, usually, when the file
    #: does not name one.
    defaults: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    status: Mapped[ImportStatus] = mapped_column(
        Enum(ImportStatus, name="import_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ImportStatus.ANALYSED,
        index=True,
    )

    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Per-row failures from the last preview or commit: row number and reason.
    #: Kept so the person who ran it can fix the file without running it again.
    errors: Mapped[list | None] = mapped_column(JSONB)
    #: Identifiers of the records this batch created, so it can be undone.
    created_ids: Mapped[list | None] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(Text)

    # --- The sheet room --------------------------------------------------
    # A spreadsheet that arrived is a document in its own right, not only a
    # step in an import. Somebody will ask for "the finds register as Ahmad
    # sent it in March" long after the records it made have been corrected
    # forty times, and the honest answer is the file itself.
    #
    # Which is why the platform keeps two: the original, byte for byte, and a
    # copy rebuilt from the records as they stand now. Overwriting the first
    # with the second would destroy the only evidence of what was actually
    # received.

    #: The sheet this one replaces. Set when a corrected version of the same
    #: file arrives, so the room shows one current sheet and its history rather
    #: than four files with confusingly similar names.
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL")
    )
    #: Put away. Still downloadable, out of the way of the working list.
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: Where the rebuilt copy lives, and when it was last rebuilt. Both null
    #: until somebody asks for one - building it for every sheet on every edit
    #: would be work nobody asked for on files nobody opens.
    refreshed_path: Mapped[str | None] = mapped_column(String(500))
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])

    @property
    def shelf_state(self) -> str:
        """One word for where this sheet stands, for a person reading a list.

        Deliberately computed rather than stored: every part of it is already
        recorded somewhere, and a stored state is a state that goes out of step
        with the facts it was meant to summarise.
        """
        if self.superseded_by_id is not None:
            return "superseded"
        if self.is_archived:
            return "archived"
        if self.status is ImportStatus.COMMITTED:
            return "imported"
        if self.status is ImportStatus.FAILED:
            return "failed"
        return "received"
