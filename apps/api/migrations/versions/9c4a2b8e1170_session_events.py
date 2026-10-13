"""Persist observed charging-session events without rewriting older sessions.

Revision ID: 9c4a2b8e1170
Revises: 81a24d97be63
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "9c4a2b8e1170"
down_revision = "81a24d97be63"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "session_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("session_id", UUID(), sa.ForeignKey("charging_sessions.id"), nullable=False),
        sa.Column("event_key", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "event_key"),
    )
    op.create_index("ix_session_events_session_id", "session_events", ["session_id"])
    op.execute("ALTER TABLE session_events ENABLE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT ON TABLE session_events TO chargegrid_api")
    op.execute("GRANT USAGE ON SEQUENCE session_events_id_seq TO chargegrid_api")
    op.execute("CREATE POLICY api_only ON session_events FOR ALL TO chargegrid_api USING (true) WITH CHECK (true)")


def downgrade():
    op.drop_index("ix_session_events_session_id", table_name="session_events")
    op.drop_table("session_events")
