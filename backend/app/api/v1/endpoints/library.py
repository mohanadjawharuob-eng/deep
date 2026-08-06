"""The library.

Shaped like the reference manager people already use — folders a reference can
be in several of at once, keywords, notes, BibTeX in and out — with the one
thing a reference manager cannot do: **a reference can be attached to the record
it is about**, at the pages it is about them.

"Smith 1987 is about this site" is a bibliography. "Smith 1987, 88-91, describes
context 1042" is a finding aid, and it is the sentence that never gets written
down because there has been nowhere to write it.

Permissions are the archaeology module's. A bibliography is not secret, and the
platform already has a module whose viewers are the people who would read one;
inventing a seventh module for it would mean every new account needing one more
grant before it could look anything up.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, or_, select

from app.api.deps import DbSession, require_module
from app.models.artifact import Artifact
from app.models.context import ExcavationContext
from app.models.enums import Module, ReferenceType, ResourceType
from app.models.enums import ModuleLevel as Level
from app.models.library import LibraryCollection, ReferenceLink
from app.models.museum import MuseumObject
from app.models.project import Project
from app.models.site import Site
from app.models.taxonomy import Publication
from app.models.user import User
from app.schemas.common import Message, Page
from app.schemas.library import (
    CollectionCreate,
    CollectionRead,
    CollectionUpdate,
    ImportPreview,
    ImportResult,
    LinkCreate,
    LinkRead,
    ReferenceBase,
    ReferenceCreate,
    ReferenceRead,
    ReferenceUpdate,
)
from app.services import bibtex, records

router = APIRouter(prefix="/library", tags=["Library"])

MODULE = Module.ARCHAEOLOGY
RESOURCE = ResourceType.PUBLICATION

Reader = Annotated[User, Depends(require_module(MODULE, Level.VIEWER))]
Writer = Annotated[User, Depends(require_module(MODULE, Level.CONTRIBUTOR))]

#: Which column on a link points at which record, and what to call it.
_TARGETS: list[tuple[str, type[Any], str, str]] = [
    ("museum_object_id", MuseumObject, "Object", "accession_number"),
    ("artifact_id", Artifact, "Find", "inventory_number"),
    ("context_id", ExcavationContext, "Context", "context_number"),
    ("site_id", Site, "Site", "name"),
    ("project_id", Project, "Project", "name"),
]


# --------------------------------------------------------------------------
# Shaping
# --------------------------------------------------------------------------
def _reference(session: DbSession, row: Publication) -> ReferenceRead:
    payload = ReferenceRead.model_validate(row)
    payload.collection_ids = [collection.id for collection in row.collections]
    payload.link_count = (
        session.scalar(
            select(func.count())
            .select_from(ReferenceLink)
            .where(ReferenceLink.publication_id == row.id)
        )
        or 0
    )
    return payload


def _link(session: DbSession, row: ReferenceLink, *, with_reference: bool = False) -> LinkRead:
    payload = LinkRead.model_validate(row)

    # Resolved here rather than by the client: a list of what a reference is
    # about should not cost one request per row.
    for column, model, kind, attribute in _TARGETS:
        identifier = getattr(row, column)
        if identifier is None:
            continue
        target = session.get(model, identifier)
        payload.target_kind = kind
        payload.target_label = getattr(target, attribute, None) if target else None
        break

    if with_reference and row.publication is not None:
        payload.reference = _reference(session, row.publication)
    return payload


def _apply_collections(session: DbSession, row: Publication, ids: list[uuid.UUID]) -> None:
    if not ids:
        row.collections = []
        return
    found = list(session.scalars(select(LibraryCollection).where(LibraryCollection.id.in_(ids))))
    missing = set(ids) - {collection.id for collection in found}
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No folder with id {next(iter(missing))}",
        )
    row.collections = found


# --------------------------------------------------------------------------
# Folders
# --------------------------------------------------------------------------
@router.get("/collections", response_model=list[CollectionRead], summary="The folders")
def list_collections(session: DbSession, user: Reader) -> list[CollectionRead]:
    rows = list(session.scalars(select(LibraryCollection).order_by(LibraryCollection.name)))

    counts = dict(
        session.execute(
            select(
                LibraryCollection.id,
                func.count(),
            )
            .select_from(LibraryCollection)
            .join(
                LibraryCollection.publications,  # type: ignore[attr-defined]
            )
            .group_by(LibraryCollection.id)
        ).all()
    )

    payload = []
    for row in rows:
        item = CollectionRead.model_validate(row)
        item.reference_count = counts.get(row.id, 0)
        payload.append(item)
    return payload


@router.post(
    "/collections",
    response_model=CollectionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Make a folder",
)
def create_collection(
    payload: CollectionCreate, session: DbSession, user: Writer
) -> CollectionRead:
    if payload.parent_id is not None:
        records.get_or_404(session, LibraryCollection, payload.parent_id, "Folder")

    row = LibraryCollection(**payload.model_dump(), owner_id=user.id)
    session.add(row)
    try:
        session.commit()
    except Exception as exc:  # noqa: BLE001 - reported as a conflict, not a 500
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"There is already a folder called {payload.name!r} in the same place.",
        ) from exc
    session.refresh(row)
    return CollectionRead.model_validate(row)


@router.patch("/collections/{collection_id}", response_model=CollectionRead, summary="Rename it")
def update_collection(
    collection_id: uuid.UUID, payload: CollectionUpdate, session: DbSession, user: Writer
) -> CollectionRead:
    row = records.get_or_404(session, LibraryCollection, collection_id, "Folder")

    changes = payload.model_dump(exclude_unset=True)
    if changes.get("parent_id") == collection_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A folder cannot be inside itself."
        )
    for name, value in changes.items():
        setattr(row, name, value)
    session.commit()
    session.refresh(row)
    return CollectionRead.model_validate(row)


@router.delete("/collections/{collection_id}", response_model=Message, summary="Remove a folder")
def delete_collection(collection_id: uuid.UUID, session: DbSession, user: Writer) -> Message:
    row = records.get_or_404(session, LibraryCollection, collection_id, "Folder")
    name = row.name
    session.delete(row)
    session.commit()
    # Said explicitly. A folder is a view onto references, not a container of
    # them, and somebody about to press delete has to know which one this is.
    return Message(
        detail=f"Folder {name!r} removed. The references that were in it are still in the library."
    )


# --------------------------------------------------------------------------
# References
# --------------------------------------------------------------------------
@router.get("/references", response_model=Page[ReferenceRead], summary="Search the library")
def list_references(
    session: DbSession,
    user: Reader,
    q: Annotated[str | None, Query(description="Match title, authors, journal or keywords")] = None,
    collection_id: Annotated[uuid.UUID | None, Query()] = None,
    reference_type: Annotated[ReferenceType | None, Query()] = None,
    year_from: Annotated[int | None, Query()] = None,
    year_to: Annotated[int | None, Query()] = None,
    keyword: Annotated[str | None, Query()] = None,
    site_id: Annotated[uuid.UUID | None, Query(description="Attached to this site")] = None,
    artifact_id: Annotated[uuid.UUID | None, Query()] = None,
    museum_object_id: Annotated[uuid.UUID | None, Query()] = None,
    sort: Annotated[str, Query(pattern="^-?(year|title|created_at|authors)$")] = "-year",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ReferenceRead]:
    statement = select(Publication)

    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Publication.title).like(pattern),
                func.lower(Publication.authors).like(pattern),
                func.lower(Publication.journal).like(pattern),
                func.lower(Publication.abstract).like(pattern),
                func.lower(func.array_to_string(Publication.keywords, " ")).like(pattern),
            )
        )
    if collection_id is not None:
        statement = statement.where(
            Publication.collections.any(LibraryCollection.id == collection_id)
        )
    if reference_type is not None:
        statement = statement.where(Publication.reference_type == reference_type)
    if year_from is not None:
        statement = statement.where(Publication.year >= year_from)
    if year_to is not None:
        statement = statement.where(Publication.year <= year_to)
    if keyword:
        statement = statement.where(Publication.keywords.any(keyword))

    for column, value in (
        (ReferenceLink.site_id, site_id),
        (ReferenceLink.artifact_id, artifact_id),
        (ReferenceLink.museum_object_id, museum_object_id),
    ):
        if value is not None:
            statement = statement.where(
                Publication.id.in_(select(ReferenceLink.publication_id).where(column == value))
            )

    descending = sort.startswith("-")
    column = getattr(Publication, sort.lstrip("-"))
    # Nulls last either way: a library sorted by year should not open with
    # forty references that have no year on them.
    ordering = column.desc().nullslast() if descending else column.asc().nullslast()
    statement = statement.order_by(ordering, Publication.title)

    rows, total = records.paginate(session, statement, limit, offset)
    return Page[ReferenceRead](
        items=[_reference(session, row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/references",
    response_model=ReferenceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a reference",
)
def create_reference(payload: ReferenceCreate, session: DbSession, user: Writer) -> ReferenceRead:
    data = payload.model_dump(exclude={"collection_ids"})

    if data.get("doi"):
        existing = session.scalar(select(Publication).where(Publication.doi == data["doi"]))
        if existing is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    f"That DOI is already in the library, as {existing.title!r}. "
                    f"Open that reference rather than adding a second one."
                ),
            )

    row = Publication(**data, owner_id=user.id)
    _apply_collections(session, row, payload.collection_ids)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _reference(session, row)


@router.get("/references/{reference_id}", response_model=ReferenceRead, summary="One reference")
def read_reference(reference_id: uuid.UUID, session: DbSession, user: Reader) -> ReferenceRead:
    row = records.get_or_404(session, Publication, reference_id, "Reference")
    return _reference(session, row)


@router.patch("/references/{reference_id}", response_model=ReferenceRead, summary="Correct it")
def update_reference(
    reference_id: uuid.UUID, payload: ReferenceUpdate, session: DbSession, user: Writer
) -> ReferenceRead:
    row = records.get_or_404(session, Publication, reference_id, "Reference")

    changes = payload.model_dump(exclude_unset=True)
    collections = changes.pop("collection_ids", None)
    for name, value in changes.items():
        setattr(row, name, value)
    if collections is not None:
        _apply_collections(session, row, collections)

    session.commit()
    session.refresh(row)
    return _reference(session, row)


@router.delete("/references/{reference_id}", response_model=Message, summary="Remove a reference")
def delete_reference(
    reference_id: uuid.UUID, session: DbSession, request: Request, user: Writer
) -> Message:
    row = records.get_or_404(session, Publication, reference_id, "Reference")

    attached = (
        session.scalar(
            select(func.count())
            .select_from(ReferenceLink)
            .where(ReferenceLink.publication_id == reference_id)
        )
        or 0
    )
    title = row.title
    records.on_deleted(session, row, RESOURCE, user=user, request=request, label=title)
    session.delete(row)
    session.commit()

    detail = f"{title!r} removed from the library."
    if attached:
        detail += (
            f" It was attached to {attached} record{'' if attached == 1 else 's'}; "
            f"those attachments went with it."
        )
    return Message(detail=detail)


# --------------------------------------------------------------------------
# What a reference is about
# --------------------------------------------------------------------------
@router.get(
    "/references/{reference_id}/links",
    response_model=list[LinkRead],
    summary="What this reference is about",
)
def list_links(reference_id: uuid.UUID, session: DbSession, user: Reader) -> list[LinkRead]:
    records.get_or_404(session, Publication, reference_id, "Reference")
    rows = session.scalars(
        select(ReferenceLink).where(ReferenceLink.publication_id == reference_id)
    )
    return [_link(session, row) for row in rows]


@router.post(
    "/references/{reference_id}/links",
    response_model=LinkRead,
    status_code=status.HTTP_201_CREATED,
    summary="Attach it to a record",
    description=(
        "Attach a reference to the thing it is about, and say where in it.\n\n"
        "The `locator` is the point of this: a reference attached to a site is "
        "a bibliography entry, and the same reference attached to context 1042 "
        "at pages 88-91 is a finding aid."
    ),
)
def create_link(
    reference_id: uuid.UUID, payload: LinkCreate, session: DbSession, user: Writer
) -> LinkRead:
    records.get_or_404(session, Publication, reference_id, "Reference")

    given = [
        column
        for column, _model, _kind, _attribute in _TARGETS
        if getattr(payload, column) is not None
    ]
    if not given:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Attach this to a project, site, context, find or object.",
        )
    if len(given) > 1:
        # One target per link, so "what is this about" has one answer per row
        # and a list of them reads as a list rather than as a puzzle.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="One record per attachment. Add a second attachment for the second record.",
        )

    for column, model, _kind, _attribute in _TARGETS:
        identifier = getattr(payload, column)
        if identifier is not None:
            records.get_or_404(session, model, identifier, "Record")

    row = ReferenceLink(publication_id=reference_id, **payload.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return _link(session, row)


@router.delete("/links/{link_id}", response_model=Message, summary="Detach it")
def delete_link(link_id: uuid.UUID, session: DbSession, user: Writer) -> Message:
    row = records.get_or_404(session, ReferenceLink, link_id, "Attachment")
    session.delete(row)
    session.commit()
    return Message(detail="Detached. The reference is still in the library.")


@router.get(
    "/for-record",
    response_model=list[LinkRead],
    summary="The references attached to a record",
    description="What a site's, find's or object's own page shows under 'Published in'.",
)
def links_for_record(
    session: DbSession,
    user: Reader,
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    context_id: uuid.UUID | None = None,
    artifact_id: uuid.UUID | None = None,
    museum_object_id: uuid.UUID | None = None,
) -> list[LinkRead]:
    filters = {
        "project_id": project_id,
        "site_id": site_id,
        "context_id": context_id,
        "artifact_id": artifact_id,
        "museum_object_id": museum_object_id,
    }
    given = {name: value for name, value in filters.items() if value is not None}
    if not given:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Name the record to look up."
        )

    statement = select(ReferenceLink)
    for name, value in given.items():
        statement = statement.where(getattr(ReferenceLink, name) == value)

    rows = session.scalars(statement)
    return [_link(session, row, with_reference=True) for row in rows]


# --------------------------------------------------------------------------
# BibTeX
# --------------------------------------------------------------------------
def _read_bibtex(text: str) -> list[bibtex.Entry]:
    try:
        entries = bibtex.parse(text)
    except bibtex.BibtexError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not entries:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No references were found in that file. A BibTeX entry looks "
                "like `@article{key, title = {...}, ...}` and needs at least a "
                "title."
            ),
        )
    return entries


def _as_reference(entry: bibtex.Entry) -> ReferenceBase:
    return ReferenceBase(
        reference_type=entry.reference_type,
        citation_key=entry.citation_key,
        **dict(entry.fields),  # type: ignore[arg-type]
    )


@router.post(
    "/import/preview",
    response_model=ImportPreview,
    summary="What a BibTeX file would add",
    description="Reads the file and reports what it holds. Writes nothing.",
)
async def preview_import(
    session: DbSession,
    user: Writer,
    file: Annotated[UploadFile, File(description="A .bib file")],
) -> ImportPreview:
    text = (await file.read()).decode("utf-8", errors="replace")
    entries = _read_bibtex(text)

    seen_dois = {
        row.doi for row in session.scalars(select(Publication).where(Publication.doi.is_not(None)))
    }
    seen_keys = {
        row.citation_key
        for row in session.scalars(select(Publication).where(Publication.citation_key.is_not(None)))
    }

    fresh: list[ReferenceBase] = []
    duplicates = 0
    for entry in entries:
        doi = entry.fields.get("doi")
        if (doi and doi in seen_dois) or entry.citation_key in seen_keys:
            duplicates += 1
            continue
        fresh.append(_as_reference(entry))

    problems = []
    ignored = sorted({name for entry in entries for name in entry.ignored})
    if ignored:
        problems.append("These BibTeX fields were read and not stored: " + ", ".join(ignored) + ".")

    return ImportPreview(
        parsed=len(entries),
        duplicates=duplicates,
        new=len(fresh),
        entries=fresh[:200],
        problems=problems,
    )


@router.post(
    "/import",
    response_model=ImportResult,
    summary="Import a BibTeX file",
    description=(
        "Adds every entry that is not already here. A reference is taken as "
        "already here when its DOI matches, or when its citation key does — so "
        "importing the same file twice adds nothing the second time."
    ),
)
async def run_import(
    session: DbSession,
    user: Writer,
    file: Annotated[UploadFile, File(description="A .bib file")],
    collection_id: Annotated[
        uuid.UUID | None, Query(description="File everything imported into this folder")
    ] = None,
) -> ImportResult:
    text = (await file.read()).decode("utf-8", errors="replace")
    entries = _read_bibtex(text)

    folder = None
    if collection_id is not None:
        folder = records.get_or_404(session, LibraryCollection, collection_id, "Folder")

    seen_dois = {
        row.doi for row in session.scalars(select(Publication).where(Publication.doi.is_not(None)))
    }
    seen_keys = {
        row.citation_key
        for row in session.scalars(select(Publication).where(Publication.citation_key.is_not(None)))
    }

    created = 0
    skipped = 0
    for entry in entries:
        doi = entry.fields.get("doi")
        if (doi and doi in seen_dois) or entry.citation_key in seen_keys:
            skipped += 1
            continue

        reference = _as_reference(entry)
        row = Publication(**reference.model_dump(), owner_id=user.id)
        if folder is not None:
            row.collections = [folder]
        session.add(row)

        # Added to the seen sets as we go, so a file that repeats an entry
        # inside itself does not create it twice.
        if doi:
            seen_dois.add(str(doi))
        seen_keys.add(entry.citation_key)
        created += 1

    session.commit()

    detail = f"{created} reference{'' if created == 1 else 's'} added."
    if skipped:
        detail += f" {skipped} were already in the library."
    if folder is not None and created:
        detail += f" Filed in {folder.name!r}."
    return ImportResult(created=created, skipped=skipped, detail=detail)


@router.get(
    "/export.bib",
    summary="Download the library as BibTeX",
    description=(
        "Everything, or whatever the same filters as the search return. A "
        "library you cannot export is a library nobody sensible puts anything "
        "into."
    ),
    response_class=Response,
    responses={200: {"content": {"application/x-bibtex": {}}}},
)
def export_bibtex(
    session: DbSession,
    user: Reader,
    collection_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    q: str | None = None,
) -> Response:
    statement = select(Publication)
    if collection_id is not None:
        statement = statement.where(
            Publication.collections.any(LibraryCollection.id == collection_id)
        )
    if site_id is not None:
        statement = statement.where(
            Publication.id.in_(
                select(ReferenceLink.publication_id).where(ReferenceLink.site_id == site_id)
            )
        )
    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Publication.title).like(pattern),
                func.lower(Publication.authors).like(pattern),
            )
        )

    rows = list(session.scalars(statement.order_by(Publication.year, Publication.title)))
    body = bibtex.write(rows)  # type: ignore[arg-type]

    return Response(
        content=body.encode("utf-8"),
        media_type="application/x-bibtex; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="stratum-library.bib"'},
    )
