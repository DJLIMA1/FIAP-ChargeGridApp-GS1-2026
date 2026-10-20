"""Overstay after charging: accepted terms, the connected interval and the fee per session.

Additive only. Old rotation rules were stored as "registered, not charged": they are turned
off here so no station starts charging (or holding money for) an overstay fee without the
owner switching it on again with the new cap (``max_amount``).

Revision ID: c8e3a5f2d914
Revises: c5f0a7e3d912
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "c8e3a5f2d914"
down_revision = "c5f0a7e3d912"
branch_labels = None
depends_on = None

OPEN = "overstay_started_at IS NOT NULL AND overstay_ended_at IS NULL"


def upgrade():
    op.add_column("charging_sessions", sa.Column("overstay_terms", JSONB()))
    op.add_column("charging_sessions", sa.Column("overstay_started_at", sa.DateTime(timezone=True)))
    op.add_column("charging_sessions", sa.Column("overstay_last_connected_at", sa.DateTime(timezone=True)))
    op.add_column(
        "charging_sessions",
        sa.Column("overstay_billable_seconds", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("charging_sessions", sa.Column("overstay_ended_at", sa.DateTime(timezone=True)))
    op.add_column("charging_sessions", sa.Column("overstay_end_reason", sa.String(30)))
    op.add_column(
        "charging_sessions",
        sa.Column("overstay_fee", sa.Numeric(12, 4), nullable=False, server_default=sa.text("0")),
    )
    op.create_check_constraint(
        "session_overstay_amounts", "charging_sessions", "overstay_billable_seconds >= 0 AND overstay_fee >= 0"
    )
    op.create_check_constraint(
        "session_overstay_order", "charging_sessions", "overstay_ended_at IS NULL OR overstay_started_at IS NOT NULL"
    )
    op.create_check_constraint(
        "session_overstay_end_reason", "charging_sessions",
        "overstay_end_reason IS NULL OR overstay_end_reason IN "
        "('disconnected', 'device_reboot', 'observation_lost', 'owner_waived')",
    )
    op.create_index(
        "one_open_overstay_connector", "charging_sessions", ["connector_id"], unique=True,
        postgresql_where=sa.text(OPEN),
    )
    op.create_index("ix_open_overstay_user", "charging_sessions", ["user_id"], postgresql_where=sa.text(OPEN))
    op.execute(
        "UPDATE stations SET pricing = jsonb_set(pricing, '{rotation,enabled}', 'false'::jsonb) "
        "WHERE jsonb_typeof(pricing->'rotation') = 'object' AND NOT (pricing->'rotation' ? 'max_amount')"
    )


def downgrade():
    # The rotation rules switched off on upgrade stay off (they were never charged).
    op.drop_index("ix_open_overstay_user", table_name="charging_sessions")
    op.drop_index("one_open_overstay_connector", table_name="charging_sessions")
    op.drop_constraint("session_overstay_end_reason", "charging_sessions", type_="check")
    op.drop_constraint("session_overstay_order", "charging_sessions", type_="check")
    op.drop_constraint("session_overstay_amounts", "charging_sessions", type_="check")
    for column in ("overstay_fee", "overstay_end_reason", "overstay_ended_at", "overstay_billable_seconds",
                   "overstay_last_connected_at", "overstay_started_at", "overstay_terms"):
        op.drop_column("charging_sessions", column)
