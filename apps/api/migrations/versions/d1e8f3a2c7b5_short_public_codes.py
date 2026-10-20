"""Short connector public codes: CG-4C7574B217E6 -> CG-7KQ2.

Factory provisioning used ``"CG-" + 12 hex``; new points get ``CG-`` + 4 characters
(``app.service.new_public_code``). This data migration shortens the existing long codes;
other codes (``CG-PAINEL-03``, demo, manual) stay as they are. Devices learn the new code on
their next sync.

Revision ID: d1e8f3a2c7b5
Revises: a7c2e9d4b6f1
"""

import re
import secrets

import sqlalchemy as sa
from alembic import op

revision = "d1e8f3a2c7b5"
down_revision = "a7c2e9d4b6f1"
branch_labels = None
depends_on = None

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LONG = re.compile(r"^CG-[0-9A-F]{12}$")


def upgrade():
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, public_code FROM connectors")).all()
    taken = {code for _, code in rows}
    for identifier, code in rows:
        if not LONG.match(code):
            continue
        while True:
            short = "CG-" + "".join(secrets.choice(ALPHABET) for _ in range(4))
            if short not in taken:
                break
        taken.add(short)
        connection.execute(sa.text("UPDATE connectors SET public_code = :short WHERE id = :id"),
                           {"short": short, "id": identifier})


def downgrade():
    # Os códigos antigos eram aleatórios e não precisam voltar.
    pass
