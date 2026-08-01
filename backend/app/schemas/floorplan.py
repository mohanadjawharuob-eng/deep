"""Schemas for floor plans."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator

from app.models.enums import ResourceType, ShapeKind
from app.schemas.common import ORMModel

#: A point on a plan, as a fraction of its extent.
Point = Annotated[list[float], Field(min_length=2, max_length=2)]

#: How many vertices a polygon may have. Generous for a room outline, small
#: enough that a runaway client cannot store a megabyte of coordinates.
MAX_POINTS = 200


def _check_points(kind: ShapeKind, points: list[list[float]]) -> list[list[float]]:
    """Every coordinate is a fraction of the plan, and each kind needs its own
    number of them. Storing a rectangle with one corner is storing nothing."""
    required = {
        ShapeKind.RECT: 2,
        ShapeKind.CIRCLE: 2,
        ShapeKind.PIN: 1,
        ShapeKind.LABEL: 1,
    }
    minimum = required.get(kind, 2)

    if len(points) < minimum:
        raise ValueError(
            f"A {kind.value} needs at least {minimum} point"
            f"{'' if minimum == 1 else 's'}; {len(points)} given"
        )
    if kind in required and len(points) != required[kind]:
        raise ValueError(f"A {kind.value} takes exactly {required[kind]} points")
    if len(points) > MAX_POINTS:
        raise ValueError(f"A shape may have at most {MAX_POINTS} points")

    for point in points:
        if len(point) != 2:
            raise ValueError("Every point is an [x, y] pair")
        if not all(0 <= value <= 1 for value in point):
            raise ValueError(
                "Coordinates are fractions of the plan, so every value must be "
                "between 0 and 1. Divide pixel positions by the plan's width "
                "and height before sending them."
            )
    return points


class ShapeBase(BaseModel):
    kind: ShapeKind
    points: list[Point]
    label: str | None = Field(default=None, max_length=200)
    #: A token name from the palette rather than a hex, so a plan drawn today
    #: still fits the interface after a redesign.
    colour: str | None = Field(default=None, max_length=30)
    rotation: float = 0
    z_index: int = 0
    location_id: uuid.UUID | None = None
    resource_type: ResourceType | None = None
    resource_id: uuid.UUID | None = None
    notes: str | None = None

    @field_validator("points")
    @classmethod
    def _points_are_fractions(cls, value: list[list[float]], info: Any) -> list[list[float]]:
        kind = info.data.get("kind")
        return _check_points(kind, value) if kind else value


class ShapeCreate(ShapeBase):
    pass


class ShapeUpdate(BaseModel):
    kind: ShapeKind | None = None
    points: list[Point] | None = None
    label: str | None = Field(default=None, max_length=200)
    colour: str | None = Field(default=None, max_length=30)
    rotation: float | None = None
    z_index: int | None = None
    location_id: uuid.UUID | None = None
    resource_type: ResourceType | None = None
    resource_id: uuid.UUID | None = None
    notes: str | None = None


class ShapeRead(ORMModel):
    id: uuid.UUID
    kind: ShapeKind
    points: list[list[float]]
    label: str | None = None
    colour: str | None = None
    rotation: float = 0
    z_index: int = 0
    location_id: uuid.UUID | None = None
    resource_type: ResourceType | None = None
    resource_id: uuid.UUID | None = None
    notes: str | None = None

    #: Filled by the endpoint from the store, so a plan never keeps its own
    #: copy of what is in a cabinet.
    location_name: str | None = None
    location_path: str | None = None
    item_count: int | None = None


class FloorPlanBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    width_m: float | None = Field(default=None, gt=0, le=10_000)
    height_m: float | None = Field(default=None, gt=0, le=10_000)
    is_default: bool = True


class FloorPlanCreate(FloorPlanBase):
    location_id: uuid.UUID


class FloorPlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    width_m: float | None = Field(default=None, gt=0, le=10_000)
    height_m: float | None = Field(default=None, gt=0, le=10_000)
    is_default: bool | None = None


class FloorPlanSummary(ORMModel):
    id: uuid.UUID
    location_id: uuid.UUID
    name: str
    description: str | None = None
    image_path: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    image_mime: str | None = None
    width_m: float | None = None
    height_m: float | None = None
    is_default: bool
    created_at: datetime

    #: Convenience for a client that would otherwise fetch the location too.
    location_name: str | None = None
    location_path: str | None = None
    shape_count: int = 0
    #: Where the background image is served from, when there is one.
    image_url: str | None = None


class FloorPlanDetail(FloorPlanSummary):
    shapes: list[ShapeRead] = Field(default_factory=list)


class ShapeReorder(BaseModel):
    """A whole plan's shapes, replaced in one call.

    Drawing is a rapid sequence of small edits, and a request per drag would
    make the editor feel like a form. Replacing the set atomically also means a
    half-applied plan is not a state that can exist.
    """

    shapes: list[ShapeCreate]
