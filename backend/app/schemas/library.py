"""The library, as the API speaks it."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, computed_field

from app.models.enums import ReferenceType
from app.schemas.common import ORMModel


class CollectionBase(BaseModel):
    name: str = Field(max_length=200)
    description: str | None = None
    parent_id: uuid.UUID | None = None
    is_public: bool = False


class CollectionCreate(CollectionBase):
    pass


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    parent_id: uuid.UUID | None = None
    is_public: bool | None = None


class CollectionRead(ORMModel, CollectionBase):
    id: uuid.UUID
    created_at: datetime
    #: How many references are filed here. Not counting children: a folder that
    #: claims forty and shows none because they are all in sub-folders is a
    #: folder somebody thinks is broken.
    reference_count: int = 0


class ReferenceBase(BaseModel):
    reference_type: ReferenceType = ReferenceType.ARTICLE
    title: str = Field(max_length=500)
    authors: str | None = Field(default=None, max_length=500)
    editors: str | None = Field(default=None, max_length=500)
    year: int | None = Field(default=None, ge=-3000, le=2200)
    publisher: str | None = Field(default=None, max_length=300)
    journal: str | None = Field(default=None, max_length=300)
    series: str | None = Field(default=None, max_length=300)
    volume: str | None = Field(default=None, max_length=50)
    issue: str | None = Field(default=None, max_length=50)
    pages: str | None = Field(default=None, max_length=50)
    edition: str | None = Field(default=None, max_length=50)
    place: str | None = Field(default=None, max_length=200)
    institution: str | None = Field(default=None, max_length=300)
    language: str | None = Field(default=None, max_length=80)
    doi: str | None = Field(default=None, max_length=200)
    isbn: str | None = Field(default=None, max_length=20)
    url: str | None = Field(default=None, max_length=1000)
    accessed_on: date | None = None
    abstract: str | None = None
    notes: str | None = None
    citation: str | None = None
    keywords: list[str] | None = None
    citation_key: str | None = Field(default=None, max_length=120)
    is_public: bool = False


class ReferenceCreate(ReferenceBase):
    #: Filed into these folders on creation, so adding a reference from inside a
    #: folder does not need a second call that might not happen.
    collection_ids: list[uuid.UUID] = Field(default_factory=list)


class ReferenceUpdate(BaseModel):
    reference_type: ReferenceType | None = None
    title: str | None = Field(default=None, max_length=500)
    authors: str | None = Field(default=None, max_length=500)
    editors: str | None = Field(default=None, max_length=500)
    year: int | None = Field(default=None, ge=-3000, le=2200)
    publisher: str | None = Field(default=None, max_length=300)
    journal: str | None = Field(default=None, max_length=300)
    series: str | None = Field(default=None, max_length=300)
    volume: str | None = Field(default=None, max_length=50)
    issue: str | None = Field(default=None, max_length=50)
    pages: str | None = Field(default=None, max_length=50)
    edition: str | None = Field(default=None, max_length=50)
    place: str | None = Field(default=None, max_length=200)
    institution: str | None = Field(default=None, max_length=300)
    language: str | None = Field(default=None, max_length=80)
    doi: str | None = Field(default=None, max_length=200)
    isbn: str | None = Field(default=None, max_length=20)
    url: str | None = Field(default=None, max_length=1000)
    accessed_on: date | None = None
    abstract: str | None = None
    notes: str | None = None
    citation: str | None = None
    keywords: list[str] | None = None
    citation_key: str | None = Field(default=None, max_length=120)
    is_public: bool | None = None
    collection_ids: list[uuid.UUID] | None = None


class ReferenceRead(ORMModel, ReferenceBase):
    id: uuid.UUID
    owner_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    #: Which folders it is filed in. Several, deliberately.
    collection_ids: list[uuid.UUID] = Field(default_factory=list)
    #: How many records it has been attached to, so a list can show which
    #: references are doing work and which are only filed.
    link_count: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def label(self) -> str:
        """One line, for a list on screen.

        Not a citation style: implementing Harvard properly means implementing
        all of CSL, and implementing it badly produces something that looks like
        a citation and is wrong — worse than something that plainly is not one.
        """
        from app.services import bibtex

        return bibtex.cite(self)


class LinkBase(BaseModel):
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    context_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    museum_object_id: uuid.UUID | None = None
    locator: str | None = Field(
        default=None,
        max_length=120,
        description='Where in it: "88-91", "fig. 14", "pl. IIIa"',
    )
    note: str | None = None


class LinkCreate(LinkBase):
    pass


class LinkRead(ORMModel, LinkBase):
    id: uuid.UUID
    publication_id: uuid.UUID
    created_at: datetime

    #: Resolved for display, so a list of what a reference is about does not
    #: need one request per row.
    target_kind: str | None = None
    target_label: str | None = None
    #: The reference itself, when the link is being read from the record's side.
    reference: ReferenceRead | None = None


class ImportPreview(BaseModel):
    """What a .bib file would do, before it does it."""

    parsed: int
    #: Matched to something already in the library, by DOI or by citation key.
    duplicates: int
    new: int
    entries: list[ReferenceBase] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)


class ImportResult(BaseModel):
    created: int
    skipped: int
    detail: str
