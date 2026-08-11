"""Media can hang from a museum object.

Revision ID: 0022_media_museum_object
Revises: 0021_data_requests
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_media_museum_object"
down_revision: Union[str, None] = "0021_data_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None

#: Every table that can hold a picture, a document, a drawing or a model.
TABLES = ("photographs", "documents", "models_3d", "media_folders")

#: Requests too: the commonest thing a museum needs asked for is a
#: photograph of an object somebody else has. `SET NULL` rather than
#: `CASCADE`, because that a file was asked for and never arrived is
#: exactly the question somebody asks after the record has gone.
REQUEST_TABLE = "data_requests"


def upgrade() -> None:
    # Nullable, so no backfill and no default: an existing photograph belongs
    # to a site or a find and always did. This only opens a door that was shut
    # - the museum half of the platform could not hold a photograph at all,
    # because every media record hung from an excavation record.
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                "museum_object_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("museum_objects.id", ondelete="CASCADE"),
                nullable=True,
            ),
        )
        op.create_index(f"ix_{table}_museum_object_id", table, ["museum_object_id"])

    op.add_column(
        REQUEST_TABLE,
        sa.Column(
            "museum_object_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("museum_objects.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        f"ix_{REQUEST_TABLE}_museum_object_id", REQUEST_TABLE, ["museum_object_id"]
    )


def downgrade() -> None:
    op.drop_index(f"ix_{REQUEST_TABLE}_museum_object_id", table_name=REQUEST_TABLE)
    op.drop_column(REQUEST_TABLE, "museum_object_id")
    for table in TABLES:
        op.drop_index(f"ix_{table}_museum_object_id", table_name=table)
        op.drop_column(table, "museum_object_id")
