"""Revoke Supabase client roles from tables created after the initial schema.

The initial migration revokes ``PUBLIC``, ``anon`` and ``authenticated`` from
every table, so only ``chargegrid_api`` (the backend) can touch them. Later
tables (device claims, session events, driver profiles and AI usage) only got
RLS. On Supabase, default privileges grant ALL (including TRUNCATE, which RLS
does not cover) on new ``public`` tables to ``anon``/``authenticated``; revoke
them so every table follows the same backend-only rule.

Revision ID: b8e4f2a6c913
Revises: a71c3e5d9b20
"""

from alembic import op

revision = "b8e4f2a6c913"
down_revision = "a71c3e5d9b20"
branch_labels = None
depends_on = None

TABLES = ("device_claims", "session_events", "driver_profiles", "ai_usage")


def upgrade():
    op.execute(
        f"""DO $$ DECLARE table_name text; BEGIN
        FOREACH table_name IN ARRAY string_to_array('{",".join(TABLES)}', ',') LOOP
          EXECUTE format('REVOKE ALL ON TABLE %I FROM PUBLIC', table_name);
          IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
            EXECUTE format('REVOKE ALL ON TABLE %I FROM anon', table_name);
          END IF;
          IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
            EXECUTE format('REVOKE ALL ON TABLE %I FROM authenticated', table_name);
          END IF;
        END LOOP; END $$"""
    )


def downgrade():
    # Re-granting client roles would reopen the tables; the backend keeps its own grants.
    pass
