"""Stripe test-mode payments: prepaid cap per charge, webhook dedupe and station flags.

``payments`` holds the accepted cap, the terms locked at quote time and the final settlement
(captured / refunded / waived) in integer cents; ``environment`` is always ``test``.
``payment_events`` deduplicates provider webhooks without storing their bodies. Stations gain
``prepay_required`` (START needs a confirmed payment) and ``kiosk_payments`` (payment QR on the
physical panel). Additive: historical sessions keep ``payment = null``.

Revision ID: e5a1c7f3b9d2
Revises: b6d2f9a4c8e1
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "e5a1c7f3b9d2"
down_revision = "b6d2f9a4c8e1"
branch_labels = None
depends_on = None

STATUSES = ("awaiting_payment", "declined", "authorized", "paid", "in_use", "expired", "canceled", "completed")
SETTLEMENT = ("none", "due", "settling", "done", "failed")


def _in(values):
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def _backend_only(table, sequence=None):
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON TABLE {table} TO chargegrid_api")
    if sequence:
        op.execute(f"GRANT USAGE ON SEQUENCE {sequence} TO chargegrid_api")
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
    for name in ("prepay_required", "kiosk_payments"):
        op.add_column("stations", sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_table(
        "payments",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("user_id", UUID(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column("connector_id", UUID(), sa.ForeignKey("connectors.id"), nullable=False),
        sa.Column("session_id", UUID(), sa.ForeignKey("charging_sessions.id"), nullable=True, unique=True),
        sa.Column("origin", sa.String(10), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("environment", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("settlement_status", sa.String(20), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("energy_cap_cents", sa.Integer(), nullable=False),
        sa.Column("fixed_fee_cents", sa.Integer(), nullable=False),
        sa.Column("overstay_reserve_cents", sa.Integer(), nullable=False),
        sa.Column("energy_cents", sa.Integer(), nullable=True),
        sa.Column("overstay_cents", sa.Integer(), nullable=True),
        sa.Column("charge_cents", sa.Integer(), nullable=True),
        sa.Column("waived_cents", sa.Integer(), nullable=False),
        sa.Column("uncollected_cents", sa.Integer(), nullable=False),
        sa.Column("captured_cents", sa.Integer(), nullable=False),
        sa.Column("refunded_cents", sa.Integer(), nullable=False),
        sa.Column("provider_fee_cents", sa.Integer(), nullable=True),
        sa.Column("price_per_kwh", sa.Numeric(10, 4), nullable=False),
        sa.Column("base_price_per_kwh", sa.Numeric(10, 4), nullable=False),
        sa.Column("demand_multiplier", sa.Numeric(4, 2), nullable=False),
        sa.Column("discount_percent", sa.Integer(), nullable=False),
        sa.Column("coupon_code", sa.String(50), nullable=True),
        sa.Column("max_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("max_power_kw", sa.Numeric(10, 3), nullable=True),
        sa.Column("quote", JSONB(), nullable=False),
        sa.Column("provider_checkout_id", sa.String(100), nullable=True, unique=True),
        sa.Column("provider_payment_intent_id", sa.String(100), nullable=True, unique=True),
        sa.Column("provider_status", sa.String(40), nullable=True),
        sa.Column("method", sa.String(30), nullable=True),
        sa.Column("checkout_url", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_provider_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settle_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(200), nullable=True),
        sa.Column("kiosk_token_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("origin IN ('app', 'kiosk')", name="payment_origin"),
        sa.CheckConstraint("environment = 'test'", name="payment_environment_test"),
        sa.CheckConstraint(f"status IN {_in(STATUSES)}", name="payment_status"),
        sa.CheckConstraint(f"settlement_status IN {_in(SETTLEMENT)}", name="payment_settlement_status"),
        sa.CheckConstraint(
            "amount_cents > 0 AND energy_cap_cents > 0 AND fixed_fee_cents >= 0 AND overstay_reserve_cents >= 0"
            " AND amount_cents = energy_cap_cents + fixed_fee_cents + overstay_reserve_cents",
            name="payment_amounts",
        ),
        sa.CheckConstraint(
            "captured_cents >= 0 AND refunded_cents >= 0 AND waived_cents >= 0 AND uncollected_cents >= 0"
            " AND captured_cents <= amount_cents AND refunded_cents <= captured_cents"
            " AND (charge_cents IS NULL OR charge_cents BETWEEN 0 AND amount_cents)",
            name="payment_settlement_amounts",
        ),
        sa.CheckConstraint("discount_percent BETWEEN 0 AND 100", name="payment_discount_range"),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_index("ix_payments_connector_status", "payments", ["connector_id", "status"])
    op.create_index(
        "ix_payments_settlement", "payments", ["settlement_status"],
        postgresql_where=sa.text("settlement_status IN ('due', 'settling')"),
    )
    op.create_index(
        "one_open_app_payment_user", "payments", ["user_id"], unique=True,
        postgresql_where=sa.text(
            "origin = 'app' AND status IN ('awaiting_payment', 'declined', 'authorized', 'paid')"
        ),
    )
    _backend_only("payments")
    op.create_table(
        "payment_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("event_id", sa.String(100), nullable=False),
        sa.Column("type", sa.String(80), nullable=False),
        sa.Column("payment_id", UUID(), sa.ForeignKey("payments.id"), nullable=True),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("provider", "event_id"),
    )
    op.create_index("ix_payment_events_payment_id", "payment_events", ["payment_id"])
    _backend_only("payment_events", "payment_events_id_seq")


def downgrade():
    op.drop_index("ix_payment_events_payment_id", table_name="payment_events")
    op.drop_table("payment_events")
    for name in ("one_open_app_payment_user", "ix_payments_settlement", "ix_payments_connector_status",
                 "ix_payments_user_id"):
        op.drop_index(name, table_name="payments")
    op.drop_table("payments")
    op.drop_column("stations", "kiosk_payments")
    op.drop_column("stations", "prepay_required")
