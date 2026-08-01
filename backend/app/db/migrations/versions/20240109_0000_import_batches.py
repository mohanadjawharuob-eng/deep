"""Spreadsheet import batches.

An import is kept as a record: the file as uploaded, the column mapping a
person approved, and the identifiers of everything it created. Without that
last part a mistaken run is indistinguishable from ordinary cataloguing the
moment it finishes.

Revision ID: 0011_import_batches
Revises: 0010_retag_museum_objects
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0011_import_batches"
down_revision: Union[str, None] = "0010_retag_museum_objects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_batches",
        sa.Column("record_type", sa.String(length=60), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("stored_path", sa.String(length=500), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sheet_name", sa.String(length=200), nullable=True),
        sa.Column("header_row", sa.Integer(), nullable=False),
        sa.Column("columns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("mapping", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("defaults", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "analysed",
                "mapped",
                "previewed",
                "committed",
                "failed",
                "reverted",
                name="import_status",
            ),
            nullable=False,
        ),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("created_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_import_batches_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_batches")),
    )
    op.create_index(
        op.f("ix_import_batches_checksum"), "import_batches", ["checksum"], unique=False
    )
    op.create_index(
        op.f("ix_import_batches_created_at"), "import_batches", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_import_batches_owner_id"), "import_batches", ["owner_id"], unique=False
    )
    op.create_index(
        op.f("ix_import_batches_record_type"), "import_batches", ["record_type"], unique=False
    )
    op.create_index(op.f("ix_import_batches_status"), "import_batches", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_import_batches_status"), table_name="import_batches")
    op.drop_index(op.f("ix_import_batches_record_type"), table_name="import_batches")
    op.drop_index(op.f("ix_import_batches_owner_id"), table_name="import_batches")
    op.drop_index(op.f("ix_import_batches_created_at"), table_name="import_batches")
    op.drop_index(op.f("ix_import_batches_checksum"), table_name="import_batches")
    op.drop_table("import_batches")
    # The table owns this type; nothing else uses it.
    postgresql.ENUM(name="import_status").drop(op.get_bind(), checkfirst=True)
