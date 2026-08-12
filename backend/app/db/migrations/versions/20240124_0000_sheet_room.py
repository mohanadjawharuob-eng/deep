"""The sheet room: a spreadsheet kept as a document, not only as an import.

Revision ID: 0026_sheet_room
Revises: 0025_post_notes
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_sheet_room"
down_revision: Union[str, None] = "0025_post_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "import_batches",
        sa.Column("superseded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_import_batches_superseded_by",
        "import_batches",
        "import_batches",
        ["superseded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "import_batches",
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("import_batches", sa.Column("refreshed_path", sa.String(500), nullable=True))
    op.add_column(
        "import_batches",
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("import_batches", "refreshed_at")
    op.drop_column("import_batches", "refreshed_path")
    op.drop_column("import_batches", "is_archived")
    op.drop_constraint("fk_import_batches_superseded_by", "import_batches", type_="foreignkey")
    op.drop_column("import_batches", "superseded_by_id")
