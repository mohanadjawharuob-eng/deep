"""Make room for the activity hub: two new enum values.

The hub needs a module of its own (so access to "what we did and what it cost"
is granted separately from everything else) and a resource type of its own (so
an activity can appear in the activity log, carry revisions, and be pointed at
by a task in the same polymorphic shape as every other record).

Both are values on existing PostgreSQL enums, and this is a **separate
revision** from the tables that use them for one reason: PostgreSQL will not
let a value added to an enum be *used* in the same transaction that added it.
Putting the ALTER TYPE and the backfill in one migration produces "unsafe use
of new value" and a failed upgrade. Splitting them is the fix, and it is the
same shape as 0013, which did this for equipment.

Adding a value to an enum is not reversible, so the downgrade leaves both in
place. That is harmless: an unused enum value costs nothing, while removing one
means rebuilding the type and every column that uses it.

Revision ID: 0017_activity_module
Revises: 0016_social
"""

from __future__ import annotations

from alembic import op

revision = "0017_activity_module"
down_revision = "0016_social"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE module ADD VALUE IF NOT EXISTS 'activities'")
    op.execute("ALTER TYPE resource_type ADD VALUE IF NOT EXISTS 'activity'")


def downgrade() -> None:
    """Deliberately empty — see the module docstring."""
