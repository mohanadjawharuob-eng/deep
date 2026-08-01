"""Floor plans.

Where the store *is*, drawn. The storage hierarchy already answers which shelf
an object is on; a plan answers where that shelf is, which is the question
somebody standing in the doorway of an unfamiliar room actually has.

Shape coordinates are normalised to 0–1 of the plan's extent, so a plan drawn
against one background scan still lines up after the scan is replaced.

Revision ID: 0012_floor_plans
Revises: 0011_import_batches
Created: 2026-08-01 21:14:12.155267+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0012_floor_plans"
down_revision: Union[str, None] = "0011_import_batches"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "floor_plans",
        sa.Column("location_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_path", sa.String(length=500), nullable=True),
        sa.Column("image_width", sa.Integer(), nullable=True),
        sa.Column("image_height", sa.Integer(), nullable=True),
        sa.Column("image_mime", sa.String(length=100), nullable=True),
        sa.Column("width_m", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("height_m", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
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
        sa.CheckConstraint(
            "height_m IS NULL OR height_m > 0", name=op.f("ck_floor_plans_ck_floor_plans_height")
        ),
        sa.CheckConstraint(
            "width_m IS NULL OR width_m > 0", name=op.f("ck_floor_plans_ck_floor_plans_width")
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["storage_locations.id"],
            name=op.f("fk_floor_plans_location_id_storage_locations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_floor_plans_owner_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_floor_plans")),
    )
    op.create_index(op.f("ix_floor_plans_created_at"), "floor_plans", ["created_at"], unique=False)
    op.create_index(
        op.f("ix_floor_plans_location_id"), "floor_plans", ["location_id"], unique=False
    )
    op.create_table(
        "floor_plan_shapes",
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("rect", "polygon", "circle", "pin", "wall", "label", name="shape_kind"),
            nullable=False,
        ),
        sa.Column("points", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("colour", sa.String(length=30), nullable=True),
        sa.Column("rotation", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("z_index", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.UUID(), nullable=True),
        sa.Column(
            "resource_type",
            postgresql.ENUM(name="resource_type", create_type=False),
            nullable=True,
        ),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            ["location_id"],
            ["storage_locations.id"],
            name=op.f("fk_floor_plan_shapes_location_id_storage_locations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["floor_plans.id"],
            name=op.f("fk_floor_plan_shapes_plan_id_floor_plans"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_floor_plan_shapes")),
    )
    op.create_index(
        op.f("ix_floor_plan_shapes_created_at"), "floor_plan_shapes", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_floor_plan_shapes_location_id"), "floor_plan_shapes", ["location_id"], unique=False
    )
    op.create_index(
        op.f("ix_floor_plan_shapes_plan_id"), "floor_plan_shapes", ["plan_id"], unique=False
    )
    op.create_index(
        op.f("ix_floor_plan_shapes_resource_id"), "floor_plan_shapes", ["resource_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_floor_plan_shapes_resource_id"), table_name="floor_plan_shapes")
    op.drop_index(op.f("ix_floor_plan_shapes_plan_id"), table_name="floor_plan_shapes")
    op.drop_index(op.f("ix_floor_plan_shapes_location_id"), table_name="floor_plan_shapes")
    op.drop_index(op.f("ix_floor_plan_shapes_created_at"), table_name="floor_plan_shapes")
    op.drop_table("floor_plan_shapes")
    op.drop_index(op.f("ix_floor_plans_location_id"), table_name="floor_plans")
    op.drop_index(op.f("ix_floor_plans_created_at"), table_name="floor_plans")
    op.drop_table("floor_plans")
    postgresql.ENUM(name="shape_kind").drop(op.get_bind(), checkfirst=True)
