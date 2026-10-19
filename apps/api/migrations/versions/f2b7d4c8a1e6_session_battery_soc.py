"""Car battery on charging sessions: initial SoC, usable capacity and SoC source.

Revision ID: f2b7d4c8a1e6
Revises: b8e4f2a6c913
"""

import sqlalchemy as sa
from alembic import op

revision = "f2b7d4c8a1e6"
down_revision = "b8e4f2a6c913"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("charging_sessions", sa.Column("start_soc_percent", sa.Numeric(5, 2), nullable=True))
    op.add_column("charging_sessions", sa.Column("battery_kwh", sa.Numeric(6, 2), nullable=True))
    op.add_column("charging_sessions", sa.Column("soc_source", sa.String(20), nullable=True))
    op.create_check_constraint(
        "session_start_soc_range", "charging_sessions",
        "start_soc_percent IS NULL OR start_soc_percent BETWEEN 0 AND 100",
    )
    op.create_check_constraint(
        "session_battery_kwh_range", "charging_sessions", "battery_kwh IS NULL OR battery_kwh BETWEEN 5 AND 250"
    )
    op.create_check_constraint(
        "session_soc_source", "charging_sessions", "soc_source IS NULL OR soc_source IN ('simulated', 'phone')"
    )


def downgrade():
    op.drop_constraint("session_soc_source", "charging_sessions", type_="check")
    op.drop_constraint("session_battery_kwh_range", "charging_sessions", type_="check")
    op.drop_constraint("session_start_soc_range", "charging_sessions", type_="check")
    op.drop_column("charging_sessions", "soc_source")
    op.drop_column("charging_sessions", "battery_kwh")
    op.drop_column("charging_sessions", "start_soc_percent")
