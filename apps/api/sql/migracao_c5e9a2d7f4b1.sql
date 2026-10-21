BEGIN;

-- Running upgrade b7c4e2a9d1f3 -> c5e9a2d7f4b1

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
WHERE c.id = picked.id;

ALTER TABLE connectors ALTER COLUMN charger_address SET NOT NULL;

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
$$ LANGUAGE plpgsql;

CREATE TRIGGER connector_next_charger_address BEFORE INSERT ON connectors
FOR EACH ROW EXECUTE FUNCTION connector_next_charger_address();

UPDATE alembic_version SET version_num='c5e9a2d7f4b1' WHERE alembic_version.version_num = 'b7c4e2a9d1f3';

COMMIT;

