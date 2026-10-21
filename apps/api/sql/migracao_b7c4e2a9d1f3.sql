BEGIN;

-- Running upgrade a3e8c5d1f7b9 -> b7c4e2a9d1f3

ALTER TABLE connectors ADD COLUMN charger_address INTEGER;

ALTER TABLE connectors ADD CONSTRAINT connector_charger_address_range CHECK (charger_address IS NULL OR charger_address BETWEEN 1 AND 247);

ALTER TABLE connectors ADD CONSTRAINT uq_connector_station_charger_address UNIQUE (station_id, charger_address);

UPDATE alembic_version SET version_num='b7c4e2a9d1f3' WHERE alembic_version.version_num = 'a3e8c5d1f7b9';

COMMIT;

