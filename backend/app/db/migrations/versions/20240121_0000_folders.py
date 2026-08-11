"""Folders: somewhere to put things, made by the people who use the platform.

Revision ID: 0023_folders
Revises: 0022_media_museum_object
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_folders"
down_revision: Union[str, None] = "0022_media_museum_object"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None

#: The two kinds of file people actually file by hand.
FILED = ("photographs", "documents")


def upgrade() -> None:
    kind = sa.Enum("general", "facebook", "instagram", name="folder_kind")
    kind.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "folders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("folders.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "kind",
            postgresql.ENUM(name="folder_kind", create_type=False),
            nullable=False,
            server_default="general",
        ),
        sa.Column("note", sa.Text()),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.UniqueConstraint("parent_id", "name", name="uq_folders_sibling_name"),
    )

    op.create_index("ix_folders_name", "folders", ["name"])
    op.create_index("ix_folders_parent_id", "folders", ["parent_id"])
    op.create_index("ix_folders_kind", "folders", ["kind"])
    # `UNIQUE(parent_id, name)` does not catch two folders both called
    # "Photographs" at the top level, because NULL is not equal to NULL.
    op.create_index(
        "uq_folders_root_name",
        "folders",
        ["name"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NULL"),
    )

    for table in FILED:
        op.add_column(
            table,
            sa.Column(
                "folder_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("folders.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index(f"ix_{table}_folder_id", table, ["folder_id"])


def downgrade() -> None:
    for table in FILED:
        op.drop_index(f"ix_{table}_folder_id", table_name=table)
        op.drop_column(table, "folder_id")

    op.drop_index("uq_folders_root_name", table_name="folders")
    op.drop_index("ix_folders_kind", table_name="folders")
    op.drop_index("ix_folders_parent_id", table_name="folders")
    op.drop_index("ix_folders_name", table_name="folders")
    op.drop_table("folders")
    sa.Enum(name="folder_kind").drop(op.get_bind(), checkfirst=True)
