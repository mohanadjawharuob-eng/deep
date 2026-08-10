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

from app.db.base import Base

# Every model module has to be imported for its tables to be on the metadata.
import app.models  # noqa: F401


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
