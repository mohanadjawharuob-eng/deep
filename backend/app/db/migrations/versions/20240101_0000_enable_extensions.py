"""Enable the PostgreSQL extensions the schema depends on.

Revision ID: 0001_extensions
Revises:
Created: 2024-01-01 00:00:00

PostGIS must exist before any table with a geometry column is created, so this
runs first and separately. ``pg_trgm`` backs fuzzy name search and
``unaccent`` lets a search for "Cesarea" match "Caesarea".
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001_extensions"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXTENSIONS = ("postgis", "pg_trgm", "unaccent", "btree_gin")


def upgrade() -> None:
    for extension in EXTENSIONS:
        op.execute(f'CREATE EXTENSION IF NOT EXISTS "{extension}"')


def downgrade() -> None:
    # Deliberately not dropping PostGIS: other schemas in the same database may
    # depend on it, and dropping it would cascade away their geometry columns.
    for extension in ("btree_gin", "unaccent", "pg_trgm"):
        op.execute(f'DROP EXTENSION IF EXISTS "{extension}"')
