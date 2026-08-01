"""Image handling: validation, EXIF extraction and thumbnails.

An uploaded image is hostile input. Nothing here trusts the declared content
type or the extension — the file is opened and decoded, and if Pillow cannot
make an image of it, it is not an image regardless of what it claims to be.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, BinaryIO

from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError

from app.core.config import settings

logger = logging.getLogger("archeo.images")

#: Formats accepted on upload. Deliberately short: these cover every camera and
#: phone a field team will use, and each is a format Pillow decodes safely.
#: SVG is absent on purpose — it is a document that can carry script, not a
#: raster image, and serving one back opens a cross-site scripting hole.
ALLOWED_FORMATS: dict[str, str] = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "TIFF": ".tif",
    "GIF": ".gif",
    "BMP": ".bmp",
}

MIME_TYPES: dict[str, str] = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "TIFF": "image/tiff",
    "GIF": "image/gif",
    "BMP": "image/bmp",
}

#: A decompression bomb is a small file that expands to something enormous.
#: Pillow warns above ~89 megapixels by default; this makes it a refusal, at a
#: size no archaeological photograph legitimately reaches.
MAX_PIXELS = 120_000_000

#: EXIF tags worth keeping. The full block is stored verbatim as well, but
#: these are the ones the interface reads.
_INTERESTING_TAGS = {
    "Make",
    "Model",
    "LensModel",
    "DateTime",
    "DateTimeOriginal",
    "DateTimeDigitized",
    "ExposureTime",
    "FNumber",
    "ISOSpeedRatings",
    "FocalLength",
    "Orientation",
    "Software",
    "Artist",
    "Copyright",
    "ImageDescription",
}


class ImageError(ValueError):
    """The upload is not a usable image. The message is safe to show a user."""


@dataclass
class ImageFacts:
    """What could be learned from an uploaded image."""

    format: str
    mime_type: str
    extension: str
    width: int
    height: int
    exif: dict[str, Any] = field(default_factory=dict)
    taken_at: datetime | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    lens: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    direction: float | None = None


def _rational(value: Any) -> float | None:
    """EXIF numbers arrive as rationals, tuples, or occasionally nonsense."""
    try:
        if isinstance(value, tuple) and len(value) == 2:
            return float(value[0]) / float(value[1]) if value[1] else None
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _degrees(dms: Any, reference: Any) -> float | None:
    """Convert EXIF degrees/minutes/seconds into a signed decimal degree."""
    try:
        degrees, minutes, seconds = (_rational(part) for part in dms)
    except (TypeError, ValueError):
        return None
    if degrees is None or minutes is None or seconds is None:
        return None

    value = degrees + minutes / 60 + seconds / 3600
    if str(reference).upper().startswith(("S", "W")):
        value = -value
    return value if -180 <= value <= 180 else None


def _reference_flag(value: Any) -> int | None:
    """Normalise an EXIF reference byte to an integer.

    ``GPSAltitudeRef`` is a BYTE tag, so decoders hand it back as ``b"\\x01"``,
    ``1`` or ``"1"`` depending on the camera and the library version. Comparing
    the raw value against ``1`` silently fails for the bytes form, which would
    turn every below-datum reading into a positive one.
    """
    if isinstance(value, bytes):
        return value[0] if value else None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _parse_timestamp(raw: Any) -> datetime | None:
    """EXIF timestamps look like ``2024:05:04 09:13:22``."""
    if not isinstance(raw, str):
        return None
    for pattern in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw.strip(), pattern)
        except ValueError:
            continue
    return None


def _jsonable(value: Any) -> Any:
    """EXIF holds bytes, rationals and tuples; JSONB does not."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[:500]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value][:50]
    return str(value)[:500]


def extract_exif(image: Image.Image) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(readable_exif, gps)``.

    Failure here is never fatal: a photograph with unreadable metadata is still
    a photograph, and cameras produce malformed EXIF often enough that refusing
    the upload would be the wrong call.
    """
    readable: dict[str, Any] = {}
    gps: dict[str, Any] = {}

    try:
        raw = image.getexif()
    except Exception:  # pragma: no cover - depends on the decoder
        return readable, gps
    if not raw:
        return readable, gps

    for tag_id, value in raw.items():
        name = ExifTags.TAGS.get(tag_id, str(tag_id))
        if name in _INTERESTING_TAGS:
            readable[name] = _jsonable(value)

    try:
        gps_block = raw.get_ifd(ExifTags.IFD.GPSInfo)
    except Exception:  # pragma: no cover - depends on the decoder
        gps_block = None

    if gps_block:
        for tag_id, value in gps_block.items():
            gps[ExifTags.GPSTAGS.get(tag_id, str(tag_id))] = value

    # The Exif sub-IFD carries the timestamps most cameras actually set.
    try:
        exif_block = raw.get_ifd(ExifTags.IFD.Exif)
        for tag_id, value in (exif_block or {}).items():
            name = ExifTags.TAGS.get(tag_id, str(tag_id))
            if name in _INTERESTING_TAGS:
                readable.setdefault(name, _jsonable(value))
    except Exception:  # pragma: no cover - depends on the decoder
        pass

    return readable, gps


def inspect(data: bytes) -> ImageFacts:
    """Validate an upload and pull out everything useful.

    Raises :class:`ImageError` if the bytes are not a supported image.
    """
    if not data:
        raise ImageError("The uploaded file is empty")

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS

    try:
        # verify() is destructive, so the image is opened twice: once to check
        # the file is structurally sound, once to actually read it.
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()

        with Image.open(io.BytesIO(data)) as image:
            image_format = (image.format or "").upper()
            if image_format not in ALLOWED_FORMATS:
                raise ImageError(
                    f"{image_format or 'That file'} is not a supported image format. "
                    f"Use one of: {', '.join(sorted(ALLOWED_FORMATS))}."
                )

            width, height = image.size
            if width * height > MAX_PIXELS:
                raise ImageError("That image is implausibly large and was not accepted")

            exif, gps = extract_exif(image)
    except ImageError:
        raise
    except UnidentifiedImageError as exc:
        raise ImageError("That file is not an image, or the image is corrupt") from exc
    except Image.DecompressionBombError as exc:
        raise ImageError("That image is implausibly large and was not accepted") from exc
    except Exception as exc:  # pragma: no cover - malformed input is varied
        raise ImageError(f"The image could not be read: {type(exc).__name__}") from exc

    facts = ImageFacts(
        format=image_format,
        mime_type=MIME_TYPES[image_format],
        extension=ALLOWED_FORMATS[image_format],
        width=width,
        height=height,
        exif=exif,
    )

    facts.camera_make = (exif.get("Make") or None) and str(exif["Make"]).strip()[:120]
    facts.camera_model = (exif.get("Model") or None) and str(exif["Model"]).strip()[:120]
    facts.lens = (exif.get("LensModel") or None) and str(exif["LensModel"]).strip()[:150]
    facts.taken_at = _parse_timestamp(
        exif.get("DateTimeOriginal") or exif.get("DateTimeDigitized") or exif.get("DateTime")
    )

    if gps:
        facts.latitude = _degrees(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"))
        facts.longitude = _degrees(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"))
        if facts.latitude is not None and not -90 <= facts.latitude <= 90:
            facts.latitude = facts.longitude = None
        altitude = _rational(gps.get("GPSAltitude"))
        if altitude is not None:
            # Reference 1 means below sea level.
            below = _reference_flag(gps.get("GPSAltitudeRef")) == 1
            facts.altitude = -altitude if below else altitude
        facts.direction = _rational(gps.get("GPSImgDirection"))

    return facts


def make_thumbnail(data: bytes, size: int) -> bytes:
    """Render a JPEG thumbnail whose longest edge is ``size`` pixels.

    Three things this does that a naive resize does not: it honours the EXIF
    orientation tag, so portrait photographs are not served on their side; it
    flattens transparency onto white rather than producing a JPEG with a black
    background; and it strips metadata, so a thumbnail cannot leak the GPS
    position of a site whose location is restricted.
    """
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS

    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image) or image

        if image.mode in ("RGBA", "LA", "P"):
            image = image.convert("RGBA")
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")

        image.thumbnail((size, size), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85, optimize=True, progressive=True)
        return buffer.getvalue()


def thumbnail_sizes() -> list[int]:
    return sorted(set(settings.THUMBNAIL_SIZES))


def read_upload(stream: BinaryIO, *, max_bytes: int) -> bytes:
    """Read an upload, refusing anything over the limit.

    Reads one chunk beyond the limit rather than trusting a declared
    ``Content-Length``, which a client controls.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := stream.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise ImageError(f"That file is larger than the {max_bytes // (1024 * 1024)} MB limit")
        chunks.append(chunk)
    return b"".join(chunks)
