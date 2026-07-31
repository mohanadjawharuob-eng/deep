-- Runs once, when the data directory is first created.
--
-- The Alembic migration ``0001_extensions`` creates these too, so this file is
-- belt and braces: it means a database restored from a plain dump, or inspected
-- before the API has ever started, already has PostGIS available.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS btree_gin;

-- Timings for the slowest queries end up in the log, which is how index gaps
-- get noticed on a real dataset rather than in review. The database name is
-- not a psql variable here, so it is interpolated from ``current_database()``.
DO $$
BEGIN
    EXECUTE format(
        'ALTER DATABASE %I SET log_min_duration_statement = %L',
        current_database(), '1000ms'
    );
END
$$;
