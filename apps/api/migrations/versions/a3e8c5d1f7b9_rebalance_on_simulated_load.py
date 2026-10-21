"""Live rebalancing on by default, simulated store load by establishment type/size, and
the per-station payment switches back to their defaults.

* ``stations.rebalance_enabled``: server default becomes ``true`` and every existing station
  is switched on (the store load is now simulated automatically, chargegrid_core.site_load).
* ``stations.building_profile`` / ``building_size``: establishment type and size for the
  simulated hourly curve (NULL = convenience store, medium size).
* ``prepay_required`` / ``kiosk_payments`` go back to ``false`` on every station: the app no
  longer exposes them; the app pays with Stripe by default (simulated in presentation mode)
  and the self-service totem (``kiosk_mode``, in "Dados da estação") is the panel's payment.

Additive. Downgrade drops the two columns and restores the ``false`` default; the previous
values of ``rebalance_enabled``/``prepay_required``/``kiosk_payments`` are not restored.

Revision ID: a3e8c5d1f7b9
Revises: f4b9d2c7e1a3
"""

import sqlalchemy as sa
from alembic import op

revision = "a3e8c5d1f7b9"
down_revision = "f4b9d2c7e1a3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stations", sa.Column("building_profile", sa.String(20)))
    op.add_column("stations", sa.Column("building_size", sa.String(10)))
    op.alter_column("stations", "rebalance_enabled", server_default=sa.text("true"))
    op.execute("UPDATE stations SET rebalance_enabled = true WHERE rebalance_enabled IS DISTINCT FROM true")
    op.execute("UPDATE stations SET prepay_required = false, kiosk_payments = false "
               "WHERE prepay_required OR kiosk_payments")


def downgrade():
    op.alter_column("stations", "rebalance_enabled", server_default=sa.text("false"))
    op.drop_column("stations", "building_size")
    op.drop_column("stations", "building_profile")
