"""Index hot read paths: device sync telemetry, session commands, history, coupons.

Revision ID: 4d7e1a9c2b60
Revises: a3f1c9d2e7b4
"""

from alembic import op

revision = "4d7e1a9c2b60"
down_revision = "a3f1c9d2e7b4"
branch_labels = None
depends_on = None

INDEXES = (
    # Each device sync reads the latest sample of that device.
    ("ix_telemetry_device_received", "telemetry_samples", ["device_id", "received_at"]),
    # Start-timeout reconciliation and STOP supersession look up commands by session.
    ("ix_device_commands_session_id", "device_commands", ["session_id"]),
    # Driver history is filtered by user and ordered by creation time.
    ("ix_charging_sessions_user_created", "charging_sessions", ["user_id", "created_at"]),
    # Operators list their own coupons.
    ("ix_coupons_operator_id", "coupons", ["operator_id"]),
)


def upgrade():
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns, if_not_exists=True)


def downgrade():
    for name, table, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)
