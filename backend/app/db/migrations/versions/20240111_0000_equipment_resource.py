"""Give equipment its own resource type.

A total station lives on a shelf like everything else, so it moves through the
same storage register, carries the same printed label, and shows up in the same
activity log. All three are polymorphic over ``resource_type``, so the register
has to be able to say that a row is about a piece of kit rather than a find.

Adding a value to a PostgreSQL enum is not reversible, so the downgrade leaves
it in place. That is harmless: an unused enum value costs nothing, and removing
one means rebuilding the type and every column that uses it.

Revision ID: 0013_equipment_resource
Revises: 0012_floor_plans
"""

from __future__ import annotations

from alembic import op

revision = "0013_equipment_resource"
down_revision = "0012_floor_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL 12 and later allow ADD VALUE inside a transaction as long as
    # the new value is not *used* in the same transaction. Nothing below uses
    # it; the tables that will arrive in the next revision.
    op.execute("ALTER TYPE resource_type ADD VALUE IF NOT EXISTS 'equipment'")


def downgrade() -> None:
    """Deliberately empty — see the module docstring."""
