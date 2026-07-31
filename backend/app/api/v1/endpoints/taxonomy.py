"""Controlled vocabularies: periods, materials and object categories.

These describe the recording scheme rather than anybody's excavation, so they
are readable without authentication — the create and edit forms need them
before a visitor has signed in. Editing them is an administrator's job.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.api.deps import DbSession, require_capability
from app.core.permissions import Capability
from app.models.enums import ActivityAction
from app.models.taxonomy import Material, ObjectCategory, Period
from app.models.user import User
from app.schemas.common import Message, ORMModel
from app.schemas.project import slugify
from app.services import activity

router = APIRouter(prefix="/taxonomy", tags=["Vocabularies"])

RequireTaxonomyAdmin = Annotated[User, Depends(require_capability(Capability.MANAGE_TAXONOMY))]


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class PeriodRead(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    abbreviation: str | None = None
    description: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    region: str | None = None
    color: str | None = None
    parent_id: uuid.UUID | None = None
    sort_order: int


class PeriodWrite(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    abbreviation: str | None = Field(default=None, max_length=20)
    description: str | None = None
    start_year: int | None = Field(default=None, description="Negative is BCE")
    end_year: int | None = None
    region: str | None = Field(default=None, max_length=150)
    color: str | None = Field(default=None, pattern="^#[0-9a-fA-F]{6}$")
    parent_id: uuid.UUID | None = None
    sort_order: int = 0


class MaterialRead(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    group: str | None = None
    parent_id: uuid.UUID | None = None


class MaterialWrite(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    group: str | None = Field(default=None, max_length=80)
    parent_id: uuid.UUID | None = None


class CategoryRead(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    parent_id: uuid.UUID | None = None


class CategoryWrite(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    parent_id: uuid.UUID | None = None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _unique_slug(session: DbSession, model: Any, name: str) -> str:
    base = slugify(name)
    candidate, counter = base, 2
    while session.scalar(select(model.id).where(model.slug == candidate)) is not None:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def _check_parent(session: DbSession, model: Any, parent_id: uuid.UUID | None) -> None:
    if parent_id is not None and session.get(model, parent_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Parent not found")


# --------------------------------------------------------------------------
# Periods
# --------------------------------------------------------------------------
@router.get("/periods", response_model=list[PeriodRead], summary="List periods")
def list_periods(
    session: DbSession,
    q: Annotated[str | None, Query()] = None,
    region: Annotated[str | None, Query()] = None,
    year: Annotated[
        int | None, Query(description="Only periods spanning this year; negative is BCE")
    ] = None,
) -> list[PeriodRead]:
    statement = select(Period)
    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Period.name).like(pattern), func.lower(Period.abbreviation).like(pattern)
            )
        )
    if region:
        statement = statement.where(func.lower(Period.region) == region.lower())
    if year is not None:
        statement = statement.where(
            or_(Period.start_year.is_(None), Period.start_year <= year),
            or_(Period.end_year.is_(None), Period.end_year >= year),
        )
    rows = session.scalars(statement.order_by(Period.sort_order, Period.name)).all()
    return [PeriodRead.model_validate(row) for row in rows]


@router.post(
    "/periods",
    response_model=PeriodRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a period (administrator)",
)
def create_period(
    payload: PeriodWrite, session: DbSession, request: Request, user: RequireTaxonomyAdmin
) -> PeriodRead:
    if (
        payload.start_year is not None
        and payload.end_year is not None
        and payload.end_year < payload.start_year
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="end_year cannot precede start_year"
        )
    _check_parent(session, Period, payload.parent_id)

    period = Period(**payload.model_dump(), slug=_unique_slug(session, Period, payload.name))
    session.add(period)
    session.flush()
    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_label=period.name,
        summary=f"Created period {period.name!r}",
        request=request,
    )
    return PeriodRead.model_validate(period)


@router.patch(
    "/periods/{period_id}",
    response_model=PeriodRead,
    summary="Update a period (administrator)",
)
def update_period(
    period_id: uuid.UUID,
    payload: PeriodWrite,
    session: DbSession,
    request: Request,
    user: RequireTaxonomyAdmin,
) -> PeriodRead:
    period = session.get(Period, period_id)
    if period is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Period not found")
    if payload.parent_id == period_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A period cannot be its own parent"
        )
    _check_parent(session, Period, payload.parent_id)

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(period, key, value)
    session.add(period)
    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_label=period.name,
        summary=f"Updated period {period.name!r}",
        request=request,
    )
    session.flush()
    return PeriodRead.model_validate(period)


@router.delete(
    "/periods/{period_id}",
    response_model=Message,
    summary="Delete a period (administrator)",
    description=(
        "Records referring to the period keep their own `period_text`; their "
        "`period_id` is cleared rather than the records being removed."
    ),
)
def delete_period(
    period_id: uuid.UUID, session: DbSession, request: Request, user: RequireTaxonomyAdmin
) -> Message:
    period = session.get(Period, period_id)
    if period is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Period not found")
    name = period.name
    session.delete(period)
    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=user,
        resource_label=name,
        summary=f"Deleted period {name!r}",
        request=request,
    )
    return Message(detail=f"Period {name!r} deleted")


# --------------------------------------------------------------------------
# Materials
# --------------------------------------------------------------------------
@router.get("/materials", response_model=list[MaterialRead], summary="List materials")
def list_materials(
    session: DbSession,
    q: Annotated[str | None, Query()] = None,
    group: Annotated[str | None, Query()] = None,
) -> list[MaterialRead]:
    statement = select(Material)
    if q:
        statement = statement.where(func.lower(Material.name).like(f"%{q.lower()}%"))
    if group:
        statement = statement.where(func.lower(Material.group) == group.lower())
    rows = session.scalars(statement.order_by(Material.name)).all()
    return [MaterialRead.model_validate(row) for row in rows]


@router.post(
    "/materials",
    response_model=MaterialRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a material (administrator)",
)
def create_material(
    payload: MaterialWrite, session: DbSession, request: Request, user: RequireTaxonomyAdmin
) -> MaterialRead:
    _check_parent(session, Material, payload.parent_id)
    material = Material(**payload.model_dump(), slug=_unique_slug(session, Material, payload.name))
    session.add(material)
    session.flush()
    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_label=material.name,
        summary=f"Created material {material.name!r}",
        request=request,
    )
    return MaterialRead.model_validate(material)


@router.delete(
    "/materials/{material_id}",
    response_model=Message,
    summary="Delete a material (administrator)",
)
def delete_material(
    material_id: uuid.UUID, session: DbSession, request: Request, user: RequireTaxonomyAdmin
) -> Message:
    material = session.get(Material, material_id)
    if material is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Material not found")
    name = material.name
    session.delete(material)
    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=user,
        resource_label=name,
        summary=f"Deleted material {name!r}",
        request=request,
    )
    return Message(detail=f"Material {name!r} deleted")


# --------------------------------------------------------------------------
# Object categories
# --------------------------------------------------------------------------
@router.get("/categories", response_model=list[CategoryRead], summary="List object categories")
def list_categories(
    session: DbSession,
    q: Annotated[str | None, Query()] = None,
    parent_id: Annotated[uuid.UUID | None, Query()] = None,
    top_level: Annotated[bool, Query(description="Only categories with no parent")] = False,
) -> list[CategoryRead]:
    statement = select(ObjectCategory)
    if q:
        statement = statement.where(func.lower(ObjectCategory.name).like(f"%{q.lower()}%"))
    if parent_id is not None:
        statement = statement.where(ObjectCategory.parent_id == parent_id)
    elif top_level:
        statement = statement.where(ObjectCategory.parent_id.is_(None))
    rows = session.scalars(statement.order_by(ObjectCategory.name)).all()
    return [CategoryRead.model_validate(row) for row in rows]


@router.post(
    "/categories",
    response_model=CategoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an object category (administrator)",
)
def create_category(
    payload: CategoryWrite, session: DbSession, request: Request, user: RequireTaxonomyAdmin
) -> CategoryRead:
    _check_parent(session, ObjectCategory, payload.parent_id)
    category = ObjectCategory(
        **payload.model_dump(), slug=_unique_slug(session, ObjectCategory, payload.name)
    )
    session.add(category)
    session.flush()
    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_label=category.name,
        summary=f"Created category {category.name!r}",
        request=request,
    )
    return CategoryRead.model_validate(category)


@router.delete(
    "/categories/{category_id}",
    response_model=Message,
    summary="Delete an object category (administrator)",
)
def delete_category(
    category_id: uuid.UUID, session: DbSession, request: Request, user: RequireTaxonomyAdmin
) -> Message:
    category = session.get(ObjectCategory, category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Category not found")
    name = category.name
    session.delete(category)
    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=user,
        resource_label=name,
        summary=f"Deleted category {name!r}",
        request=request,
    )
    return Message(detail=f"Category {name!r} deleted")
