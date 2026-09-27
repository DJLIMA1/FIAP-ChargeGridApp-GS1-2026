"""Generate private presence seeds for SQL provisioning and legacy imports.

Revision ID: 81a24d97be63
Revises: 6f312d950c41
"""

import sqlalchemy as sa
from alembic import op

revision = "81a24d97be63"
down_revision = "6f312d950c41"
branch_labels = None
depends_on = None


def upgrade():
    # Two independently random UUIDs provide 244 random bits using PostgreSQL's
    # built-in generator. No extension privilege is needed; existing seeds stay.
    op.alter_column(
        "stations", "presence_secret", existing_type=sa.String(64),
        server_default=sa.text("replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', '')"),
    )


def downgrade():
    op.alter_column("stations", "presence_secret", existing_type=sa.String(64), server_default=None)
