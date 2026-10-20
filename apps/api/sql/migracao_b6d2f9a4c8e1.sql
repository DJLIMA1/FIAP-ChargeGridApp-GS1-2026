BEGIN;

-- Running upgrade d1e8f3a2c7b5 -> b6d2f9a4c8e1

ALTER TABLE stations ADD COLUMN energy_cost_per_kwh NUMERIC(10, 4);

ALTER TABLE stations ADD COLUMN platform_fee_percent NUMERIC(5, 2) DEFAULT 25 NOT NULL;

ALTER TABLE stations ADD CONSTRAINT station_energy_cost_range CHECK (energy_cost_per_kwh IS NULL OR energy_cost_per_kwh BETWEEN 0 AND 100);

ALTER TABLE stations ADD CONSTRAINT station_platform_fee_range CHECK (platform_fee_percent BETWEEN 0 AND 100);

ALTER TABLE charging_sessions ADD COLUMN price_terms JSONB;

ALTER TABLE charging_sessions ADD COLUMN energy_cost_per_kwh NUMERIC(10, 4);

ALTER TABLE charging_sessions ADD COLUMN platform_fee_percent NUMERIC(5, 2);

ALTER TABLE charging_sessions ADD CONSTRAINT session_energy_cost_range CHECK (energy_cost_per_kwh IS NULL OR energy_cost_per_kwh BETWEEN 0 AND 100);

ALTER TABLE charging_sessions ADD CONSTRAINT session_platform_fee_range CHECK (platform_fee_percent IS NULL OR platform_fee_percent BETWEEN 0 AND 100);

ALTER TABLE reservations ADD COLUMN price_terms JSONB;

UPDATE alembic_version SET version_num='b6d2f9a4c8e1' WHERE alembic_version.version_num = 'd1e8f3a2c7b5';

COMMIT;

