BEGIN;

-- Running upgrade c3a9e5f1d204 -> a7c2e9d4b6f1

ALTER TABLE stations ADD COLUMN pricing JSONB DEFAULT '{}'::jsonb NOT NULL;

ALTER TABLE reservations ADD COLUMN demand_multiplier NUMERIC(4, 2);

ALTER TABLE charging_sessions ADD COLUMN base_price_per_kwh NUMERIC(10, 4);

ALTER TABLE charging_sessions ADD COLUMN demand_multiplier NUMERIC(4, 2) DEFAULT 1 NOT NULL;

ALTER TABLE charging_sessions ADD CONSTRAINT session_demand_multiplier_range CHECK (demand_multiplier BETWEEN 1 AND 2);

UPDATE alembic_version SET version_num='a7c2e9d4b6f1' WHERE alembic_version.version_num = 'c3a9e5f1d204';

COMMIT;

