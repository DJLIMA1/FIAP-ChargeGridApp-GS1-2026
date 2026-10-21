"""External charger linked to a point's screen: ``connectors.charger_address``.

The screen (ESP32 panel) is the Modbus TCP master of a GoodWe HCA G2 charger on the local
Wi-Fi (today the ESP32 DevKit simulator); the owner picks the charger address (unit id,
``cg-hca-<address>.local``) per point. NULL keeps the screen's internal relay/simulation.

* ``connectors.charger_address`` integer, NULL, 1–247.
* Unique per station (``station_id``, ``charger_address``): two points of the same station never
  drive the same charger. NULLs do not collide.

Additive. Downgrade drops the constraints and the column.

Revision ID: b7c4e2a9d1f3
Revises: a3e8c5d1f7b9
"""

import sqlalchemy as sa
from alembic import op

revision = "b7c4e2a9d1f3"
down_revision = "a3e8c5d1f7b9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("connectors", sa.Column("charger_address", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "connector_charger_address_range", "connectors",
        "charger_address IS NULL OR charger_address BETWEEN 1 AND 247",
    )
    op.create_unique_constraint(
        "uq_connector_station_charger_address", "connectors", ["station_id", "charger_address"]
    )


def downgrade():
    op.drop_constraint("uq_connector_station_charger_address", "connectors", type_="unique")
    op.drop_constraint("connector_charger_address_range", "connectors", type_="check")
    op.drop_column("connectors", "charger_address")
