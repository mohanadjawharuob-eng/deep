"""Conventions the schema has to keep, checked mechanically.

These are not tests of behaviour. They are tests of the one class of mistake
that behaviour tests cannot catch: a difference between the database the tests
build and the database a migration builds. The test suite creates its schema
from the models, so anything the models and the migrations disagree about is
invisible here and fatal in production.

The enum one below is not hypothetical. A column declared
``Enum(SomeEnum, name="…")`` without ``values_callable`` stores the member
*name* — ``PHOTOGRAPHS`` — while every migration in this project writes the
member *value* — ``photographs``. The tests pass, because ``create_all`` builds
the type from the same declaration; the first insert on a real installation
fails with "invalid input value for enum".
"""

from __future__ import annotations

import enum

import pytest
from sqlalchemy import Enum as SAEnum

# Every model module has to be imported for its tables to be on the metadata.
import app.models  # noqa: F401
from app.db.base import Base


def _enum_columns() -> list[tuple[str, str, SAEnum]]:
    found = []
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if isinstance(column.type, SAEnum) and column.type.enum_class is not None:
                found.append((table.name, column.name, column.type))
    return found


def test_there_are_enum_columns_to_check() -> None:
    """A guard on the guard: a refactor that moved the models would otherwise
    turn the test below into a loop over nothing that passes forever."""
    assert len(_enum_columns()) > 20


@pytest.mark.parametrize(
    ("table", "column", "kind"),
    [pytest.param(*item, id=f"{item[0]}.{item[1]}") for item in _enum_columns()],
)
def test_an_enum_column_stores_its_values_not_its_member_names(
    table: str, column: str, kind: SAEnum
) -> None:
    members: type[enum.Enum] = kind.enum_class
    expected = [member.value for member in members]

    assert kind.enums == expected, (
        f"{table}.{column} would store {kind.enums} but every migration in this "
        f"project writes {expected}. Add "
        f"values_callable=lambda e: [m.value for m in e] to the Enum(...)."
    )


def test_every_media_schema_field_exists_on_its_model() -> None:
    """A response schema must not advertise a column its model lacks.

    This is how `folder_id` reached `Model3D`: it was added to a *shared*
    attachment schema, so three endpoints gained a field and one of them had
    no such column. The endpoint passed it straight to the constructor and
    blew up on a keyword argument - a failure with no connection, in the
    message, to the schema edit that caused it.
    """
    from app.models import Document, Model3D, Photograph
    from app.schemas.media import DocumentSummary, Model3DSummary, PhotographSummary

    pairs = (
        (PhotographSummary, Photograph),
        (DocumentSummary, Document),
        (Model3DSummary, Model3D),
    )

    for schema, model in pairs:
        columns = set(model.__table__.c.keys())
        attributes = {name for name in dir(model) if not name.startswith("_")}
        # Only the link fields. A schema legitimately carries values the
        # endpoint computes - `thumbnail_sizes` is not a column and should not
        # be - but a `*_id` is a foreign key by convention, and one that does
        # not exist is the mistake this is here to catch.
        for field in schema.model_fields:
            if not field.endswith("_id"):
                continue
            assert field in columns or field in attributes, (
                f"{schema.__name__}.{field} is not on {model.__name__}. A schema "
                f"that promises a field the model has not got fails at the "
                f"endpoint, with a message that does not mention the schema."
            )
