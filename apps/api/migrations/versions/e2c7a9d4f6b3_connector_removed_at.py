"""Remove an additional charger: ``connectors.removed_at``.

``DELETE /v1/connectors/{id}`` removes an additional charger of a station (never the screen's own
point). Without history the rows are deleted; with history (sessions, reservations, payments,
totem orders, hourly stats or telemetry) the connector stays for those FKs and receipts, marked
``removed_at``: it leaves station/owner listings and the screen's ``chargers`` and frees its
GoodWe address (``charger_address`` NULL) for the next "Adicionar carregador".

* ``connectors.removed_at`` TIMESTAMPTZ NULL.
* ``connectors.charger_address`` NULL again, but only for removed connectors
  (``connector_charger_address_unless_removed``); live connectors keep the c5e9a2d7f4b1 rule.

Additive for existing rows. Downgrade gives removed connectors a free address back and drops the column.

Revision ID: e2c7a9d4f6b3
Revises: b6d2e8f1a490
"""

import sqlalchemy as sa
from alembic import op

revision = "e2c7a9d4f6b3"
down_revision = "b6d2e8f1a490"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("connectors", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("connectors", "charger_address", existing_type=sa.Integer(), nullable=True)
    op.create_check_constraint(
        "connector_charger_address_unless_removed", "connectors",
        "charger_address IS NOT NULL OR removed_at IS NOT NULL",
    )


def downgrade():
    op.drop_constraint("connector_charger_address_unless_removed", "connectors", type_="check")
    # NULL addresses come back with the c5e9a2d7f4b1 trigger rule (smallest free address), one row
    # at a time so two removed connectors of the same station never pick the same address.
    op.execute("""
        DO $$
        DECLARE item RECORD;
        BEGIN
            FOR item IN SELECT id, station_id FROM connectors WHERE charger_address IS NULL ORDER BY id LOOP
                UPDATE connectors SET charger_address = (
                    SELECT n FROM generate_series(1, 247) AS n
                    WHERE NOT EXISTS (
                        SELECT 1 FROM connectors taken
                        WHERE taken.station_id = item.station_id AND taken.charger_address = n
                    )
                    ORDER BY n LIMIT 1
                ) WHERE id = item.id;
            END LOOP;
        END $$
    """)
    op.alter_column("connectors", "charger_address", existing_type=sa.Integer(), nullable=False)
    op.drop_column("connectors", "removed_at")
