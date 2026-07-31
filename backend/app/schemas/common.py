"""Shared response envelopes and query parameter models."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    """Base for schemas read straight off an ORM object."""

    model_config = ConfigDict(from_attributes=True)


class Message(BaseModel):
    """Simple acknowledgement body."""

    detail: str


class ErrorResponse(BaseModel):
    """Shape of every error the API returns."""

    detail: str
    code: str | None = Field(
        default=None, description="Stable machine-readable error code, when available"
    )


class Page(BaseModel, Generic[T]):
    """Offset-paginated list."""

    items: list[T]
    total: int = Field(description="Total rows matching the query, ignoring pagination")
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class PaginationParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
