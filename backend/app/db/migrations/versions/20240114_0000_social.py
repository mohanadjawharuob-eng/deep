"""The social media repository: what the institution has said in public.

Outreach is a record. A photograph of a find that went out on Instagram in
March is part of that find's history, and "have we already published this" is a
question somebody asks before every press enquiry.

Two things here are load-bearing:

- ``social_posts.resource_type`` reuses the platform's existing enum rather
  than declaring its own, so a post can be *about* a find or a site in the same
  polymorphic shape as everything else. It is attached with ``create_type=False``
  because the type already exists — autogenerate emits a fresh ``sa.Enum``,
  which tries to CREATE TYPE a second time and fails the migration.
- ``uq_post_metrics_moment`` refuses two engagement readings for the same post
  at the same instant. A double-entry there makes every chart wrong in a way
  that looks like real growth.

Revision ID: 0016_social
Revises: 0015_management
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0016_social"
down_revision: Union[str, None] = "0015_management"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "social_accounts",
        sa.Column(
            "platform",
            sa.Enum(
                "instagram",
                "facebook",
                "x",
                "youtube",
                "linkedin",
                "threads",
                "bluesky",
                "mastodon",
                "website",
                "newsletter",
                "press",
                "other",
                name="social_platform",
            ),
            nullable=False,
        ),
        sa.Column("handle", sa.String(length=160), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("manager_id", sa.UUID(), nullable=True),
        sa.Column("manager_label", sa.String(length=200), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("follower_count", sa.Integer(), nullable=True),
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
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "follower_count IS NULL OR follower_count >= 0",
            name=op.f("ck_social_accounts_ck_social_accounts_followers_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["manager_id"],
            ["users.id"],
            name=op.f("fk_social_accounts_manager_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_social_accounts_owner_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_social_accounts")),
        sa.UniqueConstraint("platform", "handle", name="uq_social_accounts_handle"),
    )
    op.create_index(
        op.f("ix_social_accounts_created_at"), "social_accounts", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_social_accounts_is_active"), "social_accounts", ["is_active"], unique=False
    )
    op.create_index(
        op.f("ix_social_accounts_is_public"), "social_accounts", ["is_public"], unique=False
    )
    op.create_index(
        op.f("ix_social_accounts_manager_id"), "social_accounts", ["manager_id"], unique=False
    )
    op.create_index(
        op.f("ix_social_accounts_owner_id"), "social_accounts", ["owner_id"], unique=False
    )
    op.create_index(
        op.f("ix_social_accounts_platform"), "social_accounts", ["platform"], unique=False
    )
    op.create_table(
        "social_posts",
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("hashtags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "post",
                "story",
                "reel",
                "video",
                "thread",
                "article",
                "announcement",
                name="post_kind",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "needs_approval",
                "approved",
                "scheduled",
                "published",
                "withdrawn",
                name="post_status",
            ),
            nullable=False,
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_url", sa.String(length=600), nullable=True),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column(
            "resource_type",
            # The type already exists; create_type=False stops autogenerate's
            # fresh sa.Enum from trying to CREATE TYPE it a second time.
            postgresql.ENUM(name="resource_type", create_type=False),
            nullable=True,
        ),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("approved_by_id", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_note", sa.Text(), nullable=True),
        sa.Column("reveals_location", sa.Boolean(), nullable=False),
        sa.Column("location_warning", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["social_accounts.id"],
            name=op.f("fk_social_posts_account_id_social_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["users.id"],
            name=op.f("fk_social_posts_approved_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_social_posts_owner_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_social_posts_project_id_projects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_social_posts")),
    )
    op.create_index(
        op.f("ix_social_posts_account_id"), "social_posts", ["account_id"], unique=False
    )
    op.create_index(
        "ix_social_posts_account_status", "social_posts", ["account_id", "status"], unique=False
    )
    op.create_index(
        "ix_social_posts_calendar", "social_posts", ["status", "scheduled_for"], unique=False
    )
    op.create_index(
        op.f("ix_social_posts_created_at"), "social_posts", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_social_posts_is_public"), "social_posts", ["is_public"], unique=False)
    op.create_index(op.f("ix_social_posts_kind"), "social_posts", ["kind"], unique=False)
    op.create_index(op.f("ix_social_posts_language"), "social_posts", ["language"], unique=False)
    op.create_index(op.f("ix_social_posts_owner_id"), "social_posts", ["owner_id"], unique=False)
    op.create_index(
        op.f("ix_social_posts_project_id"), "social_posts", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_social_posts_published_at"), "social_posts", ["published_at"], unique=False
    )
    op.create_index(
        op.f("ix_social_posts_resource_id"), "social_posts", ["resource_id"], unique=False
    )
    op.create_index(
        op.f("ix_social_posts_scheduled_for"), "social_posts", ["scheduled_for"], unique=False
    )
    op.create_index(op.f("ix_social_posts_status"), "social_posts", ["status"], unique=False)
    op.create_index(
        "ix_social_posts_subject", "social_posts", ["resource_type", "resource_id"], unique=False
    )
    op.create_index(op.f("ix_social_posts_title"), "social_posts", ["title"], unique=False)
    op.create_table(
        "post_metrics",
        sa.Column("post_id", sa.UUID(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=True),
        sa.Column("reach", sa.Integer(), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("comments", sa.Integer(), nullable=True),
        sa.Column("shares", sa.Integer(), nullable=True),
        sa.Column("saves", sa.Integer(), nullable=True),
        sa.Column("clicks", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=True),
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
        sa.CheckConstraint(
            "(impressions IS NULL OR impressions >= 0) AND (reach IS NULL OR reach >= 0) AND (likes IS NULL OR likes >= 0) AND (comments IS NULL OR comments >= 0) AND (shares IS NULL OR shares >= 0) AND (saves IS NULL OR saves >= 0) AND (clicks IS NULL OR clicks >= 0)",
            name=op.f("ck_post_metrics_ck_post_metrics_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["social_posts.id"],
            name=op.f("fk_post_metrics_post_id_social_posts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_post_metrics")),
        sa.UniqueConstraint("post_id", "recorded_at", name="uq_post_metrics_moment"),
    )
    op.create_index(
        op.f("ix_post_metrics_created_at"), "post_metrics", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_post_metrics_post_id"), "post_metrics", ["post_id"], unique=False)
    op.create_index(
        op.f("ix_post_metrics_recorded_at"), "post_metrics", ["recorded_at"], unique=False
    )
    op.create_index(
        "ix_post_metrics_series", "post_metrics", ["post_id", "recorded_at"], unique=False
    )
    op.create_table(
        "post_assets",
        sa.Column("post_id", sa.UUID(), nullable=False),
        sa.Column("photograph_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("alt_text", sa.Text(), nullable=True),
        sa.Column("credit", sa.String(length=300), nullable=True),
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
            ["photograph_id"],
            ["photographs.id"],
            name=op.f("fk_post_assets_photograph_id_photographs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["social_posts.id"],
            name=op.f("fk_post_assets_post_id_social_posts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_post_assets")),
        sa.UniqueConstraint("post_id", "photograph_id", name="uq_post_assets_once"),
    )
    op.create_index(op.f("ix_post_assets_created_at"), "post_assets", ["created_at"], unique=False)
    op.create_index("ix_post_assets_order", "post_assets", ["post_id", "position"], unique=False)
    op.create_index(
        op.f("ix_post_assets_photograph_id"), "post_assets", ["photograph_id"], unique=False
    )
    op.create_index(op.f("ix_post_assets_post_id"), "post_assets", ["post_id"], unique=False)


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_post_assets_post_id"), table_name="post_assets")
    op.drop_index(op.f("ix_post_assets_photograph_id"), table_name="post_assets")
    op.drop_index("ix_post_assets_order", table_name="post_assets")
    op.drop_index(op.f("ix_post_assets_created_at"), table_name="post_assets")
    op.drop_table("post_assets")
    op.drop_index("ix_post_metrics_series", table_name="post_metrics")
    op.drop_index(op.f("ix_post_metrics_recorded_at"), table_name="post_metrics")
    op.drop_index(op.f("ix_post_metrics_post_id"), table_name="post_metrics")
    op.drop_index(op.f("ix_post_metrics_created_at"), table_name="post_metrics")
    op.drop_table("post_metrics")
    op.drop_index(op.f("ix_social_posts_title"), table_name="social_posts")
    op.drop_index("ix_social_posts_subject", table_name="social_posts")
    op.drop_index(op.f("ix_social_posts_status"), table_name="social_posts")
    op.drop_index(op.f("ix_social_posts_scheduled_for"), table_name="social_posts")
    op.drop_index(op.f("ix_social_posts_resource_id"), table_name="social_posts")
    op.drop_index(op.f("ix_social_posts_published_at"), table_name="social_posts")
    op.drop_index(op.f("ix_social_posts_project_id"), table_name="social_posts")
    op.drop_index(op.f("ix_social_posts_owner_id"), table_name="social_posts")
    op.drop_index(op.f("ix_social_posts_language"), table_name="social_posts")
    op.drop_index(op.f("ix_social_posts_kind"), table_name="social_posts")
    op.drop_index(op.f("ix_social_posts_is_public"), table_name="social_posts")
    op.drop_index(op.f("ix_social_posts_created_at"), table_name="social_posts")
    op.drop_index("ix_social_posts_calendar", table_name="social_posts")
    op.drop_index("ix_social_posts_account_status", table_name="social_posts")
    op.drop_index(op.f("ix_social_posts_account_id"), table_name="social_posts")
    op.drop_table("social_posts")
    op.drop_index(op.f("ix_social_accounts_platform"), table_name="social_accounts")
    op.drop_index(op.f("ix_social_accounts_owner_id"), table_name="social_accounts")
    op.drop_index(op.f("ix_social_accounts_manager_id"), table_name="social_accounts")
    op.drop_index(op.f("ix_social_accounts_is_public"), table_name="social_accounts")
    op.drop_index(op.f("ix_social_accounts_is_active"), table_name="social_accounts")
    op.drop_index(op.f("ix_social_accounts_created_at"), table_name="social_accounts")
    op.drop_table("social_accounts")

    # Autogenerate writes the CREATE TYPE and never the DROP, so a downgrade
    # leaves the enum types behind and the next upgrade fails on "type already
    # exists". `resource_type` is deliberately absent: it belongs to the rest
    # of the platform and dropping it here would take every other table's
    # column with it.
    for name in ("social_platform", "post_kind", "post_status"):
        op.execute(f"DROP TYPE IF EXISTS {name}")
