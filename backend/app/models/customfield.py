"""Fields an institution adds to the platform's forms.

Every heritage institution records something the next one does not: a ministry
file number, a Munsell reading nobody else takes, the name of the village
headman who reported the site. A platform that cannot hold those is a platform
people keep a spreadsheet beside — and the spreadsheet is where the real
recording then happens.

**Values live in the record's own ``metadata_json``.** No table per field, no
column added at runtime, no migration when somebody invents a field on a
Tuesday. The cost is that a custom field cannot be a foreign key and cannot be
indexed like a column; the benefit is that adding one is a form somebody fills
in rather than a deployment.

**The definition joins the layout.** That is the whole point of layouts being
data: a field defined here appears on the record card, in the edit form, in
the importer's column mapping and in the tray, because all four read the same
description. Nothing has to be told about it twice.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CustomField(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "custom_fields"

    #: Which form it appears on: ``site``, ``artifact``, ``museum_object``…
    record_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)

    #: The key it is stored under inside ``metadata_json``. Slug-shaped and
    #: fixed once created: renaming it would orphan every value already
    #: written under the old one.
    name: Mapped[str] = mapped_column(String(60), nullable=False)

    #: What people see. Changeable freely — it is only a caption.
    label: Mapped[str] = mapped_column(String(120), nullable=False)

    #: One of the layout's own kinds: text, textarea, number, integer, date,
    #: boolean, select. Deliberately not ``reference``: a custom field cannot
    #: be a foreign key, because nothing enforces it.
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="text")

    #: For ``select``, the choices, in order. Held here rather than in the
    #: taxonomy tables: an institution's own list is theirs, and putting it in
    #: the shared vocabulary would offer it to everybody.
    choices: Mapped[list[str] | None] = mapped_column(ARRAY(String(120)))

    help: Mapped[str | None] = mapped_column(Text)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Where it sits among the other custom fields on the same form.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Retired rather than deleted. Deleting a definition would leave values in
    #: `metadata_json` that nothing can read or explain — data that is present,
    #: unreachable and unaccounted for, which is the worst state for an archive.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("record_type", "name", name="uq_custom_fields_record_name"),)
