"""Turning mapped spreadsheet rows into records.

:mod:`app.services.spreadsheets` works out *what a column is*. This module
works out *what a cell means* — and refuses, loudly and per row, when it
cannot tell.

Two principles run through it:

**Never guess at a value.** A column mapped to Period holds ``Early Bronze
Age``, and the platform holds a period whose name is exactly that: matching it
is a lookup, not an inference. A cell reading ``EBA?`` matches nothing, and the
row is reported rather than filed under a period somebody will later have to
un-guess. The one latitude taken is case and surrounding whitespace, because
those are typing, not meaning.

**Report before writing.** :func:`plan` validates every row and returns what
would happen. Nothing in this module writes; the endpoint decides to commit
after a person has read the plan. A file that fails on row 431 must fail on
row 431 in the preview too, which is why the same function produces both.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services import forms

#: Cells that mean "nothing here". Spreadsheets are full of them.
BLANKS = {"", "-", "–", "—", "n/a", "na", "none", "null", "unknown", "?", "tbd"}

#: What a boolean column might say.
TRUE_WORDS = {"yes", "y", "true", "t", "1", "x", "✓"}
FALSE_WORDS = {"no", "n", "false", "f", "0"}

#: Separators inside a single cell holding a list — "bronze; iron", "bone, antler".
LIST_SPLIT = re.compile(r"\s*[;,/|]\s*|\s+and\s+")


class CellError(Exception):
    """One cell could not be understood. The message names the value."""


@dataclass
class RowResult:
    """What would happen to one row."""

    #: 1-based row number *in the file*, counting the heading row, so it matches
    #: what the user sees in Excel.
    row_number: int
    values: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class Plan:
    """What a whole import would do."""

    record_type: str
    rows: list[RowResult] = field(default_factory=list)

    @property
    def valid(self) -> list[RowResult]:
        return [row for row in self.rows if row.ok]

    @property
    def invalid(self) -> list[RowResult]:
        return [row for row in self.rows if not row.ok]


# --------------------------------------------------------------------------
# Value lists, reversed
# --------------------------------------------------------------------------
def _lookup_tables(session: Session, layout: forms.FormLayout) -> dict[str, dict[str, str]]:
    """For each value list, a map from what a person would type to the stored value.

    Both the label and the stored value are accepted as keys: a file exported
    from this platform holds identifiers, and a file typed by a curator holds
    names. Both should import.
    """
    resolved = forms.value_lists(session, layout.value_lists)
    tables: dict[str, dict[str, str]] = {}
    for name, options in resolved.items():
        table: dict[str, str] = {}
        for option in options:
            table[option["label"].strip().lower()] = option["value"]
            table[option["value"].strip().lower()] = option["value"]
            # Collections read "ARCH — Archaeological Collection"; a file will
            # hold one side or the other, rarely the whole thing.
            if "—" in option["label"]:
                left, right = option["label"].split("—", 1)
                table.setdefault(left.strip().lower(), option["value"])
                table.setdefault(right.strip().lower(), option["value"])
        tables[name] = table
    return tables


# --------------------------------------------------------------------------
# Coercion
# --------------------------------------------------------------------------
def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in BLANKS
    return False


_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")


def _to_number(value: Any, *, integer: bool) -> int | float:
    if isinstance(value, bool):
        raise CellError(f"{value!r} is not a number")
    if isinstance(value, int | float):
        return int(value) if integer else float(value)

    text = str(value).strip()
    # "12.5 cm", "approx. 40", "c. 120 g" — the unit belongs to the field, and
    # the number is what is wanted. A cell with two numbers is ambiguous and
    # is refused rather than resolved.
    found = _NUMBER.findall(text)
    if len(found) != 1:
        raise CellError(
            f"{text!r} is not a single number"
            + (" — it contains more than one" if len(found) > 1 else "")
        )
    cleaned = found[0].replace(",", ".")
    number = float(cleaned)
    if integer:
        if not number.is_integer():
            raise CellError(f"{text!r} is not a whole number")
        return int(number)
    return number


#: Date formats a spreadsheet actually contains, in the order worth trying.
#: Ambiguous day/month order is not guessed: see :func:`_to_date`.
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y")


def _to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    for pattern in _DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue

    # 03/04/2019 is the 3rd of April in Europe and the 4th of March in America,
    # and the file does not say which. Guessing writes a wrong date that nobody
    # will ever notice. Refusing costs one find-and-replace in Excel.
    if re.fullmatch(r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}", text):
        raise CellError(
            f"{text!r} could be day/month or month/day and the file does not "
            f"say which. Format the column as YYYY-MM-DD and import again"
        )
    raise CellError(f"{text!r} is not a date this recognises; use YYYY-MM-DD")


def _to_year(value: Any) -> int:
    """A signed year, where negative is BCE — the platform's convention."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return int(value)

    text = str(value).strip()
    match = re.fullmatch(r"(?i)\s*(-?\d{1,5})\s*(bce?|bc|ce|ad)?\s*", text)
    if match is None:
        raise CellError(f"{text!r} is not a year")
    year = int(match.group(1))
    era = (match.group(2) or "").lower()
    if era in ("bc", "bce"):
        return -abs(year)
    return year


def _to_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    raise CellError(f"{text!r} is not yes or no")


def _to_list(value: Any) -> list[str]:
    if isinstance(value, list | tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    parts = [part.strip() for part in LIST_SPLIT.split(str(value))]
    return [part for part in parts if part]


def coerce(
    spec: forms.FormField,
    value: Any,
    *,
    lookups: dict[str, dict[str, str]],
) -> Any:
    """One cell, as the field wants it. Raises :class:`CellError` with a reason."""
    if _is_blank(value):
        return None

    kind = spec.kind

    if kind in ("text", "textarea"):
        text = str(value).strip()
        if spec.max_length and len(text) > spec.max_length:
            raise CellError(
                f"is {len(text)} characters, longer than the {spec.max_length} this field holds"
            )
        return text

    if kind == "integer":
        # Year fields are integers holding a signed year, not a count.
        if spec.name in ("date_from", "date_to"):
            return _to_year(value)
        return _to_number(value, integer=True)

    if kind == "number":
        return _to_number(value, integer=False)

    if kind == "boolean":
        return _to_boolean(value)

    if kind == "date":
        return _to_date(value).isoformat()

    if kind == "datetime":
        if isinstance(value, datetime):
            return value.isoformat()
        return f"{_to_date(value).isoformat()}T00:00:00"

    if kind in ("select", "reference"):
        if spec.resolved_late:
            # Passed through as written. Nothing here knows enough to resolve
            # it — see ``FormField.resolved_late`` — and guessing at this layer
            # would mean matching a context number against every site.
            return str(value).strip()
        table = lookups.get(spec.value_list or "", {})
        if not table:
            # A reference with no value list behind it (a storage location, an
            # artifact) can only be given as an identifier.
            return _as_uuid(value, spec)
        key = str(value).strip().lower()
        if key in table:
            return table[key]
        raise CellError(f"{str(value).strip()!r} is not one of the values this field accepts")

    if kind in ("multiselect", "tags"):
        items = _to_list(value)
        table = lookups.get(spec.value_list or "", {})
        if not table:
            return items
        resolved = []
        for item in items:
            key = item.lower()
            if key not in table:
                raise CellError(f"{item!r} is not one of the values this field accepts")
            resolved.append(table[key])
        return resolved

    if kind == "json":
        return value

    return str(value).strip()


def _as_uuid(value: Any, spec: forms.FormField) -> str:
    text = str(value).strip()
    try:
        return str(uuid.UUID(text))
    except ValueError as exc:
        raise CellError(
            f"{text!r} is not an identifier. This column needs the platform's "
            f"own id for the {spec.references or 'record'} it points at; set it "
            f"after import instead"
        ) from exc


# --------------------------------------------------------------------------
# Planning a run
# --------------------------------------------------------------------------
def plan(
    session: Session,
    record_type: str,
    rows: list[dict[str, Any]],
    mapping: dict[str, str | None],
    *,
    defaults: dict[str, Any] | None = None,
    header_row: int = 1,
) -> Plan:
    """Validate every row and report what would happen. Writes nothing.

    The same function backs the preview and the commit, so what the preview
    promised is what the commit does — a preview computed by different code
    is a preview that eventually lies.
    """
    layout = forms.get_layout(record_type)
    if layout is None:
        raise ValueError(f"There is no import layout for {record_type!r}")

    fields = forms.field_index(layout)
    lookups = _lookup_tables(session, layout)

    # Only columns pointing at a field that exists and is writable.
    active = {
        column: target
        for column, target in mapping.items()
        if target and target in fields and not fields[target].read_only
    }
    ignored = {target for target in mapping.values() if target and fields.get(target, None) is None}

    # A value set once for the whole file goes through exactly the same
    # coercion a column does. Before this it went in raw, which worked only
    # because the one thing anybody set that way was already an identifier —
    # the moment somebody sets a shared date or quantity, "2026-08-10" reaches
    # the database as a string and the difference between the two routes
    # becomes a bug nobody can see. The lookup tables accept a stored value as
    # well as a label, so an identifier still resolves to itself.
    settled: dict[str, Any] = {}
    default_errors: list[str] = []
    for name, raw in (defaults or {}).items():
        spec = fields.get(name)
        if spec is None or spec.read_only:
            continue
        try:
            coerced = coerce(spec, raw, lookups=lookups)
        except CellError as exc:
            default_errors.append(f"{spec.label} (set for every row): {exc}")
            continue
        if coerced is not None:
            settled[name] = coerced

    result = Plan(record_type=record_type)

    for index, row in enumerate(rows):
        outcome = RowResult(row_number=header_row + index + 1)

        if ignored:
            outcome.warnings.append(
                f"Ignored columns mapped to fields this record does not have: "
                f"{', '.join(sorted(ignored))}"
            )
        outcome.errors.extend(default_errors)

        values: dict[str, Any] = dict(settled)
        for column, target in active.items():
            spec = fields[target]
            try:
                coerced = coerce(spec, row.get(column), lookups=lookups)
            except CellError as exc:
                outcome.errors.append(f"{spec.label} (column {column!r}): {exc}")
                continue
            if coerced is not None:
                values[target] = coerced

        for name, spec in fields.items():
            if spec.required and not spec.read_only and values.get(name) in (None, "", []):
                # An accession number is required but may be issued by the
                # platform, so its absence is a decision, not a failure.
                if name == "accession_number":
                    outcome.warnings.append("Will be given the next accession number")
                    continue
                # Two ways to supply it, and the one people reach for is the
                # second: a sheet of contexts almost never names its site,
                # because whoever made it knew. Naming only the column leaves
                # them editing the spreadsheet to add a column of one repeated
                # value.
                outcome.errors.append(
                    f"{spec.label} is required and this row has none. Map a column "
                    f"to it, or set one {spec.label.lower()} for every row in the file."
                )

        outcome.values = values
        result.rows.append(outcome)

    return result
