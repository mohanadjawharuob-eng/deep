"""BibTeX, read and written.

The one thing that decides whether a reference manager can be adopted: whether
the bibliography somebody has spent ten years building can come in, and whether
it can leave again. A library you cannot export is a library nobody sensible
puts anything into.

BibTeX rather than RIS or CSL-JSON because it is what every tool exports and
what LaTeX consumes, and because it is the format an archaeologist is most
likely to already have on disk.

Written by hand rather than pulled in as a dependency. The parser here is
small — a few hundred lines against a format whose ugly corners are well known —
and the alternative is a dependency in the production image for a feature used
on the day a library is migrated and then twice a year.

Three of those corners are handled deliberately, because they are what break a
real ``.bib`` file rather than a synthetic one:

**Braces protect capitalisation.** ``{DNA}`` and ``{Tell el-Demo}`` mean "do not
lower-case this", and a parser that strips braces blindly turns a site name into
a sentence-cased mistake in every citation that follows.

**Fields nest braces.** ``title = {A study of {Nabataean} pottery}`` cannot be
read by finding the next ``}``; it needs counting.

**A file is full of things that are not entries.** ``@comment``, ``@string``,
preambles, and free text between entries. They are skipped rather than treated
as errors, because a file that fails to import at line 4000 for a reason nobody
can see is a file that does not get imported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models.enums import ReferenceType

#: BibTeX entry type -> what this platform calls it.
#:
#: The unmapped ones fall to OTHER rather than being refused: a reference with
#: the wrong type is still a reference somebody can find and correct, and a
#: file that refuses to import is a file that stays where it is.
_TYPES: dict[str, ReferenceType] = {
    "article": ReferenceType.ARTICLE,
    "book": ReferenceType.BOOK,
    "booklet": ReferenceType.BOOK,
    "inbook": ReferenceType.CHAPTER,
    "incollection": ReferenceType.CHAPTER,
    "inproceedings": ReferenceType.CONFERENCE,
    "conference": ReferenceType.CONFERENCE,
    "proceedings": ReferenceType.CONFERENCE,
    "phdthesis": ReferenceType.THESIS,
    "mastersthesis": ReferenceType.THESIS,
    "thesis": ReferenceType.THESIS,
    "techreport": ReferenceType.REPORT,
    "report": ReferenceType.REPORT,
    "manual": ReferenceType.REPORT,
    "unpublished": ReferenceType.ARCHIVE,
    "misc": ReferenceType.OTHER,
    "dataset": ReferenceType.DATASET,
    "online": ReferenceType.WEBPAGE,
    "electronic": ReferenceType.WEBPAGE,
    "www": ReferenceType.WEBPAGE,
}

#: And back again, for export.
_OUT: dict[ReferenceType, str] = {
    ReferenceType.ARTICLE: "article",
    ReferenceType.BOOK: "book",
    ReferenceType.CHAPTER: "incollection",
    ReferenceType.THESIS: "phdthesis",
    ReferenceType.REPORT: "techreport",
    ReferenceType.CONFERENCE: "inproceedings",
    ReferenceType.ARCHIVE: "unpublished",
    ReferenceType.DATASET: "misc",
    ReferenceType.MAP: "misc",
    ReferenceType.WEBPAGE: "online",
    ReferenceType.OTHER: "misc",
}

#: BibTeX field -> the column it fills. Several BibTeX names land on one column
#: because BibTeX has drifted: ``journal`` and ``journaltitle`` are the same
#: field, one from BibTeX and one from biblatex.
_FIELDS: dict[str, str] = {
    "title": "title",
    "author": "authors",
    "editor": "editors",
    "year": "year",
    "date": "year",
    "publisher": "publisher",
    "journal": "journal",
    "journaltitle": "journal",
    "booktitle": "journal",
    "series": "series",
    "volume": "volume",
    "number": "issue",
    "issue": "issue",
    "pages": "pages",
    "edition": "edition",
    "address": "place",
    "location": "place",
    "school": "institution",
    "institution": "institution",
    "organization": "institution",
    "language": "language",
    "doi": "doi",
    "isbn": "isbn",
    "url": "url",
    "urldate": "accessed_on",
    "abstract": "abstract",
    "note": "notes",
    "annote": "notes",
    "keywords": "keywords",
}

#: The commonest TeX escapes in a bibliography of European archaeology. Not a
#: full TeX engine — that is a different project — but enough that a German or
#: French bibliography does not import full of backslashes.
_ACCENTS = [
    (
        re.compile(r'\\"\{?([aouAOUeiy])\}?'),
        {"a": "ä", "o": "ö", "u": "ü", "A": "Ä", "O": "Ö", "U": "Ü", "e": "ë", "i": "ï", "y": "ÿ"},
    ),
    (
        re.compile(r"\\'\{?([aeiouyAEIOUYcnsz])\}?"),
        {
            "a": "á",
            "e": "é",
            "i": "í",
            "o": "ó",
            "u": "ú",
            "y": "ý",
            "A": "Á",
            "E": "É",
            "I": "Í",
            "O": "Ó",
            "U": "Ú",
            "Y": "Ý",
            "c": "ć",
            "n": "ń",
            "s": "ś",
            "z": "ź",
        },
    ),
    (
        re.compile(r"\\`\{?([aeiouAEIOU])\}?"),
        {
            "a": "à",
            "e": "è",
            "i": "ì",
            "o": "ò",
            "u": "ù",
            "A": "À",
            "E": "È",
            "I": "Ì",
            "O": "Ò",
            "U": "Ù",
        },
    ),
    (
        re.compile(r"\\\^\{?([aeiouAEIOU])\}?"),
        {
            "a": "â",
            "e": "ê",
            "i": "î",
            "o": "ô",
            "u": "û",
            "A": "Â",
            "E": "Ê",
            "I": "Î",
            "O": "Ô",
            "U": "Û",
        },
    ),
    (
        re.compile(r"\\~\{?([anoANO])\}?"),
        {"a": "ã", "n": "ñ", "o": "õ", "A": "Ã", "N": "Ñ", "O": "Õ"},
    ),
    (re.compile(r"\\c\{?([cC])\}?"), {"c": "ç", "C": "Ç"}),
]

_SIMPLE = {
    r"\ss": "ß",
    r"\ae": "æ",
    r"\AE": "Æ",
    r"\oe": "œ",
    r"\o": "ø",
    r"\O": "Ø",
    r"\aa": "å",
    r"\AA": "Å",
    r"\&": "&",
    r"\%": "%",
    r"\_": "_",
    r"\#": "#",
    r"--": "\u2013",
}


class BibtexError(ValueError):
    """The file could not be read. The message is safe to show a user."""


@dataclass(slots=True)
class Entry:
    """One parsed entry, in this platform's own terms."""

    citation_key: str
    reference_type: ReferenceType
    fields: dict[str, object] = field(default_factory=dict)
    #: Anything understood but not stored — kept so the import screen can say
    #: what it is dropping rather than dropping it silently.
    ignored: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------
def _clean(value: str) -> str:
    """TeX to text, keeping what braces were protecting."""
    text = value.strip()

    for pattern, table in _ACCENTS:
        text = pattern.sub(
            lambda match, table=table: table.get(match.group(1), match.group(1)), text
        )
    for source, target in _SIMPLE.items():
        text = text.replace(source, target)

    # Braces are dropped only *after* the accents above have consumed the ones
    # that belonged to them. What is left protected capitalisation — "{DNA}",
    # "{Tell el-Demo}" — and the letters inside it are what we want; the braces
    # themselves would be noise in a citation.
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _read_braced(source: str, start: int) -> tuple[str, int]:
    """The contents of a ``{...}`` beginning at ``start``, and where it ended.

    Counts depth rather than searching for the next ``}``, because
    ``{A study of {Nabataean} pottery}`` is one field and a search finds the
    wrong end of it.
    """
    depth = 0
    for index in range(start, len(source)):
        character = source[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1 : index], index + 1
    raise BibtexError("An entry ends without its closing brace — the file is truncated.")


def _read_value(source: str, start: int) -> tuple[str, int]:
    """One field value: braced, quoted, or bare."""
    index = start
    while index < len(source) and source[index] in " \t\r\n":
        index += 1
    if index >= len(source):
        raise BibtexError("A field ends without a value.")

    if source[index] == "{":
        return _read_braced(source, index)

    if source[index] == '"':
        end = index + 1
        depth = 0
        while end < len(source):
            if source[end] == "{":
                depth += 1
            elif source[end] == "}":
                depth -= 1
            elif source[end] == '"' and depth == 0 and source[end - 1] != "\\":
                return source[index + 1 : end], end + 1
            end += 1
        raise BibtexError("A quoted value is never closed.")

    # Bare: a number, or a @string name. Runs to the next comma or closing
    # brace at depth zero.
    end = index
    while end < len(source) and source[end] not in ",}\n":
        end += 1
    return source[index:end], end


def _to_year(value: str) -> int | None:
    """The first four-digit year in the field.

    biblatex writes dates as "2019-05-01" and older files write "in press" or
    "n.d."; taking the first plausible year and otherwise nothing is better than
    refusing the entry over a field nobody sorts by.
    """
    match = re.search(r"\b(1\d{3}|20\d{2}|21\d{2})\b", value)
    return int(match.group(1)) if match else None


def parse(source: str) -> list[Entry]:
    """Every entry in a ``.bib`` file.

    Never raises on an entry it cannot understand — only on a file it cannot
    scan at all. An unreadable entry three thousand lines in must not cost
    somebody the other two thousand nine hundred.
    """
    entries: list[Entry] = []
    position = 0

    while True:
        at = source.find("@", position)
        if at == -1:
            break

        brace = source.find("{", at)
        paren = source.find("(", at)
        # Rare, but legal: @article( ... ). Treated as unsupported rather than
        # mis-parsed, and skipped.
        if brace == -1:
            break
        if paren != -1 and paren < brace:
            position = at + 1
            continue

        kind = source[at + 1 : brace].strip().lower()
        if kind in ("comment", "string", "preamble"):
            try:
                _, position = _read_braced(source, brace)
            except BibtexError:
                break
            continue

        try:
            body, position = _read_braced(source, brace)
        except BibtexError:
            # A truncated final entry. Everything before it still imports.
            break

        entry = _parse_entry(kind, body)
        if entry is not None:
            entries.append(entry)

    return entries


def _parse_entry(kind: str, body: str) -> Entry | None:
    comma = body.find(",")
    if comma == -1:
        # A key and no fields. Nothing to file.
        return None

    key = body[:comma].strip()
    entry = Entry(citation_key=key, reference_type=_TYPES.get(kind, ReferenceType.OTHER))

    position = comma + 1
    while position < len(body):
        equals = body.find("=", position)
        if equals == -1:
            break

        name = body[position:equals].strip().strip(",").lower()
        try:
            raw, position = _read_value(body, equals + 1)
        except BibtexError:
            break

        # Past the value to the comma that separates fields.
        while position < len(body) and body[position] in " \t\r\n":
            position += 1
        if position < len(body) and body[position] == ",":
            position += 1

        if not name:
            continue

        column = _FIELDS.get(name)
        value = _clean(raw)
        if not value:
            continue

        if column is None:
            entry.ignored.append(name)
            continue

        if column == "year":
            year = _to_year(value)
            if year is not None:
                entry.fields["year"] = year
        elif column == "keywords":
            entry.fields["keywords"] = [
                part.strip() for part in re.split(r"[;,]", value) if part.strip()
            ]
        elif column == "accessed_on":
            match = re.search(r"(\d{4})-(\d{2})-(\d{2})", value)
            if match:
                entry.fields["accessed_on"] = match.group(0)
        else:
            entry.fields[column] = value

    if not entry.fields.get("title"):
        # A reference with no title cannot be found again by a person, and a
        # library full of untitled rows is what makes people stop using one.
        return None
    return entry


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------
_NEEDS_ESCAPE = {"&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_", "$": r"\$"}


def _escape(value: str) -> str:
    return "".join(_NEEDS_ESCAPE.get(character, character) for character in value)


def key_for(reference: object, taken: set[str]) -> str:
    """A citation key: surname, year, and a letter if that is taken.

    Uses the stored key when there is one, so a reference imported from a .bib
    exports under the key somebody's LaTeX already cites.
    """
    existing = getattr(reference, "citation_key", None)
    if existing and existing not in taken:
        taken.add(existing)
        return existing

    authors = (getattr(reference, "authors", None) or "").strip()
    surname = re.split(r"[,;&]| and ", authors)[0].strip() if authors else ""
    surname = surname.split()[-1] if surname else "anon"
    surname = re.sub(r"[^A-Za-z]", "", surname).lower() or "anon"

    year = getattr(reference, "year", None) or "nd"
    stem = f"{surname}{year}"

    candidate = stem
    suffix = ord("a")
    while candidate in taken:
        candidate = f"{stem}{chr(suffix)}"
        suffix += 1
    taken.add(candidate)
    return candidate


def write(references: list[object]) -> str:
    """A ``.bib`` file holding every reference given."""
    taken: set[str] = set()
    out: list[str] = [
        "% Exported from Stratum.",
        "% Braces around a title protect its capitalisation; leave them in place.",
        "",
    ]

    for reference in references:
        kind = _OUT.get(getattr(reference, "reference_type", None) or ReferenceType.OTHER, "misc")
        key = key_for(reference, taken)
        lines = [f"@{kind}{{{key},"]

        def add(name: str, value: object, lines: list[str] = lines) -> None:
            # `lines` bound as a default rather than captured: the closure is
            # redefined per reference, and a captured name would be re-read
            # each call — correct here by accident, and the kind of accident
            # that stops being correct the moment this loop is refactored.
            if value in (None, "", []):
                return
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            lines.append(f"  {name} = {{{_escape(str(value))}}},")

        # Title first and braced twice: the outer braces are BibTeX's, the inner
        # pair is what stops a style lower-casing "Tell el-Demo" to "Tell
        # el-demo" in every citation that uses it.
        title = getattr(reference, "title", None)
        if title:
            lines.append(f"  title = {{{{{_escape(str(title))}}}}},")

        add("author", getattr(reference, "authors", None))
        add("editor", getattr(reference, "editors", None))
        add("year", getattr(reference, "year", None))
        add("journal", getattr(reference, "journal", None))
        add("series", getattr(reference, "series", None))
        add("volume", getattr(reference, "volume", None))
        add("number", getattr(reference, "issue", None))
        add("pages", getattr(reference, "pages", None))
        add("edition", getattr(reference, "edition", None))
        add("publisher", getattr(reference, "publisher", None))
        add("address", getattr(reference, "place", None))
        add("institution", getattr(reference, "institution", None))
        add("language", getattr(reference, "language", None))
        add("doi", getattr(reference, "doi", None))
        add("isbn", getattr(reference, "isbn", None))
        add("url", getattr(reference, "url", None))
        accessed = getattr(reference, "accessed_on", None)
        if accessed:
            add("urldate", accessed.isoformat() if hasattr(accessed, "isoformat") else accessed)
        add("abstract", getattr(reference, "abstract", None))
        add("keywords", getattr(reference, "keywords", None))
        add("note", getattr(reference, "notes", None))

        # The trailing comma on the last field is legal and means one less thing
        # to get wrong when a line is added by hand later.
        lines.append("}")
        out.append("\n".join(lines))
        out.append("")

    return "\n".join(out)


# --------------------------------------------------------------------------
# A citation to read
# --------------------------------------------------------------------------
def cite(reference: object) -> str:
    """One line, for a list on screen.

    Deliberately not a citation style. Implementing Harvard or Chicago properly
    means implementing all of CSL, and implementing one of them badly produces
    something that looks like a citation and is wrong — which is worse than
    something that plainly is not one. This is a label: author, year, title,
    where.
    """
    stored = getattr(reference, "citation", None)
    if stored:
        return str(stored).strip()

    bits: list[str] = []
    authors = getattr(reference, "authors", None)
    year = getattr(reference, "year", None)

    if authors and year:
        bits.append(f"{authors} ({year}).")
    elif authors:
        bits.append(f"{authors}.")
    elif year:
        bits.append(f"({year}).")

    title = getattr(reference, "title", None)
    if title:
        bits.append(f"{str(title).rstrip('.')}.")

    where: list[str] = []
    journal = getattr(reference, "journal", None)
    if journal:
        volume = getattr(reference, "volume", None)
        issue = getattr(reference, "issue", None)
        piece = str(journal)
        if volume:
            piece += f" {volume}"
            if issue:
                piece += f"({issue})"
        where.append(piece)
    pages = getattr(reference, "pages", None)
    if pages:
        where.append(str(pages))

    publisher = getattr(reference, "publisher", None)
    place = getattr(reference, "place", None)
    if publisher:
        where.append(f"{place}: {publisher}" if place else str(publisher))

    if where:
        bits.append(", ".join(where) + ".")

    return " ".join(bits).strip() or str(title or "Untitled")
