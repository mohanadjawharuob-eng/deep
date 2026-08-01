"""Schemas for the spreadsheet importer."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ImportStatus
from app.schemas.common import ORMModel


class ImportColumn(BaseModel):
    """One column of the file, and what it is proposed to fill.

    This is the verification screen: a person reads it and confirms or corrects
    every line before anything is written.
    """

    column: str
    suggested_field: str | None = None
    field_label: str | None = None
    field_kind: str | None = None
    #: Values taken from the file, so what is being approved is visible.
    samples: list[str] = Field(default_factory=list)
    #: How many rows have anything in this column, out of how many.
    filled: int = 0
    total: int = 0


class ImportBatchSummary(ORMModel):
    id: uuid.UUID
    record_type: str
    filename: str
    sheet_name: str | None = None
    header_row: int
    status: ImportStatus
    total_rows: int
    created_count: int
    failed_count: int
    created_at: datetime


class ImportBatchDetail(ImportBatchSummary):
    columns: list[str] = Field(default_factory=list)
    mapping: dict[str, str | None] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)
    errors: list[dict[str, Any]] | None = None
    created_ids: list[str] | None = None
    note: str | None = None

    #: Filled by the endpoint, not the ORM.
    columns_detail: list[ImportColumn] = Field(default_factory=list)
    #: Required fields no column fills, named so the caller can say so before a run.
    unmapped_required: list[str] = Field(default_factory=list)
    #: Every field a column may be mapped onto.
    available_fields: list[dict[str, Any]] = Field(default_factory=list)


class ImportMappingUpdate(BaseModel):
    """What a person approved."""

    mapping: dict[str, str | None] | None = Field(
        default=None,
        description=(
            "Column heading to field name. `null` means the column is "
            "deliberately not imported. Columns you omit keep their current "
            "mapping."
        ),
    )
    defaults: dict[str, Any] | None = Field(
        default=None,
        description="Values applied to every row — usually the collection.",
    )
    sheet_name: str | None = Field(
        default=None, description="Re-read the file using a different worksheet."
    )
    header_row: int | None = Field(
        default=None, ge=1, description="Re-read the file using a different heading row."
    )
    note: str | None = None


class ImportRowResult(BaseModel):
    """What would happen, or did happen, to one row."""

    #: The row number in the file, so it can be found in Excel.
    row_number: int
    ok: bool
    values: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ImportPreview(BaseModel):
    total_rows: int
    valid_rows: int
    invalid_rows: int
    #: Failures first: they are what has to be acted on.
    rows: list[ImportRowResult] = Field(default_factory=list)
