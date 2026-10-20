"""Live power rebalancing: site limit and simulated store load per station, device
capabilities, applied/target power and reason per session, event data and a decision log.

Additive only: with ``rebalance_enabled`` false (default) nothing changes.

Revision ID: b7d2f4a91c36
Revises: d1e8f3a2c7b5
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "b7d2f4a91c36"
down_revision = "d1e8f3a2c7b5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stations", sa.Column("site_limit_kw", sa.Numeric(10, 3)))
    op.add_column("stations", sa.Column("building_load_kw", sa.Numeric(10, 3)))
    op.add_column("stations", sa.Column("building_load_source", sa.String(20)))
    op.add_column("stations", sa.Column("building_load_updated_at", sa.DateTime(timezone=True)))
    op.add_column(
        "stations", sa.Column("rebalance_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false"))
    )
    op.create_check_constraint("station_site_limit_positive", "stations", "site_limit_kw IS NULL OR site_limit_kw > 0")
    op.create_check_constraint(
        "station_building_load_range", "stations", "building_load_kw IS NULL OR building_load_kw >= 0"
    )
    op.create_check_constraint(
        "station_building_load_source", "stations",
        "building_load_source IS NULL OR building_load_source IN ('simulated')",
    )

    op.add_column(
        "devices", sa.Column("capabilities", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb"))
    )
    op.add_column("devices", sa.Column("charger", JSONB()))

    for name, column in (
        ("requested_power_kw", sa.Numeric(10, 3)),
        ("target_power_kw", sa.Numeric(10, 3)),
        ("applied_power_kw", sa.Numeric(10, 3)),
        ("power_state", sa.String(20)),
        ("power_reason", sa.String(300)),
        ("power_reason_short", sa.String(60)),
        ("power_reason_code", sa.String(30)),
        ("power_decision_id", sa.BigInteger()),
    ):
        op.add_column("charging_sessions", sa.Column(name, column))
    op.create_check_constraint(
        "session_power_state", "charging_sessions",
        "power_state IS NULL OR power_state IN ('applied','reducing','raising','waiting','paused','fixed')",
    )
    op.create_check_constraint(
        "session_applied_power_range", "charging_sessions", "applied_power_kw IS NULL OR applied_power_kw >= 0"
    )

    op.add_column("session_events", sa.Column("data", JSONB()))

    op.create_table(
        "power_decisions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("station_id", UUID(), sa.ForeignKey("stations.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger", sa.String(40), nullable=False),
        sa.Column("inputs", JSONB(), nullable=False),
        sa.Column("available_kw", sa.Numeric(10, 3)),
        sa.Column("exceeded_kw", sa.Numeric(10, 3), nullable=False),
        sa.Column("summary", sa.String(300), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_power_decisions_station_created", "power_decisions", ["station_id", "created_at"])
    op.execute("ALTER TABLE power_decisions ENABLE ROW LEVEL SECURITY")
    op.execute(
        """DO $$ BEGIN
        REVOKE ALL ON TABLE power_decisions FROM PUBLIC;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
          REVOKE ALL ON TABLE power_decisions FROM anon;
        END IF;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
          REVOKE ALL ON TABLE power_decisions FROM authenticated;
        END IF;
        END $$"""
    )
    op.execute("GRANT SELECT, INSERT ON TABLE power_decisions TO chargegrid_api")
    op.execute("GRANT USAGE ON SEQUENCE power_decisions_id_seq TO chargegrid_api")
    op.execute("CREATE POLICY api_only ON power_decisions FOR ALL TO chargegrid_api USING (true) WITH CHECK (true)")


def downgrade():
    op.drop_index("ix_power_decisions_station_created", table_name="power_decisions")
    op.drop_table("power_decisions")
    op.drop_column("session_events", "data")
    op.drop_constraint("session_applied_power_range", "charging_sessions", type_="check")
    op.drop_constraint("session_power_state", "charging_sessions", type_="check")
    for name in ("power_decision_id", "power_reason_code", "power_reason_short", "power_reason", "power_state",
                 "applied_power_kw", "target_power_kw", "requested_power_kw"):
        op.drop_column("charging_sessions", name)
    op.drop_column("devices", "charger")
    op.drop_column("devices", "capabilities")
    op.drop_constraint("station_building_load_source", "stations", type_="check")
    op.drop_constraint("station_building_load_range", "stations", type_="check")
    op.drop_constraint("station_site_limit_positive", "stations", type_="check")
    for name in ("rebalance_enabled", "building_load_updated_at", "building_load_source", "building_load_kw",
                 "site_limit_kw"):
        op.drop_column("stations", name)
