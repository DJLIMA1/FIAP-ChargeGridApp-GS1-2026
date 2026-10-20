"""Explainable receipt and owner economics: locked price terms, energy cost and platform fee.

* ``stations.energy_cost_per_kwh``: energy cost per kWh informed by the owner (panel);
  ``NULL`` = not informed (margin is not computed, never treated as zero).
* ``stations.platform_fee_percent``: platform commission (contract), default 25 %; read-only
  for the owner, changed by an administrator (``tools/set_platform_fee.py``).
* ``charging_sessions.price_terms`` / ``reservations.price_terms``: explanation of the locked
  price (base, schedule window, demand reason and factors, coupon), written when the price is
  locked. The device protocol is unchanged.
* ``charging_sessions.energy_cost_per_kwh`` / ``platform_fee_percent``: station values copied
  at start, so later changes do not rewrite past margins.

Additive and nullable; no backfill (older sessions show an honest fallback).

Revision ID: b6d2f9a4c8e1
Revises: d1e8f3a2c7b5
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b6d2f9a4c8e1"
down_revision = "d1e8f3a2c7b5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stations", sa.Column("energy_cost_per_kwh", sa.Numeric(10, 4), nullable=True))
    op.add_column(
        "stations",
        sa.Column("platform_fee_percent", sa.Numeric(5, 2), nullable=False, server_default=sa.text("25")),
    )
    op.create_check_constraint(
        "station_energy_cost_range", "stations",
        "energy_cost_per_kwh IS NULL OR energy_cost_per_kwh BETWEEN 0 AND 100",
    )
    op.create_check_constraint(
        "station_platform_fee_range", "stations", "platform_fee_percent BETWEEN 0 AND 100"
    )
    op.add_column("charging_sessions", sa.Column("price_terms", postgresql.JSONB(), nullable=True))
    op.add_column("charging_sessions", sa.Column("energy_cost_per_kwh", sa.Numeric(10, 4), nullable=True))
    op.add_column("charging_sessions", sa.Column("platform_fee_percent", sa.Numeric(5, 2), nullable=True))
    op.create_check_constraint(
        "session_energy_cost_range", "charging_sessions",
        "energy_cost_per_kwh IS NULL OR energy_cost_per_kwh BETWEEN 0 AND 100",
    )
    op.create_check_constraint(
        "session_platform_fee_range", "charging_sessions",
        "platform_fee_percent IS NULL OR platform_fee_percent BETWEEN 0 AND 100",
    )
    op.add_column("reservations", sa.Column("price_terms", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("reservations", "price_terms")
    op.drop_constraint("session_platform_fee_range", "charging_sessions", type_="check")
    op.drop_constraint("session_energy_cost_range", "charging_sessions", type_="check")
    op.drop_column("charging_sessions", "platform_fee_percent")
    op.drop_column("charging_sessions", "energy_cost_per_kwh")
    op.drop_column("charging_sessions", "price_terms")
    op.drop_constraint("station_platform_fee_range", "stations", type_="check")
    op.drop_constraint("station_energy_cost_range", "stations", type_="check")
    op.drop_column("stations", "platform_fee_percent")
    op.drop_column("stations", "energy_cost_per_kwh")
