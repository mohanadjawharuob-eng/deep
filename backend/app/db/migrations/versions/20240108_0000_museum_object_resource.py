"""Give museum objects their own resource type.

Museum objects are filed in the same storage hierarchy as excavated finds and
move through the same register, so the register has to be able to say which of
the two a row refers to. Until now the museum module borrowed
``resource_type = 'artifact'``, which was survivable only because nothing had
yet asked the register about a museum object — the object's own card advertises
a location history, and that history had no way to be found.

Adding a value to a PostgreSQL enum is not reversible, so the downgrade leaves
it in place. That is harmless: an unused enum value costs nothing, and removing
one means rebuilding the type and every column that uses it.

Revision ID: 0009_museum_object_resource
Revises: 0008_museum
"""

from __future__ import annotations

from alembic import op

revision = "0009_museum_object_resource"
down_revision = "0008_museum"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL 12 and later allow ADD VALUE inside a transaction as long as
    # the new value is not *used* in the same transaction. Nothing below uses
    # it, so Alembic's transaction is fine.
    op.execute("ALTER TYPE resource_type ADD VALUE IF NOT EXISTS 'museum_object'")


def downgrade() -> None:
    """Deliberately empty — see the module docstring."""
