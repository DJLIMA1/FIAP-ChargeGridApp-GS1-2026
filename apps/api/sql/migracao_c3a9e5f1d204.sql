BEGIN;

-- Running upgrade f2b7d4c8a1e6 -> c3a9e5f1d204

ALTER TABLE stations ADD COLUMN max_power_kw NUMERIC(10, 3);

ALTER TABLE stations ADD COLUMN power_limit_notify BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE stations ADD CONSTRAINT station_max_power_positive CHECK (max_power_kw IS NULL OR max_power_kw > 0);

ALTER TABLE connectors ADD COLUMN power_limit_kw NUMERIC(10, 3);

ALTER TABLE connectors ADD CONSTRAINT connector_power_limit_range CHECK (power_limit_kw IS NULL OR (power_limit_kw > 0 AND power_limit_kw <= power_kw));

ALTER TABLE charging_sessions ADD COLUMN power_limit_kw NUMERIC(10, 3);

ALTER TABLE charging_sessions ADD CONSTRAINT session_power_limit_positive CHECK (power_limit_kw IS NULL OR power_limit_kw > 0);

UPDATE alembic_version SET version_num='c3a9e5f1d204' WHERE alembic_version.version_num = 'f2b7d4c8a1e6';

COMMIT;

