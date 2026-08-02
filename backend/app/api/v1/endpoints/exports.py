"""Exporting a whole dataset as one workbook.

"Send me everything on Tell el-Demo" is one request, and the honest answer to
it is one file. Not a CSV of finds and another of contexts and a third of
photographs, which is a filing job handed back to whoever asked — one workbook
with a sheet per kind of record and a cover sheet explaining itself.

Three exports, because they are the three questions people actually ask:

``/exports/sites/{id}.xlsx``
    A site and everything under it. What a specialist asks for.
``/exports/projects/{id}.xlsx``
    A whole excavation, every site included. What a funder's final report
    needs, and what an archive deposit is.
``/exports/collections/{id}.xlsx``
    A museum collection, its objects and their conservation history. What
    goes to a registrar, an insurer or a loan partner.

Two rules run through all of them.

**Nothing is exported that the reader could not already read.** The same
visibility filter the listings use is applied here. An export is not a side
door: a student who cannot see an unapproved record on screen does not get it
in a spreadsheet either.

**A restricted site's coordinates stay restricted.** Blurring a location on
the map and then writing the true one into a downloadable file would make the
protection theatre. Anyone who cannot edit the site gets the blurred figure,
and the cover sheet says so — a silent blur is worse than none, because it
would be mistaken for survey error.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.permissions import (
    Capability,
    can_edit,
    can_view,
    has_capability,
    has_module_access,
    visibility_filter,
)
from app.models.artifact import Artifact
from app.models.context import ContextRelationship, ExcavationContext
from app.models.enums import ActivityAction, Module, ResourceType
from app.models.enums import ModuleLevel as Level
from app.models.media import Document, Model3D, Photograph
from app.models.museum import Collection, ConservationRecord, MuseumObject
from app.models.project import Project
from app.models.site import Site
from app.services import activity as activity_log
from app.services import records, workbooks
from app.services.workbooks import Column, Table, Workbook

router = APIRouter(prefix="/exports", tags=["Exports"])


@dataclass(slots=True)
class Vocabulary:
    """Identifier-to-name for the controlled vocabularies.

    Artifacts and museum objects hold ``material_id`` and ``period_id`` without
    a mapped relationship on every model, so a column that reached for
    ``row.period`` would work on one and raise on the other. Loading the three
    vocabularies once per export is three queries for the whole file, and
    means a column never has to know which model it is looking at.
    """

    materials: dict[uuid.UUID, str] = field(default_factory=dict)
    periods: dict[uuid.UUID, str] = field(default_factory=dict)
    categories: dict[uuid.UUID, str] = field(default_factory=dict)

    def named(self, table: dict[uuid.UUID, str], key: uuid.UUID | None) -> str | None:
        return table.get(key) if key else None


def _vocabulary(session: DbSession) -> Vocabulary:
    from app.models.taxonomy import Material, ObjectCategory, Period

    return Vocabulary(
        materials={row.id: row.name for row in session.scalars(select(Material)).all()},
        periods={row.id: row.name for row in session.scalars(select(Period)).all()},
        categories={row.id: row.name for row in session.scalars(select(ObjectCategory)).all()},
    )


def _name(record: Any, *names: str) -> Any:
    """The first attribute that has anything in it — for label columns."""
    for attribute in names:
        value = getattr(record, attribute, None)
        if value:
            return value
    return None


def _labelled(related: Any, *names: str) -> Any:
    """A related record's name, or nothing. Never its identifier."""
    if related is None:
        return None
    return _name(related, *names)


def _send(book: Workbook, kind: str, subject: str) -> Response:
    data = workbooks.build(book)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{workbooks.filename(kind, subject)}"'
        },
    )


def _log(
    session: DbSession,
    request: Request,
    user: Any,
    resource_type: ResourceType,
    record: Any,
    summary: str,
) -> None:
    activity_log.log(
        session,
        action=ActivityAction.EXPORT,
        user=user,
        resource_type=resource_type,
        resource_id=record.id,
        resource_label=records.label_for(record),
        summary=summary,
        request=request,
    )
    session.flush()


# --------------------------------------------------------------------------
# The column sets, shared between the site and project exports
# --------------------------------------------------------------------------
def _context_columns() -> list[Column]:
    return [
        Column("Context", attribute="context_number"),
        Column("Type", attribute="context_type"),
        Column("Site", get=lambda row: _labelled(row.site, "name")),
        Column("Trench", attribute="trench"),
        Column("Area", attribute="area"),
        Column("Square", attribute="square"),
        Column("Phase", attribute="phase"),
        Column("Stratigraphic unit", attribute="stratigraphic_unit"),
        Column("Description", attribute="description"),
        Column("Interpretation", attribute="interpretation"),
        Column("Munsell colour", attribute="munsell_color"),
        Column("Composition", attribute="composition"),
        Column("Compaction", attribute="compaction"),
        Column("Inclusions", attribute="inclusions"),
        Column("Thickness (cm)", attribute="thickness_cm"),
        Column("Length (cm)", attribute="length_cm"),
        Column("Width (cm)", attribute="width_cm"),
        Column("Depth (cm)", attribute="depth_cm"),
        Column("Top elevation", attribute="top_elevation"),
        Column("Bottom elevation", attribute="bottom_elevation"),
        Column("Excavated by", attribute="excavated_by"),
        Column("Review status", attribute="review_status"),
        Column("Identifier", attribute="id"),
    ]


def _artifact_columns(blur: bool, words: Vocabulary) -> list[Column]:
    return [
        Column("Inventory number", attribute="inventory_number"),
        Column("Field number", attribute="field_number"),
        Column("Name", attribute="name"),
        Column("Object type", attribute="object_type"),
        Column("Category", get=lambda row: words.named(words.categories, row.category_id)),
        Column("Typology", attribute="typology"),
        # The vocabulary term when there is one, the typed text when there is
        # not. A specialist wants the word, not a choice of two empty columns.
        Column(
            "Material",
            get=lambda row: words.named(words.materials, row.material_id) or row.material_text,
        ),
        Column(
            "Other materials",
            get=lambda row: ", ".join(
                item.name for item in (row.secondary_materials or []) if item.name
            ),
        ),
        Column("Technique", attribute="technique"),
        Column("Decoration", attribute="decoration"),
        Column("Inscription", attribute="inscription"),
        Column("Description", attribute="description"),
        Column("Site", get=lambda row: _labelled(row.site, "name")),
        Column("Context", get=lambda row: _labelled(row.context, "context_number")),
        Column("Trench", attribute="trench"),
        Column("Square", attribute="square"),
        Column("Stratigraphic unit", attribute="stratigraphic_unit"),
        Column("Depth (cm)", attribute="depth_cm"),
        Column("Elevation", attribute="elevation"),
        Column("Latitude", get=lambda row: None if blur else row.latitude),
        Column("Longitude", get=lambda row: None if blur else row.longitude),
        Column(
            "Period",
            get=lambda row: words.named(words.periods, row.period_id) or row.period_text,
        ),
        Column("Dated from", attribute="date_from"),
        Column("Dated to", attribute="date_to"),
        Column("Dating method", attribute="dating_method"),
        Column("Length (mm)", attribute="length_mm"),
        Column("Width (mm)", attribute="width_mm"),
        Column("Height (mm)", attribute="height_mm"),
        Column("Thickness (mm)", attribute="thickness_mm"),
        Column("Diameter (mm)", attribute="diameter_mm"),
        Column("Rim diameter (mm)", attribute="rim_diameter_mm"),
        Column("Weight (g)", attribute="weight_g"),
        Column("Quantity", attribute="quantity"),
        Column("Fragment", attribute="is_fragment"),
        Column("Condition", attribute="condition"),
        Column("Conservation status", attribute="conservation_status"),
        Column("Conservation notes", attribute="conservation_notes"),
        Column("Current location", attribute="current_location"),
        Column("Storage box", attribute="storage_box"),
        Column("On display", attribute="is_on_display"),
        Column("Found on", attribute="find_date"),
        Column("Found by", attribute="found_by"),
        Column("Recovery method", attribute="recovery_method"),
        Column("Keywords", attribute="keywords"),
        Column("Review status", attribute="review_status"),
        Column("Identifier", attribute="id"),
    ]


def _photograph_columns(blur: bool) -> list[Column]:
    return [
        Column("Title", attribute="title"),
        Column("Description", attribute="description"),
        Column("Photographer", attribute="photographer"),
        Column("Taken", attribute="taken_at"),
        Column("Shot type", attribute="shot_type"),
        Column("Has scale", attribute="has_scale"),
        Column("Latitude", get=lambda row: None if blur else row.latitude),
        Column("Longitude", get=lambda row: None if blur else row.longitude),
        Column("Place", attribute="location_text"),
        Column(
            "Camera",
            get=lambda row: " ".join(part for part in (row.camera_make, row.camera_model) if part),
        ),
        Column("Lens", attribute="lens"),
        Column("File", attribute="original_filename"),
        Column("Tags", attribute="tags"),
        Column("Identifier", attribute="id"),
    ]


def _document_columns() -> list[Column]:
    return [
        Column("Title", attribute="title"),
        Column("Type", attribute="document_type"),
        Column("Author", attribute="author"),
        Column("Description", attribute="description"),
        Column("File", attribute="original_filename"),
        Column("Identifier", attribute="id"),
    ]


def _site_columns(blur: bool) -> list[Column]:
    return [
        Column("Name", attribute="name"),
        Column("Code", attribute="code"),
        Column("Type", attribute="site_type"),
        Column("Country", attribute="country"),
        Column("Region", attribute="region"),
        Column("Description", attribute="description"),
        Column("Latitude", get=lambda row: None if blur else row.latitude),
        Column("Longitude", get=lambda row: None if blur else row.longitude),
        Column("Protection", attribute="protection_status"),
        Column("Review status", attribute="review_status"),
        Column("Identifier", attribute="id"),
    ]


# --------------------------------------------------------------------------
# Sites
# --------------------------------------------------------------------------
def _site_workbook(session: DbSession, site: Site, user: Any) -> Workbook:
    """A site and everything under it, as sheets."""
    words = _vocabulary(session)
    # Blurring is decided once and applied to every sheet. A coordinate hidden
    # on the site sheet and printed on the finds sheet protects nothing.
    blur = bool(getattr(site, "location_restricted", False)) and not can_edit(
        session, user, site, ResourceType.SITE
    )

    book = Workbook(
        subject=f"{site.name} ({site.code})" if site.code else site.name,
        kind="Site",
        exported_by=user.full_name or user.username,
    )
    if blur:
        book.notes.append(
            "This site's location is restricted, so the coordinate columns are "
            "empty. They are not missing data — the true position is withheld "
            "from anyone who cannot edit the site."
        )

    book.add(Table("Site", _site_columns(blur), [site]))

    contexts = session.scalars(
        select(ExcavationContext)
        .where(
            ExcavationContext.site_id == site.id,
            visibility_filter(user, ExcavationContext, ResourceType.CONTEXT),
        )
        .order_by(ExcavationContext.context_number)
    ).all()
    book.add(Table("Contexts", _context_columns(), contexts))

    if contexts:
        ids = [row.id for row in contexts]
        relationships = session.scalars(
            select(ContextRelationship).where(ContextRelationship.context_id.in_(ids))
        ).all()
        by_id = {row.id: row for row in contexts}
        book.add(
            Table(
                "Stratigraphy",
                [
                    Column(
                        "Context",
                        get=lambda row: _labelled(by_id.get(row.context_id), "context_number"),
                    ),
                    Column("Relationship", attribute="relationship"),
                    Column(
                        "Related context",
                        get=lambda row: _labelled(
                            by_id.get(row.related_context_id), "context_number"
                        ),
                    ),
                    Column("Certainty", attribute="certainty"),
                    Column("Notes", attribute="notes"),
                ],
                relationships,
                note="The Harris matrix, as one row per relationship.",
            )
        )

    artifacts = session.scalars(
        select(Artifact)
        .where(
            Artifact.site_id == site.id,
            visibility_filter(user, Artifact, ResourceType.ARTIFACT),
        )
        .order_by(Artifact.inventory_number)
    ).all()
    book.add(Table("Finds", _artifact_columns(blur, words), artifacts))

    photographs = session.scalars(
        select(Photograph)
        .where(
            Photograph.site_id == site.id,
            visibility_filter(user, Photograph, ResourceType.PHOTOGRAPH),
        )
        .order_by(Photograph.taken_at.asc().nullslast(), Photograph.title)
    ).all()
    book.add(Table("Photographs", _photograph_columns(blur), photographs))

    documents = session.scalars(
        select(Document)
        .where(
            Document.site_id == site.id,
            visibility_filter(user, Document, ResourceType.DOCUMENT),
        )
        .order_by(Document.title)
    ).all()
    book.add(Table("Documents", _document_columns(), documents))

    models = session.scalars(
        select(Model3D).where(Model3D.site_id == site.id).order_by(Model3D.title)
    ).all()
    book.add(
        Table(
            "3D models",
            [
                Column("Title", attribute="title"),
                Column("Format", attribute="file_format"),
                Column("File", attribute="original_filename"),
                Column("Identifier", attribute="id"),
            ],
            models,
        )
    )
    return book


@router.get(
    "/sites/{site_id}.xlsx",
    response_class=Response,
    summary="A site and everything in it",
    description=(
        "One workbook: the site, its contexts, the stratigraphy between them, "
        "its finds, its photographs, its documents and its 3D models. Only "
        "what the reader could already see, and a restricted site's "
        "coordinates stay withheld."
    ),
    responses={
        200: {
            "content": {"application/vnd.openxmlformats-officedocument" ".spreadsheetml.sheet": {}}
        }
    },
)
def export_site(
    site_id: uuid.UUID, session: DbSession, request: Request, user: CurrentUser
) -> Response:
    site = records.get_or_404(session, Site, site_id, "Site")
    if not can_view(session, user, site, ResourceType.SITE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Site not found")
    if not has_capability(user, Capability.EXPORT_DATA, Module.ARCHAEOLOGY):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Your access does not permit exporting data"
        )

    book = _site_workbook(session, site, user)
    _log(session, request, user, ResourceType.SITE, site, f"Exported {site.name} as a workbook")
    return _send(book, "site", site.code or site.name)


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------
@router.get(
    "/projects/{project_id}.xlsx",
    response_class=Response,
    summary="A whole excavation",
    description=(
        "Every site in the project and everything under them, in one file — "
        "what a final report or an archive deposit is made from."
    ),
)
def export_project(
    project_id: uuid.UUID, session: DbSession, request: Request, user: CurrentUser
) -> Response:
    project = records.get_or_404(session, Project, project_id, "Project")
    if not can_view(session, user, project, ResourceType.PROJECT):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")
    if not has_capability(user, Capability.EXPORT_DATA, Module.ARCHAEOLOGY):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Your access does not permit exporting data"
        )

    words = _vocabulary(session)
    sites = session.scalars(
        select(Site)
        .where(Site.project_id == project.id, visibility_filter(user, Site, ResourceType.SITE))
        .order_by(Site.name)
    ).all()

    book = Workbook(
        subject=f"{project.name} ({project.code})",
        kind="Project",
        exported_by=user.full_name or user.username,
    )

    restricted = [
        site
        for site in sites
        if getattr(site, "location_restricted", False)
        and not can_edit(session, user, site, ResourceType.SITE)
    ]
    if restricted:
        book.notes.append(
            f"{len(restricted)} of these sites have a restricted location, so their "
            "coordinate columns are empty. That is deliberate, not missing data."
        )

    book.add(
        Table(
            "Project",
            [
                Column("Name", attribute="name"),
                Column("Code", attribute="code"),
                Column("Institution", attribute="institution"),
                Column("Country", attribute="country"),
                Column("Region", attribute="region"),
                Column("Status", attribute="status"),
                Column("Starts", attribute="start_date"),
                Column("Ends", attribute="end_date"),
                Column("Description", attribute="description"),
                Column("Identifier", attribute="id"),
            ],
            [project],
        )
    )

    # Sheets are per *kind*, not per site: forty sheets called "Tell A finds",
    # "Tell B finds" is unusable, and a Site column sorts and filters.
    blurred = {site.id for site in restricted}
    book.add(Table("Sites", _site_columns(False), sites))

    site_ids = [site.id for site in sites]
    if site_ids:
        contexts = session.scalars(
            select(ExcavationContext)
            .where(
                ExcavationContext.site_id.in_(site_ids),
                visibility_filter(user, ExcavationContext, ResourceType.CONTEXT),
            )
            .order_by(ExcavationContext.context_number)
        ).all()
        book.add(Table("Contexts", _context_columns(), contexts))

        artifacts = session.scalars(
            select(Artifact)
            .where(
                Artifact.site_id.in_(site_ids),
                visibility_filter(user, Artifact, ResourceType.ARTIFACT),
            )
            .order_by(Artifact.inventory_number)
        ).all()
        columns = _artifact_columns(False, words)
        for column in columns:
            if column.header in {"Latitude", "Longitude"}:
                attribute = column.header.lower()
                column.get = (
                    lambda row, name=attribute: None
                    if row.site_id in blurred
                    else getattr(row, name)
                )
        book.add(Table("Finds", columns, artifacts))

        photographs = session.scalars(
            select(Photograph)
            .where(
                Photograph.site_id.in_(site_ids),
                visibility_filter(user, Photograph, ResourceType.PHOTOGRAPH),
            )
            .order_by(Photograph.title)
        ).all()
        book.add(Table("Photographs", _photograph_columns(False), photographs))

        documents = session.scalars(
            select(Document)
            .where(
                Document.site_id.in_(site_ids),
                visibility_filter(user, Document, ResourceType.DOCUMENT),
            )
            .order_by(Document.title)
        ).all()
        book.add(Table("Documents", _document_columns(), documents))

    _log(
        session,
        request,
        user,
        ResourceType.PROJECT,
        project,
        f"Exported {project.name} as a workbook",
    )
    return _send(book, "project", project.code or project.name)


# --------------------------------------------------------------------------
# Museum collections
# --------------------------------------------------------------------------
def _object_columns(show_value: bool, words: Vocabulary) -> list[Column]:
    columns = [
        Column("Accession number", attribute="accession_number"),
        Column("Former number", attribute="former_number"),
        Column("Name", attribute="name"),
        Column("Object type", attribute="object_type"),
        Column("Category", get=lambda row: words.named(words.categories, row.category_id)),
        Column("Description", attribute="description"),
        Column("Materials", attribute="materials"),
        Column("Techniques", attribute="techniques"),
        Column("Period", get=lambda row: words.named(words.periods, row.period_id)),
        Column("Dated from", attribute="date_from"),
        Column("Dated to", attribute="date_to"),
        Column("Culture", attribute="culture"),
        Column("Provenance", attribute="provenance"),
        Column("Acquisition method", attribute="acquisition_method"),
        Column("Acquired on", attribute="acquisition_date"),
        Column("Acquired from", attribute="acquisition_source"),
        Column("Status", attribute="status"),
        Column("Condition", attribute="condition"),
        Column("On display", attribute="is_on_display"),
        Column("Height (mm)", attribute="height_mm"),
        Column("Width (mm)", attribute="width_mm"),
        Column("Depth (mm)", attribute="depth_mm"),
        Column("Weight (g)", attribute="weight_g"),
        Column("Identifier", attribute="id"),
    ]
    if show_value:
        # Valuations are withheld from anyone who cannot edit the object, on
        # screen and here. A valuation in a file that gets forwarded is an
        # invitation, and an export is the easiest thing in the world to
        # forward.
        columns.insert(-1, Column("Valuation", attribute="valuation"))
        columns.insert(-1, Column("Valuation currency", attribute="valuation_currency"))
    return columns


@router.get(
    "/collections/{collection_id}.xlsx",
    response_class=Response,
    summary="A museum collection",
    description=(
        "The collection, its objects and their conservation history.\n\n"
        "**Valuations are included only for somebody who could already see "
        "them** — that is, who may edit the objects. A valuation in a file "
        "that gets forwarded is an invitation."
    ),
)
def export_collection(
    collection_id: uuid.UUID, session: DbSession, request: Request, user: CurrentUser
) -> Response:
    collection = records.get_or_404(session, Collection, collection_id, "Collection")
    if not has_module_access(user, Module.MUSEUM, Level.VIEWER) and not collection.is_public:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Collection not found")
    if not has_capability(user, Capability.EXPORT_DATA, Module.MUSEUM):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Your access does not permit exporting data"
        )

    show_value = has_module_access(user, Module.MUSEUM, Level.CONTRIBUTOR)
    words = _vocabulary(session)

    book = Workbook(
        subject=f"{collection.name} ({collection.code})" if collection.code else collection.name,
        kind="Collection",
        exported_by=user.full_name or user.username,
    )
    if not show_value:
        book.notes.append(
            "Valuations are not in this file. They are withheld from anyone "
            "who cannot edit the objects."
        )

    book.add(
        Table(
            "Collection",
            [
                Column("Name", attribute="name"),
                Column("Code", attribute="code"),
                Column("Description", attribute="description"),
                Column("Identifier", attribute="id"),
            ],
            [collection],
        )
    )

    objects = session.scalars(
        select(MuseumObject)
        .where(MuseumObject.collection_id == collection.id)
        .order_by(MuseumObject.accession_number)
    ).all()
    book.add(Table("Objects", _object_columns(show_value, words), objects))

    if objects:
        treatments = session.scalars(
            select(ConservationRecord)
            .where(ConservationRecord.object_id.in_([row.id for row in objects]))
            .order_by(ConservationRecord.performed_on)
        ).all()
        by_id = {row.id: row for row in objects}
        book.add(
            Table(
                "Conservation",
                [
                    Column(
                        "Object",
                        get=lambda row: _labelled(by_id.get(row.object_id), "accession_number"),
                    ),
                    Column("Treatment", attribute="treatment_type"),
                    Column("Performed on", attribute="performed_on"),
                    Column("By", attribute="performed_by"),
                    Column("Condition before", attribute="condition_before"),
                    Column("Condition after", attribute="condition_after"),
                    Column("Materials used", attribute="materials_used"),
                    Column("Description", attribute="description"),
                    Column("Identifier", attribute="id"),
                ],
                treatments,
            )
        )

    _log(
        session,
        request,
        user,
        ResourceType.MUSEUM_OBJECT,
        collection,
        f"Exported the {collection.name} collection as a workbook",
    )
    return _send(book, "collection", collection.code or collection.name)
