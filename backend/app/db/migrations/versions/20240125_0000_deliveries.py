"""Files prepared for somebody to collect.

Revision ID: 0027_deliveries
Revises: 0026_sheet_room
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_deliveries"
down_revision: Union[str, None] = "0026_sheet_room"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None

delivery_status = sa.Enum(
    "preparing",
    "ready",
    "collected",
    "expired",
    "failed",
    name="delivery_status",
)


def upgrade() -> None:
    # Created before the table so ``create_table`` does not issue a second
    # CREATE TYPE for the same name.
    delivery_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "deliveries",
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
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("to_name", sa.String(200), nullable=False),
        sa.Column("to_email", sa.String(320), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="delivery_status", create_type=False),
            nullable=False,
            server_default="preparing",
        ),
        sa.Column("photograph_ids", postgresql.JSONB()),
        sa.Column("document_ids", postgresql.JSONB()),
        sa.Column("sheet_ids", postgresql.JSONB()),
        sa.Column("folder_path", sa.String(500)),
        sa.Column("zip_path", sa.String(500)),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing", postgresql.JSONB()),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("collected_at", sa.DateTime(timezone=True)),
        sa.Column("collected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.create_index("ix_deliveries_token", "deliveries", ["token"], unique=True)
    op.create_index("ix_deliveries_status", "deliveries", ["status"])
    op.create_index("ix_deliveries_owner_id", "deliveries", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_deliveries_owner_id", table_name="deliveries")
    op.drop_index("ix_deliveries_status", table_name="deliveries")
    op.drop_index("ix_deliveries_token", table_name="deliveries")
    op.drop_table("deliveries")
    delivery_status.drop(op.get_bind(), checkfirst=True)
