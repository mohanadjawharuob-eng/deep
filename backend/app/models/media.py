"""Photographs, documents and 3D models.

All three share the same linking pattern: a nullable foreign key to each of
project / site / artifact / context. A photograph of an artifact belongs to
that artifact *and*, transitively, to its site and project, so the denormalised
links let the gallery for any level be one indexed query.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, OwnedRecordMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import DocumentType, MediaFolderKind, Model3DFormat, ReviewStatus

if TYPE_CHECKING:
    from app.models.user import User


class _AttachableMixin:
    """The optional parents every media record may hang from."""

    @property
    def parent_ids(self) -> dict[str, uuid.UUID | None]:
        return {
            "project_id": getattr(self, "project_id", None),
            "site_id": getattr(self, "site_id", None),
            "artifact_id": getattr(self, "artifact_id", None),
            "context_id": getattr(self, "context_id", None),
            "museum_object_id": getattr(self, "museum_object_id", None),
        }


class Photograph(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, _AttachableMixin, Base):
    __tablename__ = "photographs"

    title: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    photographer: Mapped[str | None] = mapped_column(String(200), index=True)
    photographer_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    camera_make: Mapped[str | None] = mapped_column(String(120))
    camera_model: Mapped[str | None] = mapped_column(String(120))
    lens: Mapped[str | None] = mapped_column(String(150))

    # --- Stored file -----------------------------------------------------
    #: Path relative to ``settings.STORAGE_ROOT``, never an absolute path, so
    #: the whole tree can be moved or swapped for object storage.
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(300))
    mime_type: Mapped[str | None] = mapped_column(String(120))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    #: SHA-256 of the bytes, used to detect duplicate uploads.
    checksum: Mapped[str | None] = mapped_column(String(64), index=True)
    width: Mapped[int | None] = mapped_column()
    height: Mapped[int | None] = mapped_column()
    #: ``{"200": "thumbs/200/ab/cd.jpg", "800": "..."}`` — one entry per
    #: configured thumbnail size.
    thumbnails: Mapped[dict | None] = mapped_column(JSONB)
    #: Full EXIF block as extracted on upload; kept verbatim for provenance.
    exif: Mapped[dict | None] = mapped_column(JSONB)

    # --- Where the photo was taken ---------------------------------------
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7))
    altitude: Mapped[float | None] = mapped_column(Numeric(8, 2))
    direction: Mapped[float | None] = mapped_column(Numeric(6, 2))  # compass bearing
    location_text: Mapped[str | None] = mapped_column(String(300))

    #: Field-photo conventions: overview, detail, working shot, section…
    shot_type: Mapped[str | None] = mapped_column(String(80), index=True)
    #: Marks the representative image of the parent record. Kept here rather
    #: than as a ``cover_image_id`` on projects, sites and artifacts: those
    #: would each form a foreign-key cycle with this table, and the link is
    #: already expressed by the parent columns below.
    is_cover: Mapped[bool] = mapped_column(default=False, nullable=False)
    #: Whether a scale bar / north arrow is visible — matters for publication.
    has_scale: Mapped[bool | None] = mapped_column()
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String(80)))

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    context_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("excavation_contexts.id", ondelete="CASCADE"), index=True
    )
    #: A museum object. Added late, and its absence was a real hole: the museum
    #: half of the platform could not hold a photograph at all, because every
    #: media record hung from an excavation record and an accessioned object is
    #: not one. An object that came out of a trench still has its find, and the
    #: two sets of pictures are different things - the find as excavated, the
    #: object as catalogued.
    museum_object_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("museum_objects.id", ondelete="CASCADE"), index=True
    )

    #: Which folder somebody filed this in, if any. Nullable and deliberately
    #: singular: a photograph in three folders is a photograph nobody can file,
    #: because "where is it" stops having an answer. `SET NULL`, because
    #: deleting a drawer must not delete what was in it.
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("folders.id", ondelete="SET NULL"), index=True
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status", values_callable=lambda e: [m.value for m in e]),
        default=ReviewStatus.APPROVED,
        nullable=False,
        index=True,
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    photographer_user: Mapped[User | None] = relationship(foreign_keys=[photographer_id])

    __table_args__ = (
        Index("ix_photographs_links", "project_id", "site_id", "artifact_id"),
        # Cover lookups are frequent (every card in every listing) and match
        # only a handful of rows, so index just those.
        Index(
            "ix_photographs_cover",
            "project_id",
            "site_id",
            "artifact_id",
            postgresql_where=text("is_cover"),
        ),
    )


class Document(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, _AttachableMixin, Base):
    """PDF, DOCX, spreadsheet or plain-text file attached to a record."""

    __tablename__ = "documents"

    title: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    document_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType, name="document_type", values_callable=lambda e: [m.value for m in e]),
        default=DocumentType.OTHER,
        nullable=False,
        index=True,
    )
    author: Mapped[str | None] = mapped_column(String(300), index=True)
    document_date: Mapped[date | None] = mapped_column(Date)
    language: Mapped[str | None] = mapped_column(String(10))

    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(300))
    mime_type: Mapped[str | None] = mapped_column(String(120))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    checksum: Mapped[str | None] = mapped_column(String(64), index=True)
    page_count: Mapped[int | None] = mapped_column()
    #: Text extracted for full-text search (OCR lands here in a later phase).
    extracted_text: Mapped[str | None] = mapped_column(Text)

    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String(80)))

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    context_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("excavation_contexts.id", ondelete="CASCADE"), index=True
    )
    #: A museum object. Added late, and its absence was a real hole: the museum
    #: half of the platform could not hold a photograph at all, because every
    #: media record hung from an excavation record and an accessioned object is
    #: not one. An object that came out of a trench still has its find, and the
    #: two sets of pictures are different things - the find as excavated, the
    #: object as catalogued.
    museum_object_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("museum_objects.id", ondelete="CASCADE"), index=True
    )
    publication_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("publications.id", ondelete="SET NULL"), index=True
    )
    researcher_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    #: Which folder somebody filed this in, if any. Nullable and deliberately
    #: singular: a photograph in three folders is a photograph nobody can file,
    #: because "where is it" stops having an answer. `SET NULL`, because
    #: deleting a drawer must not delete what was in it.
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("folders.id", ondelete="SET NULL"), index=True
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status", values_callable=lambda e: [m.value for m in e]),
        default=ReviewStatus.APPROVED,
        nullable=False,
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (Index("ix_documents_links", "project_id", "site_id", "artifact_id"),)


class Model3D(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, _AttachableMixin, Base):
    """A 3D model: either an uploaded mesh or a link to an external viewer.

    Photogrammetry output is far too large to hold in the platform, so a model
    is usually a *reference* — a Sketchfab embed, a RealityScan project, a
    Metashape archive on institutional storage — with an optional lightweight
    glTF for in-browser preview.
    """

    __tablename__ = "models_3d"

    title: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    format: Mapped[Model3DFormat] = mapped_column(
        Enum(Model3DFormat, name="model_3d_format", values_callable=lambda e: [m.value for m in e]),
        default=Model3DFormat.OTHER,
        nullable=False,
        index=True,
    )

    #: Locally stored mesh, when small enough to host.
    file_path: Mapped[str | None] = mapped_column(String(500))
    #: External URL (Sketchfab, institutional repository, object storage).
    external_url: Mapped[str | None] = mapped_column(String(1000))
    #: URL that can be put in an ``<iframe>``; null when not embeddable.
    embed_url: Mapped[str | None] = mapped_column(String(1000))
    preview_image_path: Mapped[str | None] = mapped_column(String(500))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    checksum: Mapped[str | None] = mapped_column(String(64))

    # --- Capture provenance ----------------------------------------------
    capture_method: Mapped[str | None] = mapped_column(String(120))  # photogrammetry, laser scan…
    software: Mapped[str | None] = mapped_column(String(150))
    capture_date: Mapped[date | None] = mapped_column(Date)
    vertex_count: Mapped[int | None] = mapped_column(BigInteger)
    face_count: Mapped[int | None] = mapped_column(BigInteger)
    #: Real-world size of one model unit, needed for measurement in the viewer.
    scale_note: Mapped[str | None] = mapped_column(String(200))
    license: Mapped[str | None] = mapped_column(String(120))

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    context_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("excavation_contexts.id", ondelete="CASCADE"), index=True
    )
    #: A museum object. Added late, and its absence was a real hole: the museum
    #: half of the platform could not hold a photograph at all, because every
    #: media record hung from an excavation record and an accessioned object is
    #: not one. An object that came out of a trench still has its find, and the
    #: two sets of pictures are different things - the find as excavated, the
    #: object as catalogued.
    museum_object_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("museum_objects.id", ondelete="CASCADE"), index=True
    )

    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (Index("ix_models_3d_links", "project_id", "site_id", "artifact_id"),)


class MediaFolder(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, _AttachableMixin, Base):
    """Files that exist, and are not in here.

    A season produces four hundred gigabytes of raw frames, a photogrammetry
    set per structure, and a drone survey. Uploading all of it is sometimes
    right and sometimes absurd — it is already on the project drive, backed up,
    and nobody is going to look at the RAWs through a web page.

    What is *not* optional is knowing the material exists and where it is. A
    catalogue that is silent about four hundred gigabytes is a catalogue that
    will be believed to be complete, and the drive will be reformatted by
    somebody who checked the archive first.

    So this records the folder rather than the files: what is in it, where it
    is, which disk that is, how many items were there when it was written down.

    **This is a note, not a link.** The platform cannot open it, cannot verify
    it, and cannot tell you when it stops being true. That is stated on the
    screen too, because a path rendered like a hyperlink is a promise, and this
    one cannot be kept.
    """

    __tablename__ = "media_folders"

    #: What this folder is, in the words of whoever keeps it: "Trench A
    #: season photographs", "Pottery drawings 2019".
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[MediaFolderKind] = mapped_column(
        Enum(
            MediaFolderKind,
            name="media_folder_kind",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=MediaFolderKind.PHOTOGRAPHS,
        nullable=False,
        index=True,
    )

    #: The folder exactly as written. Never parsed, never resolved, never
    #: opened: it may be a Windows path, a share, a mount point on somebody
    #: else's laptop, or a shelf reference for a box of DVDs.
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    #: Which disk that path is on — "external drive DIG-2019", "NAS, share
    #: `excavation`". The single most useful field here and the one most often
    #: left out: a path with no disk names a folder on a machine nobody can
    #: identify five years later.
    medium: Mapped[str | None] = mapped_column(String(300))

    #: How many files were there when this was recorded. Not maintained, and
    #: not meant to be: it is evidence about a moment, which is why
    #: ``recorded_on`` sits beside it.
    item_count: Mapped[int | None] = mapped_column()
    #: Approximate size, in gigabytes, for deciding whether it can ever be
    #: uploaded.
    size_gb: Mapped[float | None] = mapped_column(Numeric(10, 2))
    recorded_on: Mapped[date | None] = mapped_column(Date)

    #: Whether somebody has confirmed a copy exists somewhere else. Three
    #: states: yes, no, and nobody has said — and the third is the common one,
    #: so it must not be stored as "no".
    is_backed_up: Mapped[bool | None] = mapped_column()
    note: Mapped[str | None] = mapped_column(Text)

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    context_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("excavation_contexts.id", ondelete="CASCADE"), index=True
    )
    #: A museum object. Added late, and its absence was a real hole: the museum
    #: half of the platform could not hold a photograph at all, because every
    #: media record hung from an excavation record and an accessioned object is
    #: not one. An object that came out of a trench still has its find, and the
    #: two sets of pictures are different things - the find as excavated, the
    #: object as catalogued.
    museum_object_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("museum_objects.id", ondelete="CASCADE"), index=True
    )

    __table_args__ = (Index("ix_media_folders_links", "project_id", "site_id", "artifact_id"),)
