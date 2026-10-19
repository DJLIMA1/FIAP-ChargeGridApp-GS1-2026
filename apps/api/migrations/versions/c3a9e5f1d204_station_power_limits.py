"""Station power limits: station-wide cap, per-connector limit, notify flag, session cap.

``connectors.power_kw`` stays the hardware rating; the vendor limit lives in
``connectors.power_limit_kw``. Allocation rule: ``chargegrid_core.power``.

Revision ID: c3a9e5f1d204
Revises: f2b7d4c8a1e6
"""

import sqlalchemy as sa
from alembic import op

revision = "c3a9e5f1d204"
down_revision = "f2b7d4c8a1e6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stations", sa.Column("max_power_kw", sa.Numeric(10, 3), nullable=True))
    op.add_column(
        "stations",
        sa.Column("power_limit_notify", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_check_constraint("station_max_power_positive", "stations", "max_power_kw IS NULL OR max_power_kw > 0")
    op.add_column("connectors", sa.Column("power_limit_kw", sa.Numeric(10, 3), nullable=True))
    op.create_check_constraint(
        "connector_power_limit_range", "connectors",
        "power_limit_kw IS NULL OR (power_limit_kw > 0 AND power_limit_kw <= power_kw)",
    )
    op.add_column("charging_sessions", sa.Column("power_limit_kw", sa.Numeric(10, 3), nullable=True))
    op.create_check_constraint(
        "session_power_limit_positive", "charging_sessions", "power_limit_kw IS NULL OR power_limit_kw > 0"
    )


def downgrade():
    op.drop_constraint("session_power_limit_positive", "charging_sessions", type_="check")
    op.drop_column("charging_sessions", "power_limit_kw")
    op.drop_constraint("connector_power_limit_range", "connectors", type_="check")
    op.drop_column("connectors", "power_limit_kw")
    op.drop_constraint("station_max_power_positive", "stations", type_="check")
    op.drop_column("stations", "power_limit_notify")
    op.drop_column("stations", "max_power_kw")
