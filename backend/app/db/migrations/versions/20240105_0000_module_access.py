"""Per-module access, replacing the global role as the permission ceiling.

Revision ID: 0006_module_access
Revises: 0005_public_tokens
Created: 2026-08-01 06:00:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0006_module_access"
down_revision: Union[str, None] = "0005_public_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MODULES = ("archaeology", "museum", "social_media", "management", "inventory", "archive")
LEVELS = ("viewer", "contributor", "editor", "supervisor", "administrator")

#: The archaeology level each existing global role is worth. Chosen so that
#: every permission the old role table granted is still granted afterwards and
#: nothing new is: visitors read, students submit for approval, researchers
#: approve and start projects. Administrators get no row — they hold every
#: module implicitly, and a row would make revoking one look meaningful.
ROLE_TO_LEVEL = {
    "visitor": "viewer",
    "student": "contributor",
    "researcher": "supervisor",
}


def upgrade() -> None:
    module = postgresql.ENUM(*MODULES, name="module", create_type=False)
    module_level = postgresql.ENUM(*LEVELS, name="module_level", create_type=False)
    module.create(op.get_bind(), checkfirst=True)
    module_level.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "user_module_access",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module", module, nullable=False),
        sa.Column("level", module_level, nullable=False),
        sa.Column("granted_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
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
        sa.ForeignKeyConstraint(["granted_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "module", name="uq_user_module_access"),
    )
    op.create_index(
        op.f("ix_user_module_access_created_at"), "user_module_access", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_user_module_access_user_id"), "user_module_access", ["user_id"], unique=False
    )
    op.create_index(
        "ix_user_module_access_lookup", "user_module_access", ["user_id", "module"], unique=False
    )

    # Backfill, so nobody loses access the moment this is applied. Without it
    # every non-administrator would wake up with no module at all and the
    # platform would look empty to them.
    for role, level in ROLE_TO_LEVEL.items():
        op.execute(
            sa.text(
                """
                INSERT INTO user_module_access
                    (id, user_id, module, level, note, created_at, updated_at)
                SELECT gen_random_uuid(), u.id,
                       'archaeology'::module,
                       CAST(:level AS module_level),
                       'Granted by the migration to per-module access',
                       now(), now()
                  FROM users u
                 WHERE u.role = CAST(:role AS user_role)
                """
            ).bindparams(sa.bindparam("level", level), sa.bindparam("role", role))
        )


def downgrade() -> None:
    op.drop_index("ix_user_module_access_lookup", table_name="user_module_access")
    op.drop_index(op.f("ix_user_module_access_user_id"), table_name="user_module_access")
    op.drop_index(op.f("ix_user_module_access_created_at"), table_name="user_module_access")
    op.drop_table("user_module_access")

    for name in ("module_level", "module"):
        op.execute(sa.text(f"DROP TYPE IF EXISTS {name}"))
