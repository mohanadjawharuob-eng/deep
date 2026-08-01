"""Give sites and projects a public token, so they can carry a QR label.

Revision ID: 0005_public_tokens
Revises: 0004_audit_clock_timestamp
Created: 2026-07-31 21:21:26.747168+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_public_tokens"
down_revision: Union[str, None] = "0004_audit_clock_timestamp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Artifacts already had one. Sites and projects get labels too — a site marker
#: and a project folder are both things a printed QR code is stuck to.
TABLES = ("projects", "sites")


def upgrade() -> None:
    # The column is NOT NULL and UNIQUE, and the default lives in Python rather
    # than the database, so adding it in one statement would fail on any table
    # that already holds rows. Three steps instead: add it nullable, give every
    # existing row its own token, then tighten the constraints.
    for table in TABLES:
        op.add_column(table, sa.Column("public_token", sa.String(length=32), nullable=True))

        # gen_random_uuid() is built into PostgreSQL 13+ and matches what the
        # model generates (uuid4().hex — 32 lower-case hex characters).
        op.execute(
            sa.text(
                f"UPDATE {table} SET public_token = replace(gen_random_uuid()::text, '-', '') "
                "WHERE public_token IS NULL"
            )
        )

        op.alter_column(table, "public_token", existing_type=sa.String(length=32), nullable=False)
        op.create_index(
            op.f(f"ix_{table}_public_token"), table, ["public_token"], unique=True
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_index(op.f(f"ix_{table}_public_token"), table_name=table)
        op.drop_column(table, "public_token")
