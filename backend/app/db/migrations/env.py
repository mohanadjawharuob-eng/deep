"""Alembic environment.

The connection URL and the target metadata both come from the application, so
migrations always run against the same schema definition the app uses.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from geoalchemy2 import alembic_helpers
from sqlalchemy import engine_from_config, pool

from app.core.config import settings

# Importing the models package registers every table on the metadata.
from app.models import Base  # noqa: F401  (imported for its side effects)

config = context.config
config.set_main_option("sqlalchemy.url", settings.sqlalchemy_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Keep PostGIS's own bookkeeping out of our migrations.

    Installing the extension creates ``spatial_ref_sys`` and a set of views;
    autogenerate would otherwise try to drop them on every run.
    """
    if type_ == "table" and name in {"spatial_ref_sys", "geography_columns", "geometry_columns"}:
        return False
    # GeoAlchemy2 manages its own indexes on geometry columns.
    return alembic_helpers.include_object(obj, name, type_, reflected, compare_to)


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting — used to review a migration."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
        render_item=alembic_helpers.render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
            compare_server_default=True,
            render_item=alembic_helpers.render_item,
            process_revision_directives=alembic_helpers.writer,
            # Each migration commits on its own. PostgreSQL refuses to *use* a
            # value added to an enum in the same transaction that added it, so
            # a single transaction spanning every revision would make it
            # impossible to add an enum value in one migration and backfill
            # with it in the next.
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
