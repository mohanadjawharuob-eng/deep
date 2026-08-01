"""Accession numbers, in the collection's own format.

Museums do not adopt a new numbering scheme because software arrived. The
number is painted on the object, written in ledgers going back a century and
cited in every publication that mentions it — changing it is not a data
migration, it is a conservation intervention on several thousand objects.

So the platform imposes nothing. Each collection declares a *pattern*, the
platform validates against it, offers the next number in sequence, and — this
is the part that decides whether a collection can be migrated at all — records
a number that does not fit the pattern anyway, flagged as legacy.

A system that refuses to store ``1974.1a-bis`` because it wants
``NM.1974.0001`` is a system the collection stays out of.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.museum import Collection, MuseumObject

#: Placeholders a pattern may use.
#:
#: ``{prefix}``  the collection's ``accession_prefix``
#: ``{code}``    the collection's code
#: ``{year}``    four-digit year of accession
#: ``{yy}``      two-digit year
#: ``{seq}``     the running number, optionally width-padded as ``{seq:04d}``
PLACEHOLDERS = ("prefix", "code", "year", "yy", "seq")

#: A pattern is a template, not a format string to be evaluated. Only these
#: names are substituted, and anything else in braces is a mistake worth
#: reporting rather than a silent empty string.
_PLACEHOLDER_RE = re.compile(r"\{(\w+)(?::([^}]*))?\}")

DEFAULT_PATTERN = "{prefix}.{year}.{seq:04d}"


class AccessionError(ValueError):
    """The number cannot be issued or is not acceptable. Safe to show a user."""


@dataclass(frozen=True)
class PatternCheck:
    """Whether a number matches a pattern, and why not if it does not."""

    matches: bool
    expected_example: str
    reason: str | None = None


def validate_pattern(pattern: str) -> None:
    """Refuse a pattern the platform cannot fill in.

    Checked when the collection is configured rather than when the first
    object is catalogued, so a typo surfaces immediately instead of at the
    moment somebody is trying to accession a crate of finds.
    """
    if not pattern.strip():
        raise AccessionError("An accession pattern cannot be empty")

    found = _PLACEHOLDER_RE.findall(pattern)
    if not found:
        raise AccessionError(
            "That pattern has no placeholders, so every object would get the "
            "same number. Use at least {seq}, for example: " + DEFAULT_PATTERN
        )

    unknown = [name for name, _ in found if name not in PLACEHOLDERS]
    if unknown:
        raise AccessionError(
            f"Unknown placeholder(s): {', '.join('{' + name + '}' for name in unknown)}. "
            f"Available: {', '.join('{' + name + '}' for name in PLACEHOLDERS)}."
        )

    if not any(name == "seq" for name, _ in found):
        raise AccessionError(
            "A pattern needs {seq} somewhere, or numbers would repeat. "
            "For example: " + DEFAULT_PATTERN
        )

    # Prove it renders before it is stored.
    render(pattern, prefix="X", code="X", year=2024, sequence=1)


def render(pattern: str, *, prefix: str | None, code: str, year: int, sequence: int) -> str:
    """Fill a pattern in. Never evaluates the string as code."""
    values: dict[str, object] = {
        "prefix": prefix or code,
        "code": code,
        "year": year,
        "yy": f"{year % 100:02d}",
        "seq": sequence,
    }

    def substitute(match: re.Match[str]) -> str:
        name, spec = match.group(1), match.group(2)
        value = values.get(name)
        if value is None:
            raise AccessionError(f"Unknown placeholder {{{name}}} in the accession pattern")
        try:
            return format(value, spec) if spec else str(value)
        except (ValueError, TypeError) as exc:
            raise AccessionError(
                f"{{{name}:{spec}}} is not a usable format for that placeholder"
            ) from exc

    return _PLACEHOLDER_RE.sub(substitute, pattern)


def pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """A matcher for numbers that follow a pattern.

    Used to tell a typing slip from a genuinely different historical number:
    the first should be corrected, the second recorded as it stands.
    """
    parts: list[str] = []
    position = 0

    for match in _PLACEHOLDER_RE.finditer(pattern):
        parts.append(re.escape(pattern[position : match.start()]))
        name, spec = match.group(1), match.group(2)
        if name == "seq":
            width = _padded_width(spec)
            parts.append(rf"\d{{{width},}}" if width else r"\d+")
        elif name == "year":
            parts.append(r"\d{4}")
        elif name == "yy":
            parts.append(r"\d{2}")
        else:
            # prefix and code are literal text the collection chose.
            parts.append(r"[A-Za-z0-9._-]+")
        position = match.end()

    parts.append(re.escape(pattern[position:]))
    return re.compile("^" + "".join(parts) + "$")


def _padded_width(spec: str | None) -> int | None:
    if not spec:
        return None
    digits = re.match(r"0(\d+)d?$", spec)
    return int(digits.group(1)) if digits else None


def check(collection: Collection, number: str) -> PatternCheck:
    """Whether a number fits the collection's pattern."""
    pattern = collection.accession_pattern
    example = ""
    if pattern:
        example = render(
            pattern,
            prefix=collection.accession_prefix,
            code=collection.code,
            year=date.today().year,
            sequence=collection.accession_sequence + 1,
        )

    if not pattern:
        return PatternCheck(matches=True, expected_example="")

    if pattern_to_regex(pattern).match(number.strip()):
        return PatternCheck(matches=True, expected_example=example)

    return PatternCheck(
        matches=False,
        expected_example=example,
        reason=(
            f"{number!r} does not follow this collection's numbering. "
            f"Numbers here look like {example!r}."
        ),
    )


def next_number(session: Session, collection: Collection, *, when: date | None = None) -> str:
    """The next number in the collection's sequence.

    The stored counter is advisory, so it is reconciled against the highest
    number actually in use before issuing. Two curators accessioning at once,
    or a batch import that set numbers by hand, both leave the counter behind
    what the collection really holds.
    """
    pattern = collection.accession_pattern or DEFAULT_PATTERN
    year = (when or date.today()).year

    sequence = max(collection.accession_sequence, _highest_sequence(session, collection, pattern))

    for _ in range(1000):
        sequence += 1
        candidate = render(
            pattern,
            prefix=collection.accession_prefix,
            code=collection.code,
            year=year,
            sequence=sequence,
        )
        if not _number_taken(session, collection, candidate):
            collection.accession_sequence = sequence
            session.add(collection)
            return candidate

    raise AccessionError(
        "Could not find a free accession number after 1000 attempts. "
        "Check the collection's pattern for a placeholder that never varies."
    )


def _number_taken(session: Session, collection: Collection, number: str) -> bool:
    return bool(
        session.scalar(
            select(func.count())
            .select_from(MuseumObject)
            .where(
                MuseumObject.collection_id == collection.id,
                MuseumObject.accession_number == number,
            )
        )
    )


def _highest_sequence(session: Session, collection: Collection, pattern: str) -> int:
    """Largest sequence number already used, read back out of the numbers.

    Only numbers matching the pattern are considered — a legacy number like
    ``1974.1a`` says nothing about where the modern sequence has reached.
    """
    matcher = _sequence_capture(pattern)
    if matcher is None:
        return 0

    numbers = session.scalars(
        select(MuseumObject.accession_number).where(
            MuseumObject.collection_id == collection.id,
            MuseumObject.number_is_legacy.is_(False),
        )
    ).all()

    highest = 0
    for number in numbers:
        found = matcher.match(number or "")
        if found:
            try:
                highest = max(highest, int(found.group("seq")))
            except (ValueError, IndexError):  # pragma: no cover - defensive
                continue
    return highest


def _sequence_capture(pattern: str) -> re.Pattern[str] | None:
    """Like :func:`pattern_to_regex` but capturing the sequence."""
    parts: list[str] = []
    position = 0
    captured = False

    for match in _PLACEHOLDER_RE.finditer(pattern):
        parts.append(re.escape(pattern[position : match.start()]))
        name, spec = match.group(1), match.group(2)
        if name == "seq" and not captured:
            width = _padded_width(spec)
            parts.append(rf"(?P<seq>\d{{{width},}})" if width else r"(?P<seq>\d+)")
            captured = True
        elif name == "year":
            parts.append(r"\d{4}")
        elif name == "yy":
            parts.append(r"\d{2}")
        elif name == "seq":
            parts.append(r"\d+")
        else:
            parts.append(r"[A-Za-z0-9._-]+")
        position = match.end()

    if not captured:
        return None
    parts.append(re.escape(pattern[position:]))
    return re.compile("^" + "".join(parts) + "$")


def assign(
    session: Session,
    collection: Collection,
    *,
    requested: str | None,
    when: date | None = None,
) -> tuple[str, bool, str | None]:
    """Settle on a number for a new object.

    Returns ``(number, is_legacy, warning)``. A requested number is honoured
    unless the collection enforces its pattern; one that does not match is
    kept and flagged, so the oddity reads as known rather than as a mistake
    nobody noticed.
    """
    if not requested or not requested.strip():
        return next_number(session, collection, when=when), False, None

    number = requested.strip()
    if _number_taken(session, collection, number):
        raise AccessionError(
            f"{number!r} is already used in this collection. Accession numbers "
            f"must be unique within a collection."
        )

    result = check(collection, number)
    if result.matches:
        return number, False, None

    if collection.enforce_pattern:
        raise AccessionError(
            f"{result.reason} This collection requires numbers to follow its "
            f"pattern. Turn off 'enforce_pattern' to record exceptions."
        )

    return (
        number,
        True,
        (f"{result.reason} It has been recorded as given and flagged as a " f"legacy number."),
    )
