"""Dynamic (demand) pricing: station base data, multiplier locked on reservation and session.

The calculation lives in ``chargegrid_core.pricing``; the owner only stores base data in
``stations.pricing``. ``charging_sessions.price_per_kwh`` keeps the charged price and now
equals ``base_price_per_kwh × demand_multiplier``.

Revision ID: a7c2e9d4b6f1
Revises: c3a9e5f1d204
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a7c2e9d4b6f1"
down_revision = "c3a9e5f1d204"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "stations",
        sa.Column("pricing", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column("reservations", sa.Column("demand_multiplier", sa.Numeric(4, 2), nullable=True))
    op.add_column("charging_sessions", sa.Column("base_price_per_kwh", sa.Numeric(10, 4), nullable=True))
    op.add_column(
        "charging_sessions",
        sa.Column("demand_multiplier", sa.Numeric(4, 2), nullable=False, server_default=sa.text("1")),
    )
    op.create_check_constraint(
        "session_demand_multiplier_range", "charging_sessions", "demand_multiplier BETWEEN 1 AND 2"
    )


def downgrade():
    op.drop_constraint("session_demand_multiplier_range", "charging_sessions", type_="check")
    op.drop_column("charging_sessions", "demand_multiplier")
    op.drop_column("charging_sessions", "base_price_per_kwh")
    op.drop_column("reservations", "demand_multiplier")
    op.drop_column("stations", "pricing")
