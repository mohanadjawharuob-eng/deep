"""Retag existing museum-object rows onto their own resource type.

The previous revision added ``museum_object`` to ``resource_type``. Rows
written before it exist under ``artifact``: movements, revisions and activity
entries whose ``resource_id`` is in fact a museum object. They are identified
without ambiguity by that id being present in ``museum_objects``, so the
retagging is exact — a find's id is never in that table.

This has to be a separate revision because PostgreSQL refuses to use a value
added to an enum in the transaction that added it, and Alembic is configured
for one transaction per migration.

Revision ID: 0010_retag_museum_objects
Revises: 0009_museum_object_resource
"""

from __future__ import annotations

from alembic import op

revision = "0010_retag_museum_objects"
down_revision = "0009_museum_object_resource"
branch_labels = None
depends_on = None

#: Tables carrying a polymorphic ``resource_type`` / ``resource_id`` pair.
TABLES = ("storage_movements", "revisions", "activity_logs", "record_permissions")


def upgrade() -> None:
    for table in TABLES:
        op.execute(
            f"""
            UPDATE {table} AS t
               SET resource_type = 'museum_object'
             WHERE t.resource_type = 'artifact'
               AND EXISTS (SELECT 1 FROM museum_objects m WHERE m.id = t.resource_id)
            """
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(
            f"UPDATE {table} SET resource_type = 'artifact' "
            f"WHERE resource_type = 'museum_object'"
        )
