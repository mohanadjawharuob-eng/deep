"""The inventory module: equipment, consumables, calibration and kits.

Two ways of counting, kept apart deliberately. Equipment is tracked one row per
object, because "where is the Leica" is a question about a particular thing.
Consumables are tracked as a quantity with a ledger behind it, because nobody
tracks finds bag number 4,812 and a stock figure anybody can type over is a
stock figure nobody can defend.

Three constraints here are load-bearing rather than decorative:

- ``uq_equipment_one_open_checkout`` is a *partial* unique index on open loans.
  Two people each believing they have the theodolite is exactly the failure the
  register exists to prevent, and a check written in Python is a check that a
  second request racing the first walks straight past.
- ``ck_kit_template_lines_names_one_thing`` makes a packing-list line name one
  of a specific item, a consumable, or a category — never two, never none.
- ``ck_stock_movements_balance_not_negative`` refuses to record a shelf holding
  less than nothing.

Revision ID: 0014_inventory
Revises: 0013_equipment_resource
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0014_inventory"
down_revision: Union[str, None] = "0013_equipment_resource"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "consumables",
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("unit", sa.String(length=60), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("reorder_level", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("supplier", sa.String(length=200), nullable=True),
        sa.Column("supplier_reference", sa.String(length=120), nullable=True),
        sa.Column("unit_cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("storage_location_id", sa.UUID(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.CheckConstraint(
            "quantity >= 0", name=op.f("ck_consumables_ck_consumables_quantity_not_negative")
        ),
        sa.CheckConstraint(
            "reorder_level IS NULL OR reorder_level >= 0",
            name=op.f("ck_consumables_ck_consumables_reorder_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_consumables_owner_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["storage_location_id"],
            ["storage_locations.id"],
            name=op.f("fk_consumables_storage_location_id_storage_locations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consumables")),
    )
    op.create_index(op.f("ix_consumables_category"), "consumables", ["category"], unique=False)
    op.create_index(op.f("ix_consumables_code"), "consumables", ["code"], unique=True)
    op.create_index(op.f("ix_consumables_created_at"), "consumables", ["created_at"], unique=False)
    op.create_index(op.f("ix_consumables_expires_on"), "consumables", ["expires_on"], unique=False)
    op.create_index(op.f("ix_consumables_is_active"), "consumables", ["is_active"], unique=False)
    op.create_index(op.f("ix_consumables_is_public"), "consumables", ["is_public"], unique=False)
    op.create_index(op.f("ix_consumables_name"), "consumables", ["name"], unique=False)
    op.create_index(op.f("ix_consumables_owner_id"), "consumables", ["owner_id"], unique=False)
    op.create_index(
        op.f("ix_consumables_storage_location_id"),
        "consumables",
        ["storage_location_id"],
        unique=False,
    )
    op.create_table(
        "equipment",
        sa.Column("asset_number", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("manufacturer", sa.String(length=160), nullable=True),
        sa.Column("model", sa.String(length=160), nullable=True),
        sa.Column("serial_number", sa.String(length=160), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "available",
                "checked_out",
                "in_repair",
                "out_for_calibration",
                "missing",
                "retired",
                name="equipment_status",
            ),
            nullable=False,
        ),
        sa.Column("condition_notes", sa.Text(), nullable=True),
        sa.Column("purchased_on", sa.Date(), nullable=True),
        sa.Column("purchase_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("supplier", sa.String(length=200), nullable=True),
        sa.Column("warranty_until", sa.Date(), nullable=True),
        sa.Column("funding_source", sa.String(length=200), nullable=True),
        sa.Column("needs_calibration", sa.Boolean(), nullable=False),
        sa.Column("calibration_interval_days", sa.Integer(), nullable=True),
        sa.Column("calibration_due_on", sa.Date(), nullable=True),
        sa.Column("storage_location_id", sa.UUID(), nullable=True),
        sa.Column("public_token", sa.String(length=32), nullable=False),
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
        sa.CheckConstraint(
            "calibration_interval_days IS NULL OR calibration_interval_days > 0",
            name=op.f("ck_equipment_ck_equipment_calibration_interval_positive"),
        ),
        sa.CheckConstraint(
            "purchase_price IS NULL OR purchase_price >= 0",
            name=op.f("ck_equipment_ck_equipment_price_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_equipment_owner_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["storage_location_id"],
            ["storage_locations.id"],
            name=op.f("fk_equipment_storage_location_id_storage_locations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equipment")),
    )
    op.create_index(op.f("ix_equipment_asset_number"), "equipment", ["asset_number"], unique=True)
    op.create_index(
        op.f("ix_equipment_calibration_due_on"), "equipment", ["calibration_due_on"], unique=False
    )
    op.create_index(op.f("ix_equipment_category"), "equipment", ["category"], unique=False)
    op.create_index(op.f("ix_equipment_created_at"), "equipment", ["created_at"], unique=False)
    op.create_index(op.f("ix_equipment_is_public"), "equipment", ["is_public"], unique=False)
    op.create_index(op.f("ix_equipment_manufacturer"), "equipment", ["manufacturer"], unique=False)
    op.create_index(op.f("ix_equipment_name"), "equipment", ["name"], unique=False)
    op.create_index(op.f("ix_equipment_owner_id"), "equipment", ["owner_id"], unique=False)
    op.create_index(op.f("ix_equipment_public_token"), "equipment", ["public_token"], unique=True)
    op.create_index(
        op.f("ix_equipment_serial_number"), "equipment", ["serial_number"], unique=False
    )
    op.create_index(op.f("ix_equipment_status"), "equipment", ["status"], unique=False)
    op.create_index(
        "ix_equipment_status_category", "equipment", ["status", "category"], unique=False
    )
    op.create_index(
        op.f("ix_equipment_storage_location_id"), "equipment", ["storage_location_id"], unique=False
    )
    op.create_table(
        "kit_templates",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_kit_templates_owner_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kit_templates")),
        sa.UniqueConstraint("name", name="uq_kit_templates_name"),
    )
    op.create_index(
        op.f("ix_kit_templates_created_at"), "kit_templates", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_kit_templates_is_active"), "kit_templates", ["is_active"], unique=False
    )
    op.create_index(
        op.f("ix_kit_templates_is_public"), "kit_templates", ["is_public"], unique=False
    )
    op.create_index(op.f("ix_kit_templates_name"), "kit_templates", ["name"], unique=False)
    op.create_index(op.f("ix_kit_templates_owner_id"), "kit_templates", ["owner_id"], unique=False)
    op.create_table(
        "equipment_calibrations",
        sa.Column("equipment_id", sa.UUID(), nullable=False),
        sa.Column("performed_on", sa.Date(), nullable=False),
        sa.Column("performed_by", sa.String(length=200), nullable=True),
        sa.Column("certificate_number", sa.String(length=160), nullable=True),
        sa.Column(
            "result",
            sa.Enum("passed", "adjusted", "failed", name="calibration_result"),
            nullable=False,
        ),
        sa.Column("next_due_on", sa.Date(), nullable=True),
        sa.Column("cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by_id", sa.UUID(), nullable=True),
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
            ["equipment_id"],
            ["equipment.id"],
            name=op.f("fk_equipment_calibrations_equipment_id_equipment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_id"],
            ["users.id"],
            name=op.f("fk_equipment_calibrations_recorded_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equipment_calibrations")),
        sa.UniqueConstraint(
            "equipment_id", "performed_on", "certificate_number", name="uq_calibration_certificate"
        ),
    )
    op.create_index(
        "ix_calibrations_equipment_date",
        "equipment_calibrations",
        ["equipment_id", "performed_on"],
        unique=False,
    )
    op.create_index(
        op.f("ix_equipment_calibrations_certificate_number"),
        "equipment_calibrations",
        ["certificate_number"],
        unique=False,
    )
    op.create_index(
        op.f("ix_equipment_calibrations_created_at"),
        "equipment_calibrations",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_equipment_calibrations_equipment_id"),
        "equipment_calibrations",
        ["equipment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_equipment_calibrations_next_due_on"),
        "equipment_calibrations",
        ["next_due_on"],
        unique=False,
    )
    op.create_index(
        op.f("ix_equipment_calibrations_performed_on"),
        "equipment_calibrations",
        ["performed_on"],
        unique=False,
    )
    op.create_index(
        op.f("ix_equipment_calibrations_result"), "equipment_calibrations", ["result"], unique=False
    )
    op.create_table(
        "kit_template_lines",
        sa.Column("template_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("equipment_id", sa.UUID(), nullable=True),
        sa.Column("consumable_id", sa.UUID(), nullable=True),
        sa.Column("equipment_category", sa.String(length=120), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("is_optional", sa.Boolean(), nullable=False),
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
            "(CASE WHEN equipment_id IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN consumable_id IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN equipment_category IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name=op.f("ck_kit_template_lines_ck_kit_template_lines_names_one_thing"),
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name=op.f("ck_kit_template_lines_ck_kit_template_lines_quantity_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["consumable_id"],
            ["consumables.id"],
            name=op.f("fk_kit_template_lines_consumable_id_consumables"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["equipment.id"],
            name=op.f("fk_kit_template_lines_equipment_id_equipment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["kit_templates.id"],
            name=op.f("fk_kit_template_lines_template_id_kit_templates"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kit_template_lines")),
    )
    op.create_index(
        op.f("ix_kit_template_lines_consumable_id"),
        "kit_template_lines",
        ["consumable_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_kit_template_lines_created_at"), "kit_template_lines", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_kit_template_lines_equipment_category"),
        "kit_template_lines",
        ["equipment_category"],
        unique=False,
    )
    op.create_index(
        op.f("ix_kit_template_lines_equipment_id"),
        "kit_template_lines",
        ["equipment_id"],
        unique=False,
    )
    op.create_index(
        "ix_kit_template_lines_order",
        "kit_template_lines",
        ["template_id", "position"],
        unique=False,
    )
    op.create_index(
        op.f("ix_kit_template_lines_template_id"),
        "kit_template_lines",
        ["template_id"],
        unique=False,
    )
    op.create_table(
        "kits",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("template_id", sa.UUID(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("issued_to_label", sa.String(length=200), nullable=False),
        sa.Column("issued_to_id", sa.UUID(), nullable=True),
        sa.Column("destination", sa.String(length=300), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shortfalls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
            "returned_at IS NULL OR returned_at >= issued_at",
            name=op.f("ck_kits_ck_kits_returned_after_issued"),
        ),
        sa.ForeignKeyConstraint(
            ["issued_to_id"],
            ["users.id"],
            name=op.f("fk_kits_issued_to_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_kits_owner_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_kits_project_id_projects"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["kit_templates.id"],
            name=op.f("fk_kits_template_id_kit_templates"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kits")),
    )
    op.create_index(op.f("ix_kits_created_at"), "kits", ["created_at"], unique=False)
    op.create_index(op.f("ix_kits_due_on"), "kits", ["due_on"], unique=False)
    op.create_index(op.f("ix_kits_is_public"), "kits", ["is_public"], unique=False)
    op.create_index(op.f("ix_kits_issued_at"), "kits", ["issued_at"], unique=False)
    op.create_index(op.f("ix_kits_issued_to_id"), "kits", ["issued_to_id"], unique=False)
    op.create_index(op.f("ix_kits_name"), "kits", ["name"], unique=False)
    op.create_index(op.f("ix_kits_owner_id"), "kits", ["owner_id"], unique=False)
    op.create_index(op.f("ix_kits_project_id"), "kits", ["project_id"], unique=False)
    op.create_index("ix_kits_project_issued", "kits", ["project_id", "issued_at"], unique=False)
    op.create_index(op.f("ix_kits_returned_at"), "kits", ["returned_at"], unique=False)
    op.create_index(op.f("ix_kits_template_id"), "kits", ["template_id"], unique=False)
    op.create_table(
        "equipment_checkouts",
        sa.Column("equipment_id", sa.UUID(), nullable=False),
        sa.Column("borrower_id", sa.UUID(), nullable=True),
        sa.Column("borrower_label", sa.String(length=200), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("destination", sa.String(length=300), nullable=True),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("condition_out", sa.Text(), nullable=True),
        sa.Column("condition_in", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("issued_by_id", sa.UUID(), nullable=True),
        sa.Column("received_by_id", sa.UUID(), nullable=True),
        sa.Column("kit_id", sa.UUID(), nullable=True),
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
            "returned_at IS NULL OR returned_at >= taken_at",
            name=op.f("ck_equipment_checkouts_ck_checkouts_returned_after_taken"),
        ),
        sa.ForeignKeyConstraint(
            ["borrower_id"],
            ["users.id"],
            name=op.f("fk_equipment_checkouts_borrower_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["equipment.id"],
            name=op.f("fk_equipment_checkouts_equipment_id_equipment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["issued_by_id"],
            ["users.id"],
            name=op.f("fk_equipment_checkouts_issued_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["kit_id"],
            ["kits.id"],
            name=op.f("fk_equipment_checkouts_kit_id_kits"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_equipment_checkouts_project_id_projects"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["received_by_id"],
            ["users.id"],
            name=op.f("fk_equipment_checkouts_received_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equipment_checkouts")),
    )
    op.create_index(
        "ix_checkouts_history", "equipment_checkouts", ["equipment_id", "taken_at"], unique=False
    )
    op.create_index(
        op.f("ix_equipment_checkouts_borrower_id"),
        "equipment_checkouts",
        ["borrower_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_equipment_checkouts_created_at"),
        "equipment_checkouts",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_equipment_checkouts_due_on"), "equipment_checkouts", ["due_on"], unique=False
    )
    op.create_index(
        op.f("ix_equipment_checkouts_equipment_id"),
        "equipment_checkouts",
        ["equipment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_equipment_checkouts_kit_id"), "equipment_checkouts", ["kit_id"], unique=False
    )
    op.create_index(
        op.f("ix_equipment_checkouts_project_id"),
        "equipment_checkouts",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_equipment_checkouts_returned_at"),
        "equipment_checkouts",
        ["returned_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_equipment_checkouts_taken_at"), "equipment_checkouts", ["taken_at"], unique=False
    )
    op.create_index(
        "uq_equipment_one_open_checkout",
        "equipment_checkouts",
        ["equipment_id"],
        unique=True,
        postgresql_where=sa.text("returned_at IS NULL"),
    )
    op.create_table(
        "stock_movements",
        sa.Column("consumable_id", sa.UUID(), nullable=False),
        sa.Column("change", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("balance_after", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column(
            "reason",
            sa.Enum(
                "received",
                "issued",
                "returned",
                "used",
                "damaged",
                "expired",
                "stocktake",
                "other",
                name="stock_reason",
            ),
            nullable=False,
        ),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("issued_to_label", sa.String(length=200), nullable=True),
        sa.Column("kit_id", sa.UUID(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by_id", sa.UUID(), nullable=True),
        sa.Column("recorded_by_label", sa.String(length=200), nullable=True),
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
            "balance_after >= 0",
            name=op.f("ck_stock_movements_ck_stock_movements_balance_not_negative"),
        ),
        sa.CheckConstraint(
            "change <> 0", name=op.f("ck_stock_movements_ck_stock_movements_change_not_zero")
        ),
        sa.ForeignKeyConstraint(
            ["consumable_id"],
            ["consumables.id"],
            name=op.f("fk_stock_movements_consumable_id_consumables"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["kit_id"],
            ["kits.id"],
            name=op.f("fk_stock_movements_kit_id_kits"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_stock_movements_project_id_projects"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_id"],
            ["users.id"],
            name=op.f("fk_stock_movements_recorded_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_movements")),
    )
    op.create_index(
        op.f("ix_stock_movements_consumable_id"), "stock_movements", ["consumable_id"], unique=False
    )
    op.create_index(
        "ix_stock_movements_consumable_time",
        "stock_movements",
        ["consumable_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_stock_movements_created_at"), "stock_movements", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_stock_movements_kit_id"), "stock_movements", ["kit_id"], unique=False)
    op.create_index(
        op.f("ix_stock_movements_occurred_at"), "stock_movements", ["occurred_at"], unique=False
    )
    op.create_index(
        op.f("ix_stock_movements_project_id"), "stock_movements", ["project_id"], unique=False
    )
    op.create_index(op.f("ix_stock_movements_reason"), "stock_movements", ["reason"], unique=False)


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_stock_movements_reason"), table_name="stock_movements")
    op.drop_index(op.f("ix_stock_movements_project_id"), table_name="stock_movements")
    op.drop_index(op.f("ix_stock_movements_occurred_at"), table_name="stock_movements")
    op.drop_index(op.f("ix_stock_movements_kit_id"), table_name="stock_movements")
    op.drop_index(op.f("ix_stock_movements_created_at"), table_name="stock_movements")
    op.drop_index("ix_stock_movements_consumable_time", table_name="stock_movements")
    op.drop_index(op.f("ix_stock_movements_consumable_id"), table_name="stock_movements")
    op.drop_table("stock_movements")
    op.drop_index(
        "uq_equipment_one_open_checkout",
        table_name="equipment_checkouts",
        postgresql_where=sa.text("returned_at IS NULL"),
    )
    op.drop_index(op.f("ix_equipment_checkouts_taken_at"), table_name="equipment_checkouts")
    op.drop_index(op.f("ix_equipment_checkouts_returned_at"), table_name="equipment_checkouts")
    op.drop_index(op.f("ix_equipment_checkouts_project_id"), table_name="equipment_checkouts")
    op.drop_index(op.f("ix_equipment_checkouts_kit_id"), table_name="equipment_checkouts")
    op.drop_index(op.f("ix_equipment_checkouts_equipment_id"), table_name="equipment_checkouts")
    op.drop_index(op.f("ix_equipment_checkouts_due_on"), table_name="equipment_checkouts")
    op.drop_index(op.f("ix_equipment_checkouts_created_at"), table_name="equipment_checkouts")
    op.drop_index(op.f("ix_equipment_checkouts_borrower_id"), table_name="equipment_checkouts")
    op.drop_index("ix_checkouts_history", table_name="equipment_checkouts")
    op.drop_table("equipment_checkouts")
    op.drop_index(op.f("ix_kits_template_id"), table_name="kits")
    op.drop_index(op.f("ix_kits_returned_at"), table_name="kits")
    op.drop_index("ix_kits_project_issued", table_name="kits")
    op.drop_index(op.f("ix_kits_project_id"), table_name="kits")
    op.drop_index(op.f("ix_kits_owner_id"), table_name="kits")
    op.drop_index(op.f("ix_kits_name"), table_name="kits")
    op.drop_index(op.f("ix_kits_issued_to_id"), table_name="kits")
    op.drop_index(op.f("ix_kits_issued_at"), table_name="kits")
    op.drop_index(op.f("ix_kits_is_public"), table_name="kits")
    op.drop_index(op.f("ix_kits_due_on"), table_name="kits")
    op.drop_index(op.f("ix_kits_created_at"), table_name="kits")
    op.drop_table("kits")
    op.drop_index(op.f("ix_kit_template_lines_template_id"), table_name="kit_template_lines")
    op.drop_index("ix_kit_template_lines_order", table_name="kit_template_lines")
    op.drop_index(op.f("ix_kit_template_lines_equipment_id"), table_name="kit_template_lines")
    op.drop_index(op.f("ix_kit_template_lines_equipment_category"), table_name="kit_template_lines")
    op.drop_index(op.f("ix_kit_template_lines_created_at"), table_name="kit_template_lines")
    op.drop_index(op.f("ix_kit_template_lines_consumable_id"), table_name="kit_template_lines")
    op.drop_table("kit_template_lines")
    op.drop_index(op.f("ix_equipment_calibrations_result"), table_name="equipment_calibrations")
    op.drop_index(
        op.f("ix_equipment_calibrations_performed_on"), table_name="equipment_calibrations"
    )
    op.drop_index(
        op.f("ix_equipment_calibrations_next_due_on"), table_name="equipment_calibrations"
    )
    op.drop_index(
        op.f("ix_equipment_calibrations_equipment_id"), table_name="equipment_calibrations"
    )
    op.drop_index(op.f("ix_equipment_calibrations_created_at"), table_name="equipment_calibrations")
    op.drop_index(
        op.f("ix_equipment_calibrations_certificate_number"), table_name="equipment_calibrations"
    )
    op.drop_index("ix_calibrations_equipment_date", table_name="equipment_calibrations")
    op.drop_table("equipment_calibrations")
    op.drop_index(op.f("ix_kit_templates_owner_id"), table_name="kit_templates")
    op.drop_index(op.f("ix_kit_templates_name"), table_name="kit_templates")
    op.drop_index(op.f("ix_kit_templates_is_public"), table_name="kit_templates")
    op.drop_index(op.f("ix_kit_templates_is_active"), table_name="kit_templates")
    op.drop_index(op.f("ix_kit_templates_created_at"), table_name="kit_templates")
    op.drop_table("kit_templates")
    op.drop_index(op.f("ix_equipment_storage_location_id"), table_name="equipment")
    op.drop_index("ix_equipment_status_category", table_name="equipment")
    op.drop_index(op.f("ix_equipment_status"), table_name="equipment")
    op.drop_index(op.f("ix_equipment_serial_number"), table_name="equipment")
    op.drop_index(op.f("ix_equipment_public_token"), table_name="equipment")
    op.drop_index(op.f("ix_equipment_owner_id"), table_name="equipment")
    op.drop_index(op.f("ix_equipment_name"), table_name="equipment")
    op.drop_index(op.f("ix_equipment_manufacturer"), table_name="equipment")
    op.drop_index(op.f("ix_equipment_is_public"), table_name="equipment")
    op.drop_index(op.f("ix_equipment_created_at"), table_name="equipment")
    op.drop_index(op.f("ix_equipment_category"), table_name="equipment")
    op.drop_index(op.f("ix_equipment_calibration_due_on"), table_name="equipment")
    op.drop_index(op.f("ix_equipment_asset_number"), table_name="equipment")
    op.drop_table("equipment")
    op.drop_index(op.f("ix_consumables_storage_location_id"), table_name="consumables")
    op.drop_index(op.f("ix_consumables_owner_id"), table_name="consumables")
    op.drop_index(op.f("ix_consumables_name"), table_name="consumables")
    op.drop_index(op.f("ix_consumables_is_public"), table_name="consumables")
    op.drop_index(op.f("ix_consumables_is_active"), table_name="consumables")
    op.drop_index(op.f("ix_consumables_expires_on"), table_name="consumables")
    op.drop_index(op.f("ix_consumables_created_at"), table_name="consumables")
    op.drop_index(op.f("ix_consumables_code"), table_name="consumables")
    op.drop_index(op.f("ix_consumables_category"), table_name="consumables")
    op.drop_table("consumables")

    # Autogenerate writes the CREATE TYPE but never the DROP, so a downgrade
    # leaves the enum types behind and the *next* upgrade fails on "type
    # already exists". Nothing warns about it until somebody is rolling back a
    # bad deploy at an awkward hour, which is the worst moment to find out.
    for name in ("equipment_status", "calibration_result", "stock_reason"):
        op.execute(f"DROP TYPE IF EXISTS {name}")
