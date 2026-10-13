"""Indexes for owner dashboard aggregates (period filters and live telemetry).

Revision ID: a3f1c9d2e7b4
Revises: 9c4a2b8e1170
"""

from alembic import op

revision = "a3f1c9d2e7b4"
down_revision = "9c4a2b8e1170"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_charging_sessions_connector_ended", "charging_sessions", ["connector_id", "ended_at"]),
    ("ix_charging_sessions_connector_created", "charging_sessions", ["connector_id", "created_at"]),
    ("ix_reservations_connector_created", "reservations", ["connector_id", "created_at"]),
    ("ix_telemetry_samples_session_captured", "telemetry_samples", ["session_id", "captured_at"]),
)


def upgrade():
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade():
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
