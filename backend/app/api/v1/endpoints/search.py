"""Global search across every record type.

One query returns matching projects, sites, artifacts and contexts, each scoped
by the same visibility rules that govern the individual listings — search must
never become a way to discover records the caller could not otherwise read.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUserOptional, DbSession
from app.core.permissions import visibility_filter
from app.models.artifact import Artifact
from app.models.context import ExcavationContext
from app.models.enums import ResourceType
from app.models.project import Project
from app.models.site import Site
from app.models.taxonomy import Material, Period

router = APIRouter(prefix="/search", tags=["Search"])

#: How many hits of each type a mixed search returns before the caller has to
#: narrow it with ``types``. Keeps one popular type from crowding out the rest.
PER_TYPE_LIMIT = 25


class SearchHit(BaseModel):
    id: uuid.UUID
    resource_type: ResourceType
    title: str
    subtitle: str | None = None
    description: str | None = None
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    latitude: float | None = None
    longitude: float | None = None
    date_from: int | None = None
    date_to: int | None = None


class SearchResults(BaseModel):
    query: str | None = None
    total: int = Field(description="Hits across every type, after filtering")
    counts: dict[str, int] = Field(description="Hits per resource type")
    items: list[SearchHit]


def _like(column: Any, pattern: str) -> Any:
    return func.lower(column).like(pattern)


def _date_overlap(model: Any, date_from: int | None, date_to: int | None) -> list[Any]:
    """Clauses matching records whose date range *overlaps* the query range.

    Containment would be wrong: a site dated 3000–2000 BCE is a legitimate hit
    for a search of 2500–2400 BCE, and an unknown bound should not exclude it.
    """
    clauses: list[Any] = []
    if date_from is not None:
        clauses.append(or_(model.date_to.is_(None), model.date_to >= date_from))
    if date_to is not None:
        clauses.append(or_(model.date_from.is_(None), model.date_from <= date_to))
    return clauses


@router.get(
    "",
    response_model=SearchResults,
    summary="Search everything",
    description=(
        "Free-text search with structured filters, across projects, sites, "
        "artifacts and excavation contexts.\n\n"
        "Results respect the caller's permissions: anonymous visitors see only "
        "public, approved records. At least one of `q`, a filter, or `types` "
        "must be given — an unbounded search of the whole database is not a "
        "useful answer to any question."
    ),
    responses={422: {"description": "No search terms given"}},
)
def search(
    session: DbSession,
    user: CurrentUserOptional,
    q: Annotated[str | None, Query(min_length=1, max_length=200, description="Free text")] = None,
    types: Annotated[
        list[ResourceType] | None,
        Query(description="Restrict to these record types; repeat the parameter"),
    ] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    site_id: Annotated[uuid.UUID | None, Query()] = None,
    period_id: Annotated[uuid.UUID | None, Query()] = None,
    material_id: Annotated[uuid.UUID | None, Query()] = None,
    country: Annotated[str | None, Query()] = None,
    institution: Annotated[str | None, Query()] = None,
    researcher: Annotated[
        str | None, Query(description="Match principal investigator or excavator")
    ] = None,
    date_from: Annotated[int | None, Query(description="Earliest year; negative is BCE")] = None,
    date_to: Annotated[int | None, Query(description="Latest year; negative is BCE")] = None,
    bbox: Annotated[
        str | None, Query(description="Bounding box as `minLon,minLat,maxLon,maxLat`")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SearchResults:
    filters_given = any(
        value is not None
        for value in (
            q,
            project_id,
            site_id,
            period_id,
            material_id,
            country,
            institution,
            researcher,
            date_from,
            date_to,
            bbox,
        )
    )
    if not filters_given:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Give a search term (`q`) or at least one filter",
        )

    wanted = (
        set(types)
        if types
        else {
            ResourceType.PROJECT,
            ResourceType.SITE,
            ResourceType.ARTIFACT,
            ResourceType.CONTEXT,
        }
    )
    pattern = f"%{q.lower()}%" if q else None
    box = _parse_bbox(bbox) if bbox else None

    hits: list[SearchHit] = []
    counts: dict[str, int] = {}

    # --- Projects --------------------------------------------------------
    # A site filter excludes projects: a search scoped to one site is asking
    # about that site's contents, not about the project containing it.
    if ResourceType.PROJECT in wanted and site_id is None and material_id is None:
        statement = select(Project).where(visibility_filter(user, Project, ResourceType.PROJECT))
        if pattern:
            statement = statement.where(
                or_(
                    _like(Project.name, pattern),
                    _like(Project.code, pattern),
                    _like(Project.description, pattern),
                    _like(Project.institution, pattern),
                    _like(Project.region, pattern),
                )
            )
        if project_id is not None:
            statement = statement.where(Project.id == project_id)
        if country:
            statement = statement.where(func.lower(Project.country) == country.lower())
        if institution:
            statement = statement.where(_like(Project.institution, f"%{institution.lower()}%"))
        if researcher:
            statement = statement.where(
                _like(Project.principal_investigator, f"%{researcher.lower()}%")
            )
        if box:
            statement = statement.where(
                Project.longitude.between(box[0], box[2]),
                Project.latitude.between(box[1], box[3]),
            )
        # Projects carry no year columns, so a date filter cannot apply to them.
        if date_from is None and date_to is None and period_id is None:
            rows = session.scalars(statement.order_by(Project.name).limit(PER_TYPE_LIMIT)).all()
            counts["project"] = len(rows)
            hits.extend(
                SearchHit(
                    id=row.id,
                    resource_type=ResourceType.PROJECT,
                    title=row.name,
                    subtitle=row.code,
                    description=row.description,
                    project_id=row.id,
                    latitude=float(row.latitude) if row.latitude is not None else None,
                    longitude=float(row.longitude) if row.longitude is not None else None,
                )
                for row in rows
            )

    # --- Sites -----------------------------------------------------------
    if ResourceType.SITE in wanted and material_id is None:
        statement = select(Site).where(visibility_filter(user, Site, ResourceType.SITE))
        if pattern:
            statement = statement.where(
                or_(
                    _like(Site.name, pattern),
                    _like(Site.code, pattern),
                    _like(Site.description, pattern),
                    _like(func.array_to_string(Site.alternative_names, " "), pattern),
                    _like(Site.period_text, pattern),
                )
            )
        if project_id is not None:
            statement = statement.where(Site.project_id == project_id)
        if site_id is not None:
            statement = statement.where(Site.id == site_id)
        if period_id is not None:
            statement = statement.where(Site.period_id == period_id)
        if country:
            statement = statement.where(func.lower(Site.country) == country.lower())
        if researcher:
            statement = statement.where(_like(Site.discovered_by, f"%{researcher.lower()}%"))
        if institution:
            statement = statement.where(
                Site.project_id.in_(
                    select(Project.id).where(_like(Project.institution, f"%{institution.lower()}%"))
                )
            )
        for clause in _date_overlap(Site, date_from, date_to):
            statement = statement.where(clause)
        if box:
            statement = statement.where(
                Site.longitude.between(box[0], box[2]),
                Site.latitude.between(box[1], box[3]),
            )

        rows = session.scalars(statement.order_by(Site.name).limit(PER_TYPE_LIMIT)).all()
        counts["site"] = len(rows)
        hits.extend(
            SearchHit(
                id=row.id,
                resource_type=ResourceType.SITE,
                title=row.name,
                subtitle=row.code,
                description=row.description,
                project_id=row.project_id,
                site_id=row.id,
                # Restricted coordinates are rounded here as well, so search
                # cannot be used to sidestep the site endpoint's masking.
                latitude=_masked(row.latitude, row.location_restricted),
                longitude=_masked(row.longitude, row.location_restricted),
                date_from=row.date_from,
                date_to=row.date_to,
            )
            for row in rows
        )

    # --- Artifacts -------------------------------------------------------
    if ResourceType.ARTIFACT in wanted:
        statement = select(Artifact).where(visibility_filter(user, Artifact, ResourceType.ARTIFACT))
        if pattern:
            statement = statement.where(
                or_(
                    _like(Artifact.inventory_number, pattern),
                    _like(Artifact.field_number, pattern),
                    _like(Artifact.name, pattern),
                    _like(Artifact.object_type, pattern),
                    _like(Artifact.description, pattern),
                    _like(Artifact.material_text, pattern),
                    _like(Artifact.typology, pattern),
                )
            )
        if project_id is not None:
            statement = statement.where(
                Artifact.site_id.in_(select(Site.id).where(Site.project_id == project_id))
            )
        if site_id is not None:
            statement = statement.where(Artifact.site_id == site_id)
        if period_id is not None:
            statement = statement.where(Artifact.period_id == period_id)
        if material_id is not None:
            statement = statement.where(Artifact.material_id == material_id)
        if country:
            statement = statement.where(
                Artifact.site_id.in_(
                    select(Site.id).where(func.lower(Site.country) == country.lower())
                )
            )
        if researcher:
            statement = statement.where(_like(Artifact.found_by, f"%{researcher.lower()}%"))
        for clause in _date_overlap(Artifact, date_from, date_to):
            statement = statement.where(clause)
        if box:
            statement = statement.where(
                Artifact.longitude.between(box[0], box[2]),
                Artifact.latitude.between(box[1], box[3]),
            )

        rows = session.scalars(
            statement.order_by(Artifact.inventory_number).limit(PER_TYPE_LIMIT)
        ).all()
        counts["artifact"] = len(rows)
        hits.extend(
            SearchHit(
                id=row.id,
                resource_type=ResourceType.ARTIFACT,
                title=row.inventory_number,
                subtitle=row.name or row.object_type,
                description=row.description,
                site_id=row.site_id,
                latitude=float(row.latitude) if row.latitude is not None else None,
                longitude=float(row.longitude) if row.longitude is not None else None,
                date_from=row.date_from,
                date_to=row.date_to,
            )
            for row in rows
        )

    # --- Contexts --------------------------------------------------------
    if ResourceType.CONTEXT in wanted and material_id is None:
        statement = select(ExcavationContext).where(
            visibility_filter(user, ExcavationContext, ResourceType.CONTEXT)
        )
        if pattern:
            statement = statement.where(
                or_(
                    _like(ExcavationContext.context_number, pattern),
                    _like(ExcavationContext.description, pattern),
                    _like(ExcavationContext.interpretation, pattern),
                    _like(ExcavationContext.stratigraphic_unit, pattern),
                )
            )
        if project_id is not None:
            statement = statement.where(
                ExcavationContext.site_id.in_(select(Site.id).where(Site.project_id == project_id))
            )
        if site_id is not None:
            statement = statement.where(ExcavationContext.site_id == site_id)
        if period_id is not None:
            statement = statement.where(ExcavationContext.period_id == period_id)
        if researcher:
            statement = statement.where(
                or_(
                    _like(ExcavationContext.excavated_by, f"%{researcher.lower()}%"),
                    _like(ExcavationContext.recorded_by, f"%{researcher.lower()}%"),
                )
            )
        for clause in _date_overlap(ExcavationContext, date_from, date_to):
            statement = statement.where(clause)

        rows = session.scalars(
            statement.order_by(ExcavationContext.context_number).limit(PER_TYPE_LIMIT)
        ).all()
        counts["context"] = len(rows)
        hits.extend(
            SearchHit(
                id=row.id,
                resource_type=ResourceType.CONTEXT,
                title=row.context_number,
                subtitle=row.context_type.value,
                description=row.description or row.interpretation,
                site_id=row.site_id,
                latitude=float(row.latitude) if row.latitude is not None else None,
                longitude=float(row.longitude) if row.longitude is not None else None,
                date_from=row.date_from,
                date_to=row.date_to,
            )
            for row in rows
        )

    return SearchResults(query=q, total=len(hits), counts=counts, items=hits[:limit])


def _masked(value: Any, restricted: bool) -> float | None:
    if value is None:
        return None
    number = float(value)
    return round(number, 2) if restricted else number


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        min_lon, min_lat, max_lon, max_lat = (float(part) for part in bbox.split(","))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="bbox must be four numbers: minLon,minLat,maxLon,maxLat",
        ) from exc
    if min_lon > max_lon or min_lat > max_lat:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="bbox minimum exceeds its maximum"
        )
    return min_lon, min_lat, max_lon, max_lat


class SuggestItem(BaseModel):
    id: uuid.UUID
    label: str
    kind: str


@router.get(
    "/suggest",
    response_model=list[SuggestItem],
    summary="Type-ahead suggestions",
    description="Fast prefix matches for the search box: sites, projects, periods and materials.",
)
def suggest(
    session: DbSession,
    user: CurrentUserOptional,
    q: Annotated[str, Query(min_length=2, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
) -> list[SuggestItem]:
    prefix = f"{q.lower()}%"
    contains = f"%{q.lower()}%"
    out: list[SuggestItem] = []

    projects = session.scalars(
        select(Project)
        .where(
            visibility_filter(user, Project, ResourceType.PROJECT),
            or_(_like(Project.name, contains), _like(Project.code, prefix)),
        )
        .order_by(Project.name)
        .limit(limit)
    ).all()
    out.extend(SuggestItem(id=row.id, label=row.name, kind="project") for row in projects)

    sites = session.scalars(
        select(Site)
        .where(
            visibility_filter(user, Site, ResourceType.SITE),
            or_(_like(Site.name, contains), _like(Site.code, prefix)),
        )
        .order_by(Site.name)
        .limit(limit)
    ).all()
    out.extend(SuggestItem(id=row.id, label=row.name, kind="site") for row in sites)

    # Vocabularies are reference data: readable by anyone, since they describe
    # the schema rather than anybody's excavation.
    periods = session.scalars(
        select(Period).where(_like(Period.name, contains)).order_by(Period.sort_order).limit(limit)
    ).all()
    out.extend(SuggestItem(id=row.id, label=row.name, kind="period") for row in periods)

    materials = session.scalars(
        select(Material).where(_like(Material.name, contains)).order_by(Material.name).limit(limit)
    ).all()
    out.extend(SuggestItem(id=row.id, label=row.name, kind="material") for row in materials)

    return out[:limit]
