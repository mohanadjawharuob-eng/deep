"""Data requests: asking somebody outside the platform for a file.

Revision ID: 0021_data_requests
Revises: 0020_library
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_data_requests"
down_revision: Union[str, None] = "0020_library"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    kind = sa.Enum(
        "photographs",
        "documents",
        "drawings",
        "models_3d",
        "anything",
        name="data_request_kind",
    )
    state = sa.Enum(
        "open",
        "sent",
        "answered",
        "closed",
        "cancelled",
        name="data_request_status",
    )
    # Created here, once, rather than left to ``create_table``. The columns
    # below then declare ``create_type=False`` — without it SQLAlchemy issues a
    # second CREATE TYPE while building the table, which fails outright on any
    # database where the type already exists.
    kind.create(op.get_bind(), checkfirst=True)
    state.create(op.get_bind(), checkfirst=True)

    kind_column = postgresql.ENUM(name="data_request_kind", create_type=False)
    state_column = postgresql.ENUM(name="data_request_status", create_type=False)

    op.create_table(
        "data_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # What it is about. All four nullable; exactly one is set.
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="SET NULL")
        ),
        sa.Column(
            "artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("artifacts.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "context_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("excavation_contexts.id", ondelete="SET NULL"),
        ),
        sa.Column("record_label", sa.String(300), nullable=False),
        sa.Column("kind", kind_column, nullable=False, server_default="photographs"),
        sa.Column("message", sa.Text()),
        # To whom.
        sa.Column("recipient_email", sa.String(320), nullable=False),
        sa.Column("recipient_name", sa.String(200)),
        # The invitation. Only the hash is kept.
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uploads", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("upload_count", sa.Integer(), nullable=False, server_default="0"),
        # Where it has got to.
        sa.Column("status", state_column, nullable=False, server_default="open"),
        sa.Column("delivery_note", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("first_upload_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "requested_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
    )

    op.create_index("ix_data_requests_project_id", "data_requests", ["project_id"])
    op.create_index("ix_data_requests_site_id", "data_requests", ["site_id"])
    op.create_index("ix_data_requests_artifact_id", "data_requests", ["artifact_id"])
    op.create_index("ix_data_requests_context_id", "data_requests", ["context_id"])
    op.create_index("ix_data_requests_recipient_email", "data_requests", ["recipient_email"])
    op.create_index("ix_data_requests_requested_by_id", "data_requests", ["requested_by_id"])
    op.create_index("ix_data_requests_status", "data_requests", ["status"])
    # Every incoming invitation is looked up by this, on a route that is not
    # signed in — so it is the one index that has to be there.
    op.create_index("ix_data_requests_token_hash", "data_requests", ["token_hash"], unique=True)
    op.create_index("ix_data_requests_status_expiry", "data_requests", ["status", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_data_requests_status_expiry", table_name="data_requests")
    op.drop_index("ix_data_requests_token_hash", table_name="data_requests")
    op.drop_index("ix_data_requests_status", table_name="data_requests")
    op.drop_index("ix_data_requests_requested_by_id", table_name="data_requests")
    op.drop_index("ix_data_requests_recipient_email", table_name="data_requests")
    op.drop_index("ix_data_requests_context_id", table_name="data_requests")
    op.drop_index("ix_data_requests_artifact_id", table_name="data_requests")
    op.drop_index("ix_data_requests_site_id", table_name="data_requests")
    op.drop_index("ix_data_requests_project_id", table_name="data_requests")
    op.drop_table("data_requests")
    sa.Enum(name="data_request_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="data_request_kind").drop(op.get_bind(), checkfirst=True)
