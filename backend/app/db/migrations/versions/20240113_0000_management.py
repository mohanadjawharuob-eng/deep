"""The management module: budgets, expenses, tasks and the calendar.

Money is the part with a rule in it. A budget's spent, committed and available
figures are **not** columns here — they are summed from the expenses on read,
because a stored total is a total that can drift from the rows behind it, and
money is the last place to accept that.

Two constraints carry weight:

- ``ck_expenses_amount_positive`` refuses zero and negative lines. A negative
  expense is a refund pretending to be spending, and it makes every category
  breakdown quietly wrong.
- ``ck_expenses_paid_after_spent`` refuses an invoice paid before it was
  incurred.

Revision ID: 0015_management
Revises: 0014_inventory
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0015_management"
down_revision: Union[str, None] = "0014_inventory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=250), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("funder", sa.String(length=250), nullable=True),
        sa.Column("grant_reference", sa.String(length=160), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "active", "closed", "cancelled", name="budget_status"),
            nullable=False,
        ),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("manager_id", sa.UUID(), nullable=True),
        sa.Column("manager_label", sa.String(length=200), nullable=True),
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
        sa.CheckConstraint("amount >= 0", name=op.f("ck_budgets_ck_budgets_amount_not_negative")),
        sa.CheckConstraint(
            "starts_on IS NULL OR ends_on IS NULL OR ends_on >= starts_on",
            name=op.f("ck_budgets_ck_budgets_ends_after_starts"),
        ),
        sa.ForeignKeyConstraint(
            ["manager_id"],
            ["users.id"],
            name=op.f("fk_budgets_manager_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_budgets_owner_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_budgets_project_id_projects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budgets")),
    )
    op.create_index(op.f("ix_budgets_code"), "budgets", ["code"], unique=True)
    op.create_index(op.f("ix_budgets_created_at"), "budgets", ["created_at"], unique=False)
    op.create_index(op.f("ix_budgets_ends_on"), "budgets", ["ends_on"], unique=False)
    op.create_index(op.f("ix_budgets_funder"), "budgets", ["funder"], unique=False)
    op.create_index(op.f("ix_budgets_is_public"), "budgets", ["is_public"], unique=False)
    op.create_index(op.f("ix_budgets_manager_id"), "budgets", ["manager_id"], unique=False)
    op.create_index(op.f("ix_budgets_name"), "budgets", ["name"], unique=False)
    op.create_index(op.f("ix_budgets_owner_id"), "budgets", ["owner_id"], unique=False)
    op.create_index(op.f("ix_budgets_project_id"), "budgets", ["project_id"], unique=False)
    op.create_index(op.f("ix_budgets_starts_on"), "budgets", ["starts_on"], unique=False)
    op.create_index(op.f("ix_budgets_status"), "budgets", ["status"], unique=False)
    op.create_index("ix_budgets_status_project", "budgets", ["status", "project_id"], unique=False)
    op.create_table(
        "tasks",
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("todo", "in_progress", "blocked", "done", "cancelled", name="task_status"),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum("low", "normal", "high", "urgent", name="task_priority"),
            nullable=False,
        ),
        sa.Column("assignee_id", sa.UUID(), nullable=True),
        sa.Column("assignee_label", sa.String(length=200), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("resource_type", sa.String(length=40), nullable=True),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by_id", sa.UUID(), nullable=True),
        sa.Column("position", sa.Numeric(precision=12, scale=4), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["users.id"],
            name=op.f("fk_tasks_assignee_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["completed_by_id"],
            ["users.id"],
            name=op.f("fk_tasks_completed_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_tasks_owner_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_tasks_project_id_projects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(op.f("ix_tasks_assignee_id"), "tasks", ["assignee_id"], unique=False)
    op.create_index("ix_tasks_assignee_status", "tasks", ["assignee_id", "status"], unique=False)
    op.create_index(op.f("ix_tasks_completed_at"), "tasks", ["completed_at"], unique=False)
    op.create_index(op.f("ix_tasks_created_at"), "tasks", ["created_at"], unique=False)
    op.create_index("ix_tasks_due", "tasks", ["status", "due_on"], unique=False)
    op.create_index(op.f("ix_tasks_due_on"), "tasks", ["due_on"], unique=False)
    op.create_index(op.f("ix_tasks_is_public"), "tasks", ["is_public"], unique=False)
    op.create_index(op.f("ix_tasks_owner_id"), "tasks", ["owner_id"], unique=False)
    op.create_index(op.f("ix_tasks_priority"), "tasks", ["priority"], unique=False)
    op.create_index(op.f("ix_tasks_project_id"), "tasks", ["project_id"], unique=False)
    op.create_index("ix_tasks_project_status", "tasks", ["project_id", "status"], unique=False)
    op.create_index(op.f("ix_tasks_resource_id"), "tasks", ["resource_id"], unique=False)
    op.create_index(op.f("ix_tasks_status"), "tasks", ["status"], unique=False)
    op.create_index(op.f("ix_tasks_title"), "tasks", ["title"], unique=False)
    op.create_table(
        "calendar_events",
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=80), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("all_day", sa.Boolean(), nullable=False),
        sa.Column("location", sa.String(length=300), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("budget_id", sa.UUID(), nullable=True),
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
            "ends_at IS NULL OR ends_at >= starts_at",
            name=op.f("ck_calendar_events_ck_events_ends_after_starts"),
        ),
        sa.ForeignKeyConstraint(
            ["budget_id"],
            ["budgets.id"],
            name=op.f("fk_calendar_events_budget_id_budgets"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_calendar_events_owner_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_calendar_events_project_id_projects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calendar_events")),
    )
    op.create_index(
        op.f("ix_calendar_events_budget_id"), "calendar_events", ["budget_id"], unique=False
    )
    op.create_index(
        op.f("ix_calendar_events_created_at"), "calendar_events", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_calendar_events_ends_at"), "calendar_events", ["ends_at"], unique=False
    )
    op.create_index(
        op.f("ix_calendar_events_is_public"), "calendar_events", ["is_public"], unique=False
    )
    op.create_index(op.f("ix_calendar_events_kind"), "calendar_events", ["kind"], unique=False)
    op.create_index(
        op.f("ix_calendar_events_owner_id"), "calendar_events", ["owner_id"], unique=False
    )
    op.create_index(
        op.f("ix_calendar_events_project_id"), "calendar_events", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_calendar_events_starts_at"), "calendar_events", ["starts_at"], unique=False
    )
    op.create_index(op.f("ix_calendar_events_title"), "calendar_events", ["title"], unique=False)
    op.create_index("ix_events_span", "calendar_events", ["starts_at", "ends_at"], unique=False)
    op.create_table(
        "expenses",
        sa.Column("budget_id", sa.UUID(), nullable=False),
        sa.Column("description", sa.String(length=400), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "fieldwork",
                "travel",
                "accommodation",
                "salaries",
                "equipment",
                "consumables",
                "analysis",
                "conservation",
                "publication",
                "permits",
                "overheads",
                "other",
                name="expense_category",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("planned", "committed", "paid", "cancelled", name="expense_status"),
            nullable=False,
        ),
        sa.Column("spent_on", sa.Date(), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("supplier", sa.String(length=250), nullable=True),
        sa.Column("reference", sa.String(length=160), nullable=True),
        sa.Column("paid_by_label", sa.String(length=200), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
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
        sa.CheckConstraint("amount > 0", name=op.f("ck_expenses_ck_expenses_amount_positive")),
        sa.CheckConstraint(
            "paid_on IS NULL OR paid_on >= spent_on",
            name=op.f("ck_expenses_ck_expenses_paid_after_spent"),
        ),
        sa.ForeignKeyConstraint(
            ["budget_id"],
            ["budgets.id"],
            name=op.f("fk_expenses_budget_id_budgets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_expenses_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_expenses_owner_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_expenses_project_id_projects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expenses")),
    )
    op.create_index(op.f("ix_expenses_budget_id"), "expenses", ["budget_id"], unique=False)
    op.create_index("ix_expenses_budget_status", "expenses", ["budget_id", "status"], unique=False)
    op.create_index(op.f("ix_expenses_category"), "expenses", ["category"], unique=False)
    op.create_index(op.f("ix_expenses_created_at"), "expenses", ["created_at"], unique=False)
    op.create_index(op.f("ix_expenses_document_id"), "expenses", ["document_id"], unique=False)
    op.create_index(op.f("ix_expenses_is_public"), "expenses", ["is_public"], unique=False)
    op.create_index(op.f("ix_expenses_owner_id"), "expenses", ["owner_id"], unique=False)
    op.create_index(op.f("ix_expenses_paid_on"), "expenses", ["paid_on"], unique=False)
    op.create_index(op.f("ix_expenses_project_id"), "expenses", ["project_id"], unique=False)
    op.create_index(op.f("ix_expenses_reference"), "expenses", ["reference"], unique=False)
    op.create_index(
        "ix_expenses_reporting", "expenses", ["budget_id", "category", "spent_on"], unique=False
    )
    op.create_index(op.f("ix_expenses_spent_on"), "expenses", ["spent_on"], unique=False)
    op.create_index(op.f("ix_expenses_status"), "expenses", ["status"], unique=False)
    op.create_index(op.f("ix_expenses_supplier"), "expenses", ["supplier"], unique=False)


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_expenses_supplier"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_status"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_spent_on"), table_name="expenses")
    op.drop_index("ix_expenses_reporting", table_name="expenses")
    op.drop_index(op.f("ix_expenses_reference"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_project_id"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_paid_on"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_owner_id"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_is_public"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_document_id"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_created_at"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_category"), table_name="expenses")
    op.drop_index("ix_expenses_budget_status", table_name="expenses")
    op.drop_index(op.f("ix_expenses_budget_id"), table_name="expenses")
    op.drop_table("expenses")
    op.drop_index("ix_events_span", table_name="calendar_events")
    op.drop_index(op.f("ix_calendar_events_title"), table_name="calendar_events")
    op.drop_index(op.f("ix_calendar_events_starts_at"), table_name="calendar_events")
    op.drop_index(op.f("ix_calendar_events_project_id"), table_name="calendar_events")
    op.drop_index(op.f("ix_calendar_events_owner_id"), table_name="calendar_events")
    op.drop_index(op.f("ix_calendar_events_kind"), table_name="calendar_events")
    op.drop_index(op.f("ix_calendar_events_is_public"), table_name="calendar_events")
    op.drop_index(op.f("ix_calendar_events_ends_at"), table_name="calendar_events")
    op.drop_index(op.f("ix_calendar_events_created_at"), table_name="calendar_events")
    op.drop_index(op.f("ix_calendar_events_budget_id"), table_name="calendar_events")
    op.drop_table("calendar_events")
    op.drop_index(op.f("ix_tasks_title"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_status"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_resource_id"), table_name="tasks")
    op.drop_index("ix_tasks_project_status", table_name="tasks")
    op.drop_index(op.f("ix_tasks_project_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_priority"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_owner_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_is_public"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_due_on"), table_name="tasks")
    op.drop_index("ix_tasks_due", table_name="tasks")
    op.drop_index(op.f("ix_tasks_created_at"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_completed_at"), table_name="tasks")
    op.drop_index("ix_tasks_assignee_status", table_name="tasks")
    op.drop_index(op.f("ix_tasks_assignee_id"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_budgets_status_project", table_name="budgets")
    op.drop_index(op.f("ix_budgets_status"), table_name="budgets")
    op.drop_index(op.f("ix_budgets_starts_on"), table_name="budgets")
    op.drop_index(op.f("ix_budgets_project_id"), table_name="budgets")
    op.drop_index(op.f("ix_budgets_owner_id"), table_name="budgets")
    op.drop_index(op.f("ix_budgets_name"), table_name="budgets")
    op.drop_index(op.f("ix_budgets_manager_id"), table_name="budgets")
    op.drop_index(op.f("ix_budgets_is_public"), table_name="budgets")
    op.drop_index(op.f("ix_budgets_funder"), table_name="budgets")
    op.drop_index(op.f("ix_budgets_ends_on"), table_name="budgets")
    op.drop_index(op.f("ix_budgets_created_at"), table_name="budgets")
    op.drop_index(op.f("ix_budgets_code"), table_name="budgets")
    op.drop_table("budgets")

    # Autogenerate writes the CREATE TYPE and never the DROP, so a downgrade
    # leaves the enum types behind and the *next* upgrade fails on "type
    # already exists" — found the same way as in 0014, by actually running the
    # round trip rather than trusting that a generated downgrade reverses.
    for name in (
        "budget_status",
        "expense_status",
        "expense_category",
        "task_status",
        "task_priority",
    ):
        op.execute(f"DROP TYPE IF EXISTS {name}")
