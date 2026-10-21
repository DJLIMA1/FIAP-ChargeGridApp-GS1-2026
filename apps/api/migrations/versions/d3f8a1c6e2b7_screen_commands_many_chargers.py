"""A station screen commands many GoodWe chargers: ``devices.parent_device_id``.

The STATION is the screen (the panel device with a key); every connector is a GoodWe HCA G2
charger with a Modbus address. One screen now commands N chargers of its station: each extra
charger keeps its own ``devices`` row (sessions, commands, reconciliation and the point state
stay per connector, exactly as before) with an unusable random key, linked to the screen by
``parent_device_id``. The screen syncs on its behalf with ``charger_address`` in the sync body.

* ``devices.parent_device_id`` UUID NULL REFERENCES devices(id), indexed; never itself.
* Existing devices are screens (NULL): nothing changes for old firmware (one point per screen).

Downgrade revokes the extra-charger rows (they have no usable key and the old API would treat
them as screens that never sync) and drops the column.

Revision ID: d3f8a1c6e2b7
Revises: c5e9a2d7f4b1
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d3f8a1c6e2b7"
down_revision = "c5e9a2d7f4b1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("devices", sa.Column("parent_device_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("devices_parent_device_id_fkey", "devices", "devices", ["parent_device_id"], ["id"])
    op.create_index("ix_devices_parent_device_id", "devices", ["parent_device_id"])
    op.create_check_constraint("device_parent_not_self", "devices", "parent_device_id IS NULL OR parent_device_id <> id")


def downgrade():
    op.execute("UPDATE devices SET revoked = TRUE, reconciled = FALSE WHERE parent_device_id IS NOT NULL")
    op.drop_constraint("device_parent_not_self", "devices", type_="check")
    op.drop_index("ix_devices_parent_device_id", table_name="devices")
    op.drop_constraint("devices_parent_device_id_fkey", "devices", type_="foreignkey")
    op.drop_column("devices", "parent_device_id")
