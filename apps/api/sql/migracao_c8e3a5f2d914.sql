BEGIN;

-- Running upgrade c5f0a7e3d912 -> c8e3a5f2d914

ALTER TABLE charging_sessions ADD COLUMN overstay_terms JSONB;

ALTER TABLE charging_sessions ADD COLUMN overstay_started_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE charging_sessions ADD COLUMN overstay_last_connected_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE charging_sessions ADD COLUMN overstay_billable_seconds INTEGER DEFAULT 0 NOT NULL;

ALTER TABLE charging_sessions ADD COLUMN overstay_ended_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE charging_sessions ADD COLUMN overstay_end_reason VARCHAR(30);

ALTER TABLE charging_sessions ADD COLUMN overstay_fee NUMERIC(12, 4) DEFAULT 0 NOT NULL;

ALTER TABLE charging_sessions ADD CONSTRAINT session_overstay_amounts CHECK (overstay_billable_seconds >= 0 AND overstay_fee >= 0);

ALTER TABLE charging_sessions ADD CONSTRAINT session_overstay_order CHECK (overstay_ended_at IS NULL OR overstay_started_at IS NOT NULL);

ALTER TABLE charging_sessions ADD CONSTRAINT session_overstay_end_reason CHECK (overstay_end_reason IS NULL OR overstay_end_reason IN ('disconnected', 'device_reboot', 'observation_lost', 'owner_waived'));

CREATE UNIQUE INDEX one_open_overstay_connector ON charging_sessions (connector_id) WHERE overstay_started_at IS NOT NULL AND overstay_ended_at IS NULL;

CREATE INDEX ix_open_overstay_user ON charging_sessions (user_id) WHERE overstay_started_at IS NOT NULL AND overstay_ended_at IS NULL;

UPDATE stations SET pricing = jsonb_set(pricing, '{rotation,enabled}', 'false'::jsonb) WHERE jsonb_typeof(pricing->'rotation') = 'object' AND NOT (pricing->'rotation' ? 'max_amount');

UPDATE alembic_version SET version_num='c8e3a5f2d914' WHERE alembic_version.version_num = 'c5f0a7e3d912';

COMMIT;

