"""Driver mode: station amenities and per-user driver profile (vehicle + shift preferences).

Revision ID: e7d3c1a95b42
Revises: 9c4a2b8e1170
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "e7d3c1a95b42"
down_revision = "9c4a2b8e1170"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "stations",
        sa.Column("amenities", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.create_check_constraint(
        "station_amenities_array", "stations", "jsonb_typeof(amenities) = 'array' AND jsonb_array_length(amenities) <= 12"
    )
    op.create_table(
        "driver_profiles",
        sa.Column("user_id", UUID(), sa.ForeignKey("profiles.id"), primary_key=True),
        sa.Column("vehicle", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("preferences", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute("ALTER TABLE driver_profiles ENABLE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT, UPDATE ON TABLE driver_profiles TO chargegrid_api")
    op.execute("CREATE POLICY api_only ON driver_profiles FOR ALL TO chargegrid_api USING (true) WITH CHECK (true)")


def downgrade():
    op.drop_table("driver_profiles")
    op.drop_constraint("station_amenities_array", "stations", type_="check")
    op.drop_column("stations", "amenities")
