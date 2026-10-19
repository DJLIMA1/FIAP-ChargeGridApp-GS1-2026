BEGIN;

-- Running upgrade b8e4f2a6c913 -> f2b7d4c8a1e6

ALTER TABLE charging_sessions ADD COLUMN start_soc_percent NUMERIC(5, 2);

ALTER TABLE charging_sessions ADD COLUMN battery_kwh NUMERIC(6, 2);

ALTER TABLE charging_sessions ADD COLUMN soc_source VARCHAR(20);

ALTER TABLE charging_sessions ADD CONSTRAINT session_start_soc_range CHECK (start_soc_percent IS NULL OR start_soc_percent BETWEEN 0 AND 100);

ALTER TABLE charging_sessions ADD CONSTRAINT session_battery_kwh_range CHECK (battery_kwh IS NULL OR battery_kwh BETWEEN 5 AND 250);

ALTER TABLE charging_sessions ADD CONSTRAINT session_soc_source CHECK (soc_source IS NULL OR soc_source IN ('simulated', 'phone'));

UPDATE alembic_version SET version_num='f2b7d4c8a1e6' WHERE alembic_version.version_num = 'b8e4f2a6c913';

COMMIT;

