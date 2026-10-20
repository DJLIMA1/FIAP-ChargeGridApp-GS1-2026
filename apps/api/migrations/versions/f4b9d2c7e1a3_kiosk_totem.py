"""Self-service totem: account presentation mode, per-station totem flag and totem orders.

``profiles.presentation_mode`` mirrors the app's presentation mode on the account; on the server it
only picks the totem payment of that owner's stations (simulated instead of Stripe test).
``stations.kiosk_mode`` turns the totem on per station. ``kiosk_orders`` holds each purchase made on
the panel without a phone: locked terms, the point hold (``expires_at`` while open), payment,
session and the salt/hash of the visitor receipt token. Additive; everything defaults to off.

Revision ID: f4b9d2c7e1a3
Revises: c8e3a5f2d914
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "f4b9d2c7e1a3"
down_revision = "c8e3a5f2d914"
branch_labels = None
depends_on = None

STATUSES = ("held", "awaiting_payment", "paid", "charging", "finished", "canceled", "expired", "failed")
OPEN = "status IN ('held', 'awaiting_payment', 'paid')"


def _in(values):
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def _backend_only(table):
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON TABLE {table} TO chargegrid_api")
    op.execute(f"CREATE POLICY api_only ON {table} FOR ALL TO chargegrid_api USING (true) WITH CHECK (true)")
    op.execute(
        f"""DO $$ BEGIN
        EXECUTE 'REVOKE ALL ON TABLE {table} FROM PUBLIC';
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
          EXECUTE 'REVOKE ALL ON TABLE {table} FROM anon';
        END IF;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
          EXECUTE 'REVOKE ALL ON TABLE {table} FROM authenticated';
        END IF;
        END $$"""
    )


def upgrade():
    op.add_column("profiles", sa.Column("presentation_mode", sa.Boolean(), nullable=False,
                                        server_default=sa.text("false")))
    op.add_column("stations", sa.Column("kiosk_mode", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_table(
        "kiosk_orders",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("connector_id", UUID(), sa.ForeignKey("connectors.id"), nullable=False),
        sa.Column("guest_id", UUID(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column("payment_id", UUID(), sa.ForeignKey("payments.id"), nullable=True, unique=True),
        sa.Column("session_id", UUID(), sa.ForeignKey("charging_sessions.id"), nullable=True, unique=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("quote", JSONB(), nullable=False),
        sa.Column("quote_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_salt", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("last_error", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"status IN {_in(STATUSES)}", name="kiosk_order_status"),
        sa.CheckConstraint("method IN ('simulated', 'stripe')", name="kiosk_order_method"),
        sa.CheckConstraint("mode IN ('value', 'time', 'energy')", name="kiosk_order_mode"),
    )
    op.create_index("ix_kiosk_orders_connector_created", "kiosk_orders", ["connector_id", "created_at"])
    op.create_index("one_open_kiosk_order_connector", "kiosk_orders", ["connector_id"], unique=True,
                    postgresql_where=sa.text(OPEN))
    _backend_only("kiosk_orders")


def downgrade():
    op.drop_index("one_open_kiosk_order_connector", table_name="kiosk_orders")
    op.drop_index("ix_kiosk_orders_connector_created", table_name="kiosk_orders")
    op.drop_table("kiosk_orders")
    op.drop_column("stations", "kiosk_mode")
    op.drop_column("profiles", "presentation_mode")
