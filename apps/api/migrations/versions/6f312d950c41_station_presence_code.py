"""Private random seed for rotating station presence codes.

Revision ID: 6f312d950c41
Revises: 5e92acb01877
"""

import secrets

import sqlalchemy as sa
from alembic import op

revision = "6f312d950c41"
down_revision = "5e92acb01877"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stations", sa.Column("presence_secret", sa.String(64), nullable=True))
    connection = op.get_bind()
    for station_id, in connection.execute(sa.text("SELECT id FROM stations")):
        connection.execute(
            sa.text("UPDATE stations SET presence_secret = :secret WHERE id = :id"),
            {"secret": secrets.token_hex(32), "id": station_id},
        )
    op.alter_column("stations", "presence_secret", nullable=False)


def downgrade():
    op.drop_column("stations", "presence_secret")
