"""Remove a station: ``stations.removed_at``.

``DELETE /v1/stations/{id}`` closes a whole station: it leaves every listing (driver discovery and
map, seller lists, owner dashboards and pickers, AI tools) while sessions, receipts, payments and
margin reports keep their rows. Its connectors become history (``connectors.removed_at``) and its
offline centrals are revoked.

* ``stations.removed_at`` TIMESTAMPTZ NULL.

Additive for existing rows. Downgrade drops the column (removed stations stay inactive).

Revision ID: a9d4e2b7c1f6
Revises: d8b3f6a2c5e7
"""

import sqlalchemy as sa
from alembic import op

revision = "a9d4e2b7c1f6"
down_revision = "d8b3f6a2c5e7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stations", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("stations", "removed_at")
