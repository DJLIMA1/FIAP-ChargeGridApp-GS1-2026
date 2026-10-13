"""Record AI assistant usage metadata (tokens, cost, latency) without content.

Revision ID: a71c3e5d9b20
Revises: a3f1c9d2e7b4
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "a71c3e5d9b20"
down_revision = "a3f1c9d2e7b4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_usage",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", UUID(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column("feature", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("model", sa.String(100), nullable=False, server_default=""),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tools", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ai_usage_user_id", "ai_usage", ["user_id"])
    op.create_index("ix_ai_usage_created_at", "ai_usage", ["created_at"])
    op.execute("ALTER TABLE ai_usage ENABLE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT ON TABLE ai_usage TO chargegrid_api")
    op.execute("GRANT USAGE ON SEQUENCE ai_usage_id_seq TO chargegrid_api")
    op.execute("CREATE POLICY api_only ON ai_usage FOR ALL TO chargegrid_api USING (true) WITH CHECK (true)")


def downgrade():
    op.drop_index("ix_ai_usage_created_at", table_name="ai_usage")
    op.drop_index("ix_ai_usage_user_id", table_name="ai_usage")
    op.drop_table("ai_usage")
