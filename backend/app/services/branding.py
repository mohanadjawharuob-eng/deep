"""What the institution's copy of Stratum calls itself, and what it looks like.

An installation belongs to somebody. A department that has put its collection
into this platform should see its own mark on the page it works in all day, and
on the sign-in page it sends a new student to — not a product name they have no
relationship with. That is not decoration; it is the difference between "our
records system" and "some software somebody installed".

Stored in ``system_settings``, which already existed for exactly this and whose
docstring names "site title" as the case. Six keys rather than a new table: a
new table would need a migration, a singleton row, and a rule about what happens
if there are two.

The logo goes into the ordinary content-addressed file store, so it is deduped,
backed up and served by the same code as every photograph. Its **checksum is
part of the URL** — a logo that changes while its address does not is a logo
half the staff keep seeing the old version of for a week.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.taxonomy import SystemSetting

#: Prefix, so these are recognisable among whatever else the table grows.
_PREFIX = "branding."

ORGANISATION = f"{_PREFIX}organisation_name"
TAGLINE = f"{_PREFIX}tagline"
LOGO_PATH = f"{_PREFIX}logo_path"
LOGO_MIME = f"{_PREFIX}logo_mime"
LOGO_CHECKSUM = f"{_PREFIX}logo_checksum"
FOOTER_NOTE = f"{_PREFIX}footer_note"

#: Read by the sign-in page, which by definition has nobody signed in. The
#: logo's *bytes* are equally public; that is the point of a logo.
PUBLIC = {ORGANISATION, TAGLINE, LOGO_CHECKSUM}

_DESCRIPTIONS = {
    ORGANISATION: "Shown instead of 'Stratum' in the sidebar and on the sign-in page",
    TAGLINE: "The line under the name",
    LOGO_PATH: "Where the uploaded logo lives in the file store",
    LOGO_MIME: "The logo's media type, decided by decoding it rather than by its name",
    LOGO_CHECKSUM: "Changes when the logo does, so browsers stop showing the old one",
    FOOTER_NOTE: "Printed at the foot of exported workbooks and reports",
}


@dataclass(slots=True)
class Branding:
    """Everything a page needs to render the institution's identity."""

    organisation_name: str | None = None
    tagline: str | None = None
    footer_note: str | None = None
    logo_checksum: str | None = None

    @property
    def has_logo(self) -> bool:
        return self.logo_checksum is not None

    @property
    def logo_url(self) -> str | None:
        """The address the browser fetches.

        The checksum is in the query string rather than the path because the
        path has to keep working for a caller who has only the old URL. It is
        what makes a replaced logo appear immediately instead of whenever each
        person happens to clear their cache.
        """
        if not self.has_logo:
            return None
        return f"/api/v1/branding/logo?v={self.logo_checksum}"

    #: What the sidebar prints when nothing has been set.
    @property
    def display_name(self) -> str:
        return self.organisation_name or "Stratum"


def _rows(session: Session) -> dict[str, str | None]:
    statement = select(SystemSetting).where(SystemSetting.key.startswith(_PREFIX))
    return {row.key: row.value for row in session.scalars(statement)}


def read(session: Session) -> Branding:
    """The current branding. Never raises and never inserts."""
    values = _rows(session)
    return Branding(
        organisation_name=values.get(ORGANISATION) or None,
        tagline=values.get(TAGLINE) or None,
        footer_note=values.get(FOOTER_NOTE) or None,
        logo_checksum=values.get(LOGO_CHECKSUM) or None,
    )


def logo_location(session: Session) -> tuple[str, str] | None:
    """``(stored path, media type)`` for the logo, or ``None``."""
    values = _rows(session)
    path = values.get(LOGO_PATH)
    if not path:
        return None
    return path, values.get(LOGO_MIME) or "application/octet-stream"


def put(session: Session, key: str, value: str | None) -> None:
    """Set one key, creating the row if it is not there yet.

    An empty string is stored as ``None``: "" and "unset" mean the same thing
    for every one of these, and keeping both invites a check that forgets one.
    """
    cleaned = (value or "").strip() or None
    row = session.scalar(select(SystemSetting).where(SystemSetting.key == key))
    if row is None:
        row = SystemSetting(
            key=key,
            value=cleaned,
            value_type="string",
            description=_DESCRIPTIONS.get(key),
            is_public=key in PUBLIC,
        )
        session.add(row)
    else:
        row.value = cleaned
        # Repair a row written before a key was made public, so an old
        # installation behaves like a new one.
        row.is_public = key in PUBLIC
    session.flush()


def clear_logo(session: Session) -> None:
    for key in (LOGO_PATH, LOGO_MIME, LOGO_CHECKSUM):
        put(session, key, None)
