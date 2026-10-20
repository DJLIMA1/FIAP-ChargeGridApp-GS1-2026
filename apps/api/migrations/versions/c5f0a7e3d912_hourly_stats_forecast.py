"""Durable hourly aggregates per connector for occupancy/energy tracking and forecasting.

``connector_hourly_stats`` keeps busy seconds and energy per connector and UTC hour
(``chargegrid_core.forecast.aggregate``), so the hourly history survives the 7-day
telemetry cleanup. ``aggregate_watermarks`` records how far the rollup has closed;
``tools/maintenance.py`` never deletes telemetry newer than that mark. Additive only.

Revision ID: c5f0a7e3d912
Revises: d1e8f3a2c7b5
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "c5f0a7e3d912"
down_revision = "d1e8f3a2c7b5"
branch_labels = None
depends_on = None

TABLES = ("connector_hourly_stats", "aggregate_watermarks")


def upgrade():
    op.create_table(
        "connector_hourly_stats",
        sa.Column("connector_id", UUID(), sa.ForeignKey("connectors.id"), primary_key=True),
        sa.Column("hour_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("origin", sa.String(12), primary_key=True),
        sa.Column("busy_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("energy_wh", sa.Numeric(16, 3), nullable=False, server_default="0"),
        sa.Column("energy_basis", sa.String(16), nullable=False),
        sa.Column("sessions_started", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_power_w", sa.Numeric(12, 1)),
        sa.Column("generator", sa.String(20)),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("origin IN ('measured', 'simulated', 'synthetic')", name="hourly_stats_origin"),
        sa.CheckConstraint("energy_basis IN ('telemetry', 'session_spread', 'synthetic')", name="hourly_stats_basis"),
        sa.CheckConstraint("busy_seconds BETWEEN 0 AND 3600 AND energy_wh >= 0 AND sessions_started >= 0",
                           name="hourly_stats_ranges"),
        sa.CheckConstraint("mod(CAST(EXTRACT(EPOCH FROM hour_start) AS bigint), 3600) = 0",
                           name="hourly_stats_hour_aligned"),
    )
    op.create_index("ix_connector_hourly_stats_hour", "connector_hourly_stats", ["hour_start"])
    op.create_table(
        "aggregate_watermarks",
        sa.Column("name", sa.String(50), primary_key=True),
        sa.Column("rolled_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO chargegrid_api")
        op.execute(f"CREATE POLICY api_only ON {table} FOR ALL TO chargegrid_api USING (true) WITH CHECK (true)")
        op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")
    op.execute(
        f"""DO $$ DECLARE table_name text; BEGIN
        FOREACH table_name IN ARRAY string_to_array('{",".join(TABLES)}', ',') LOOP
          IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
            EXECUTE 'REVOKE ALL ON TABLE ' || quote_ident(table_name) || ' FROM anon';
          END IF;
          IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
            EXECUTE 'REVOKE ALL ON TABLE ' || quote_ident(table_name) || ' FROM authenticated';
          END IF;
        END LOOP; END $$"""
    )


def downgrade():
    op.drop_table("aggregate_watermarks")
    op.drop_index("ix_connector_hourly_stats_hour", table_name="connector_hourly_stats")
    op.drop_table("connector_hourly_stats")
