"""Fields an institution adds to the platform's forms.

Revision ID: 0024_custom_fields
Revises: 0023_folders
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_custom_fields"
down_revision: Union[str, None] = "0023_folders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "custom_fields",
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
        sa.Column("record_type", sa.String(60), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False, server_default="text"),
        sa.Column("choices", postgresql.ARRAY(sa.String(120))),
        sa.Column("help", sa.Text()),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("record_type", "name", name="uq_custom_fields_record_name"),
    )
    op.create_index("ix_custom_fields_record_type", "custom_fields", ["record_type"])


def downgrade() -> None:
    op.drop_index("ix_custom_fields_record_type", table_name="custom_fields")
    op.drop_table("custom_fields")
