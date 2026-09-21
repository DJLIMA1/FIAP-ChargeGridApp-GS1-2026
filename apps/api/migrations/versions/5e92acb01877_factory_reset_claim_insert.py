"""Permit runtime factory-reset acknowledgement to create a fresh claim.

Revision ID: 5e92acb01877
Revises: d85af641bc01
"""

from alembic import op

revision = "5e92acb01877"
down_revision = "d85af641bc01"
branch_labels = None
depends_on = None


def upgrade():
    # The original claim flow was administratively provisioned, so the API role
    # had only SELECT/UPDATE. Factory reset now creates an unowned claim itself.
    op.execute("GRANT INSERT ON TABLE device_claims TO chargegrid_api")


def downgrade():
    op.execute("REVOKE INSERT ON TABLE device_claims FROM chargegrid_api")
