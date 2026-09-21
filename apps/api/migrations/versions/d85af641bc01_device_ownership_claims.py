"""Factory-owned points and single-use proof-of-possession claims.

Revision ID: d85af641bc01
Revises: c74ef532ab90
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d85af641bc01"
down_revision = "c74ef532ab90"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("stations", "owner_id", existing_type=postgresql.UUID(), nullable=True)
    op.create_table(
        "device_claims",
        sa.Column("connector_id", postgresql.UUID(), sa.ForeignKey("connectors.id"), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("claimed_by", postgresql.UUID(), sa.ForeignKey("profiles.id"), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("(claimed_by IS NULL) = (claimed_at IS NULL)", name="claim_audit_complete"),
    )
    op.execute("REVOKE ALL ON TABLE device_claims FROM PUBLIC")
    op.execute("GRANT SELECT, UPDATE ON TABLE device_claims TO chargegrid_api")
    op.execute("ALTER TABLE device_claims ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY api_only ON device_claims FOR ALL TO chargegrid_api USING (true) WITH CHECK (true)"
    )


def downgrade():
    # Fail safely rather than deleting unclaimed factory equipment on downgrade.
    op.alter_column("stations", "owner_id", existing_type=postgresql.UUID(), nullable=False)
    op.drop_table("device_claims")
