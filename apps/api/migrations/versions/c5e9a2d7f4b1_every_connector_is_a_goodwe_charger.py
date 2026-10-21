"""Every connector is a GoodWe HCA G2 charger: ``connectors.charger_address`` NOT NULL.

The optional external charger is gone: each point is a charger with a Modbus address
(unit id, ``cg-hca-<address>.local``), unique per station and editable by the owner. When the
charger at that address does not answer, the screen charges with its internal simulation.

* Backfill: connectors without an address get the free addresses of their station in a stable
  order (``public_code``, then ``id``; connectors have no creation timestamp and the public
  code is what the owner sees in the list), never colliding with addresses already set.
* ``charger_address`` becomes NOT NULL (range check 1–247 and the per-station unique
  constraint from b7c4e2a9d1f3 stay).
* ``BEFORE INSERT`` trigger ``connector_next_charger_address``: an INSERT without an address
  (ORM, factory SQL in ``tools/provision_point.py``) gets the lowest free address of the station.
  The same trigger is attached to ``Base.metadata`` (``app.models``) for the test schema.

A station with more than 247 connectors cannot be backfilled and makes the upgrade fail
(transactional: nothing changes).

Downgrade drops the trigger/function and makes the column nullable again; the addresses are
kept (backfilled and owner-set ones cannot be told apart). On b7c4e2a9d1f3 a non-null address
means "external charger linked", so the old API keeps sending ``charger_link`` for every point:
panel firmware from this change still falls back to its simulation, but the panel build of
b7c4e2a9d1f3 (c8e9c38) fails START while the charger is unreachable. To go back to "no external
charger" on that build, run ``UPDATE connectors SET charger_address = NULL`` where wanted.

Revision ID: c5e9a2d7f4b1
Revises: b7c4e2a9d1f3
"""

import sqlalchemy as sa
from alembic import op

revision = "c5e9a2d7f4b1"
down_revision = "b7c4e2a9d1f3"
branch_labels = None
depends_on = None

BACKFILL = """
UPDATE connectors AS c SET charger_address = picked.address
FROM (
    SELECT pending.id, free.address
    FROM (
        SELECT id, station_id,
               row_number() OVER (PARTITION BY station_id ORDER BY public_code, id) AS position
        FROM connectors WHERE charger_address IS NULL
    ) AS pending
    JOIN LATERAL (
        SELECT n AS address FROM generate_series(1, 247) AS n
        WHERE NOT EXISTS (
            SELECT 1 FROM connectors taken
            WHERE taken.station_id = pending.station_id AND taken.charger_address = n
        )
        ORDER BY n OFFSET pending.position - 1 LIMIT 1
    ) AS free ON TRUE
) AS picked
WHERE c.id = picked.id
"""

FUNCTION = """
CREATE OR REPLACE FUNCTION connector_next_charger_address() RETURNS trigger AS $$
BEGIN
    IF NEW.charger_address IS NULL THEN
        SELECT n INTO NEW.charger_address FROM generate_series(1, 247) AS n
        WHERE NOT EXISTS (
            SELECT 1 FROM connectors c WHERE c.station_id = NEW.station_id AND c.charger_address = n
        )
        ORDER BY n LIMIT 1;
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql
"""

TRIGGER = """
CREATE TRIGGER connector_next_charger_address BEFORE INSERT ON connectors
FOR EACH ROW EXECUTE FUNCTION connector_next_charger_address()
"""


def upgrade():
    op.execute(BACKFILL)
    op.alter_column("connectors", "charger_address", existing_type=sa.Integer(), nullable=False)
    op.execute(FUNCTION)
    op.execute(TRIGGER)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS connector_next_charger_address ON connectors")
    op.execute("DROP FUNCTION IF EXISTS connector_next_charger_address()")
    op.alter_column("connectors", "charger_address", existing_type=sa.Integer(), nullable=True)
