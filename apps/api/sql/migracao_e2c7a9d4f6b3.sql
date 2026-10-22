BEGIN;

-- Running upgrade b6d2e8f1a490 -> e2c7a9d4f6b3

ALTER TABLE connectors ADD COLUMN removed_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE connectors ALTER COLUMN charger_address DROP NOT NULL;

ALTER TABLE connectors ADD CONSTRAINT connector_charger_address_unless_removed CHECK (charger_address IS NOT NULL OR removed_at IS NOT NULL);

UPDATE alembic_version SET version_num='e2c7a9d4f6b3' WHERE alembic_version.version_num = 'b6d2e8f1a490';

COMMIT;

