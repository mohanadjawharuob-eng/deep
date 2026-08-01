"""Document uploads.

Reports, permits, spreadsheets and field notes. Unlike images these are stored
as they arrive — the platform does not open a DOCX or execute a spreadsheet,
and should not pretend to understand them.

What it *does* do is refuse anything outside a known list, and refuse it on the
strength of the file's own leading bytes rather than its extension or the
content type the client claimed. Both of those are attacker-controlled.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import DocumentType

#: Extension → (mime type, human name). Everything else is refused.
#:
#: No archives and no HTML. A zip invites a decompression bomb and hides its
#: contents from any check; an HTML file served back from this origin would run
#: script as the platform, which is a cross-site scripting hole with extra
#: steps. PDFs and Office formats can of course carry macros, which is why they
#: are stored and served as downloads and never rendered inline.
ALLOWED_TYPES: dict[str, tuple[str, str]] = {
    ".pdf": ("application/pdf", "PDF"),
    ".doc": ("application/msword", "Word document"),
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "Word document",
    ),
    ".xls": ("application/vnd.ms-excel", "Excel spreadsheet"),
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Excel spreadsheet",
    ),
    ".csv": ("text/csv", "CSV file"),
    ".tsv": ("text/tab-separated-values", "TSV file"),
    ".txt": ("text/plain", "Text file"),
    ".md": ("text/markdown", "Markdown file"),
    ".rtf": ("application/rtf", "Rich text file"),
    ".json": ("application/json", "JSON file"),
    ".xml": ("application/xml", "XML file"),
    ".geojson": ("application/geo+json", "GeoJSON file"),
    ".odt": ("application/vnd.oasis.opendocument.text", "OpenDocument text"),
    ".ods": ("application/vnd.oasis.opendocument.spreadsheet", "OpenDocument spreadsheet"),
}

#: Leading bytes for the formats that have a reliable signature. Text-based
#: formats have none, and are checked differently below.
_MAGIC: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF-",),
    # Every OOXML and OpenDocument file is a zip container.
    ".docx": (b"PK\x03\x04",),
    ".xlsx": (b"PK\x03\x04",),
    ".odt": (b"PK\x03\x04",),
    ".ods": (b"PK\x03\x04",),
    # The old binary Office formats use the OLE compound file header.
    ".doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    ".xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    ".rtf": (b"{\\rtf",),
}

#: Formats with no signature, where "is it text?" is the only honest check.
_TEXTUAL = {".csv", ".tsv", ".txt", ".md", ".json", ".xml", ".geojson"}


class DocumentError(ValueError):
    """The upload is not an acceptable document; the message is user-facing."""


@dataclass(frozen=True)
class DocumentFacts:
    extension: str
    mime_type: str
    description: str
    size: int


def _looks_textual(data: bytes) -> bool:
    """Whether the leading bytes are plausibly text.

    A NUL byte in the first block means binary in practice; real text files do
    not contain one. Decoding is attempted as UTF-8 and then Latin-1, which
    between them cover what field recording software emits.
    """
    sample = data[:8192]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        pass
    try:
        sample.decode("latin-1")
        return True
    except UnicodeDecodeError:
        return False


def inspect(data: bytes, filename: str | None) -> DocumentFacts:
    """Validate an uploaded document by extension *and* content.

    Raises :class:`DocumentError` with a message safe to show the user.
    """
    if not data:
        raise DocumentError("The uploaded file is empty")

    from app.services.storage import extension_of

    extension = extension_of(filename)
    if not extension:
        raise DocumentError(
            "The file needs an extension so its type can be checked, e.g. report.pdf"
        )

    if extension not in ALLOWED_TYPES:
        raise DocumentError(
            f"{extension} files are not accepted. Allowed: {', '.join(sorted(ALLOWED_TYPES))}."
        )

    mime_type, description = ALLOWED_TYPES[extension]

    signatures = _MAGIC.get(extension)
    if signatures:
        if not any(data.startswith(signature) for signature in signatures):
            raise DocumentError(
                f"That file is named {extension} but its contents are not a "
                f"{description}. Check you uploaded the right file."
            )
    elif extension in _TEXTUAL and not _looks_textual(data):
        raise DocumentError(
            f"That file is named {extension} but does not contain text. "
            f"Check you uploaded the right file."
        )

    return DocumentFacts(
        extension=extension, mime_type=mime_type, description=description, size=len(data)
    )


#: Extension → the document type it most likely is, used to pre-fill the form.
_TYPE_HINTS: dict[str, DocumentType] = {
    ".csv": DocumentType.SPREADSHEET,
    ".tsv": DocumentType.SPREADSHEET,
    ".xls": DocumentType.SPREADSHEET,
    ".xlsx": DocumentType.SPREADSHEET,
    ".ods": DocumentType.SPREADSHEET,
}


def guess_type(extension: str, filename: str | None = None) -> DocumentType:
    """A sensible default document type, which the uploader can override."""
    name = (filename or "").lower()
    for keyword, document_type in (
        ("permit", DocumentType.PERMIT),
        ("report", DocumentType.REPORT),
        ("plan", DocumentType.PLAN),
        ("section", DocumentType.SECTION_DRAWING),
        ("notes", DocumentType.FIELD_NOTES),
        ("diary", DocumentType.FIELD_NOTES),
        ("letter", DocumentType.CORRESPONDENCE),
    ):
        if keyword in name:
            return document_type
    return _TYPE_HINTS.get(extension, DocumentType.OTHER)


def extract_text(data: bytes, extension: str, *, limit: int = 200_000) -> str | None:
    """Plain text from a document, for full-text search.

    Only textual formats are handled. PDF and Office extraction needs libraries
    this project does not carry yet, and OCR is a later milestone — those
    documents are stored and searchable by their title and description until
    then, which is honest about what the search can see.
    """
    if extension not in _TEXTUAL:
        return None
    try:
        text = data[:limit].decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data[:limit].decode("latin-1")
        except UnicodeDecodeError:
            return None
    return text.strip() or None
