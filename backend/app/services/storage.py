"""File storage.

Files live on local disk today. Everything above this module speaks in
*relative* paths — ``photographs/ab/cd/<digest>.jpg`` — and never touches the
filesystem itself, so replacing this with S3 or GCS later means implementing
one class, not editing every endpoint.

Two decisions worth knowing:

**Content-addressed paths.** A stored file is named after the SHA-256 of its
bytes, not after whatever the client called it. Uploading the same photograph
twice costs one copy, and a filename can never influence where something lands
— which is the usual way file uploads turn into arbitrary writes.

**The original filename is metadata, not a path.** It is kept on the record for
display and used when the file is downloaded again, but it is not used to build
a path, so ``../../etc/passwd`` is just an odd-looking caption.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.core.config import settings

#: Sub-directory per kind of file, so the tree stays navigable by a human and a
#: bucket policy can differ per category later.
CATEGORY_PHOTOGRAPHS = "photographs"
CATEGORY_THUMBNAILS = "thumbnails"
CATEGORY_DOCUMENTS = "documents"
CATEGORY_MODELS = "models"
CATEGORY_QR = "qr"

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class StorageError(Exception):
    """Raised when a file cannot be stored or retrieved."""


@dataclass(frozen=True)
class StoredFile:
    """The result of storing bytes: where it went and what it was."""

    path: str
    checksum: str
    size: int
    #: True when the identical bytes were already stored, so nothing was written.
    deduplicated: bool = False


def safe_filename(name: str | None, fallback: str = "upload") -> str:
    """Reduce a client-supplied filename to something safe to echo back.

    Used for the ``Content-Disposition`` of a download and for display. Never
    used to build a storage path.
    """
    if not name:
        return fallback

    # Take the last component: browsers on some platforms send a full path.
    name = name.replace("\\", "/").split("/")[-1]
    # Normalise so visually identical Unicode cannot produce different names.
    name = unicodedata.normalize("NFKD", name)
    name = _UNSAFE_FILENAME.sub("_", name).strip("._")
    return name[:200] or fallback


def extension_of(name: str | None, default: str = "") -> str:
    """Lower-cased extension of a filename, dot included, or ``default``."""
    cleaned = safe_filename(name, "")
    if "." not in cleaned:
        return default
    suffix = "." + cleaned.rsplit(".", 1)[1].lower()
    # Guard against a pathological "file.<400 characters>".
    return suffix if len(suffix) <= 12 else default


class LocalStorage:
    """Stores files beneath ``settings.STORAGE_ROOT``."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or settings.STORAGE_ROOT)

    # -- paths ------------------------------------------------------------
    def _absolute(self, relative: str) -> Path:
        """Resolve a relative path, refusing anything that escapes the root.

        The paths this module generates are always safe; this check exists for
        paths read back from the database, which a future import tool or a
        careless migration could have populated with anything.
        """
        root = self.root.resolve()
        candidate = (root / relative).resolve()
        if candidate != root and root not in candidate.parents:
            raise StorageError(f"Refusing to access a path outside storage: {relative!r}")
        return candidate

    @staticmethod
    def _shard(digest: str, category: str, extension: str) -> str:
        """``photographs/ab/cd/<digest>.jpg``.

        Two levels of 256 keep any one directory small enough that listing it
        stays fast, which matters once a project has a hundred thousand photos.
        """
        return f"{category}/{digest[:2]}/{digest[2:4]}/{digest}{extension}"

    # -- writing ----------------------------------------------------------
    def save(self, source: BinaryIO, *, category: str, extension: str = "") -> StoredFile:
        """Store a stream, returning where it went.

        The stream is read once into a temporary file while the digest is
        computed, then moved into place — so a file too large for memory is
        never held in memory, and a failure part-way through leaves no
        half-written file at the final path.
        """
        temporary = self.root / ".incoming"
        temporary.mkdir(parents=True, exist_ok=True)

        digest = hashlib.sha256()
        size = 0
        scratch = temporary / f"{hashlib.sha256(str(id(source)).encode()).hexdigest()[:16]}.part"

        try:
            with scratch.open("wb") as handle:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                    handle.write(chunk)

            checksum = digest.hexdigest()
            relative = self._shard(checksum, category, extension)
            destination = self._absolute(relative)

            if destination.exists():
                # Identical bytes already stored: keep the existing copy.
                scratch.unlink(missing_ok=True)
                return StoredFile(path=relative, checksum=checksum, size=size, deduplicated=True)

            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(scratch), str(destination))
            return StoredFile(path=relative, checksum=checksum, size=size)
        finally:
            scratch.unlink(missing_ok=True)

    def save_bytes(self, data: bytes, *, category: str, extension: str = "") -> StoredFile:
        """Store an in-memory payload — thumbnails and QR codes."""
        import io

        return self.save(io.BytesIO(data), category=category, extension=extension)

    # -- reading ----------------------------------------------------------
    def open(self, relative: str) -> BinaryIO:
        path = self._absolute(relative)
        if not path.is_file():
            raise StorageError(f"Stored file is missing: {relative!r}")
        return path.open("rb")

    def absolute_path(self, relative: str) -> Path:
        """Full path, for handing to a response that streams from disk."""
        path = self._absolute(relative)
        if not path.is_file():
            raise StorageError(f"Stored file is missing: {relative!r}")
        return path

    def exists(self, relative: str) -> bool:
        try:
            return self._absolute(relative).is_file()
        except StorageError:
            return False

    def size(self, relative: str) -> int:
        return self._absolute(relative).stat().st_size

    # -- deleting ---------------------------------------------------------
    def delete(self, relative: str, *, shared: bool = True) -> bool:
        """Remove a stored file.

        ``shared=True`` — the default — means "another record may reference
        these same bytes", which is possible precisely because storage is
        content-addressed. Deleting a photograph therefore does *not* remove
        the file; it only unlinks the record. A separate sweep can collect
        files nothing refers to any more, which is the only safe time to
        delete them.
        """
        if shared:
            return False
        try:
            path = self._absolute(relative)
        except StorageError:
            return False
        if path.is_file():
            path.unlink()
            return True
        return False


#: The single instance the application uses. Swapping in a different backend is
#: a matter of rebinding this name.
storage = LocalStorage()
