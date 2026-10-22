"""Shared simulated wallet for account access at the kiosk.

Revision ID: b6d2e8f1a490
Revises: d3f8a1c6e2b7
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b6d2e8f1a490"
down_revision = "d3f8a1c6e2b7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("simulated_wallets",
        sa.Column("user_id", postgresql.UUID(), sa.ForeignKey("profiles.id"), primary_key=True),
        sa.Column("balance_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("legacy_imported", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("transactions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.CheckConstraint("balance_cents >= 0", name="simulated_wallet_nonnegative"))
    op.execute("ALTER TABLE simulated_wallets ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON simulated_wallets FROM PUBLIC")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
            REVOKE ALL ON simulated_wallets FROM anon;
        END IF;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
            REVOKE ALL ON simulated_wallets FROM authenticated;
        END IF;
    END $$""")
    op.execute("GRANT SELECT, INSERT, UPDATE ON simulated_wallets TO chargegrid_api")
    op.execute("CREATE POLICY api_only ON simulated_wallets FOR ALL TO chargegrid_api USING (true) WITH CHECK (true)")


def downgrade():
    op.drop_table("simulated_wallets")
