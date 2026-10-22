"""Monthly rent per central (screen), deducted from the owner's statement.

* ``central_rent_rates``: contract rates with a local effective date. ``station_id`` NULL = the
  platform default; a station row overrides it (``monthly_amount`` NULL = back to the default).
  No rate is seeded: without rows there is no rent (set it with ``tools/set_central_rent.py``).
* ``devices.created_at`` (NULL for rows created before this migration: the QR claim date applies)
  and ``devices.revoked_at`` filled by the ``device_revoked_at`` trigger on the first revocation
  (revoke, factory reset, retired chargers). Devices revoked before this migration keep NULL and
  are never billed.

Additive. Downgrade drops the table, trigger and columns.

Revision ID: c4f1a8e6d2b9
Revises: e2c7a9d4f6b3
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c4f1a8e6d2b9"
down_revision = "e2c7a9d4f6b3"
branch_labels = None
depends_on = None


def upgrade():
    # Sem DEFAULT na criação: as linhas existentes ficam NULL (data desconhecida); depois o padrão.
    op.add_column("devices", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("devices", "created_at", server_default=sa.text("now()"))
    op.add_column("devices", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("""
        CREATE OR REPLACE FUNCTION device_revoked_at() RETURNS trigger AS $$
        BEGIN
            IF NEW.revoked AND NEW.revoked_at IS NULL AND (TG_OP = 'INSERT' OR NOT OLD.revoked) THEN
                NEW.revoked_at := now();
            END IF;
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER device_revoked_at BEFORE INSERT OR UPDATE OF revoked ON devices
        FOR EACH ROW EXECUTE FUNCTION device_revoked_at()
    """)
    op.create_table(
        "central_rent_rates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("station_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stations.id"), nullable=True),
        sa.Column("monthly_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("monthly_amount IS NULL OR monthly_amount BETWEEN 0 AND 10000",
                           name="central_rent_amount_range"),
        sa.CheckConstraint("station_id IS NOT NULL OR monthly_amount IS NOT NULL",
                           name="central_rent_default_amount"),
    )
    op.create_index("ix_central_rent_rates_station_id", "central_rent_rates", ["station_id"])
    op.create_index("uq_central_rent_default", "central_rent_rates", ["effective_from"], unique=True,
                    postgresql_where=sa.text("station_id IS NULL"))
    op.create_index("uq_central_rent_station", "central_rent_rates", ["station_id", "effective_from"], unique=True,
                    postgresql_where=sa.text("station_id IS NOT NULL"))


def downgrade():
    op.drop_table("central_rent_rates")
    op.execute("DROP TRIGGER IF EXISTS device_revoked_at ON devices")
    op.execute("DROP FUNCTION IF EXISTS device_revoked_at()")
    op.drop_column("devices", "revoked_at")
    op.drop_column("devices", "created_at")
