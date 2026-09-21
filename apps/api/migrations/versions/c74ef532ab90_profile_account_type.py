"""Persist account intent and chronological charging-session creation time.

Revision ID: c74ef532ab90
Revises: b25b5b74d07e
"""

import sqlalchemy as sa
from alembic import op

revision = "c74ef532ab90"
down_revision = "b25b5b74d07e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "profiles",
        sa.Column("account_type", sa.String(20), nullable=False, server_default="consumer"),
    )
    op.execute("UPDATE profiles SET account_type = 'vendor' WHERE operator_enabled IS TRUE")
    op.create_check_constraint("profile_account_type", "profiles", "account_type IN ('consumer', 'vendor')")
    op.add_column(
        "charging_sessions",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute("UPDATE charging_sessions SET created_at = COALESCE(started_at, ended_at, created_at)")


def downgrade():
    op.drop_column("charging_sessions", "created_at")
    op.drop_constraint("profile_account_type", "profiles", type_="check")
    op.drop_column("profiles", "account_type")
