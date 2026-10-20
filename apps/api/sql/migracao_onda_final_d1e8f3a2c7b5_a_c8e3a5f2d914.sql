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

-- Running upgrade b6d2f9a4c8e1 -> e5a1c7f3b9d2

ALTER TABLE stations ADD COLUMN prepay_required BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE stations ADD COLUMN kiosk_payments BOOLEAN DEFAULT false NOT NULL;

CREATE TABLE payments (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    connector_id UUID NOT NULL, 
    session_id UUID, 
    origin VARCHAR(10) NOT NULL, 
    provider VARCHAR(20) NOT NULL, 
    environment VARCHAR(10) NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    settlement_status VARCHAR(20) NOT NULL, 
    amount_cents INTEGER NOT NULL, 
    energy_cap_cents INTEGER NOT NULL, 
    fixed_fee_cents INTEGER NOT NULL, 
    overstay_reserve_cents INTEGER NOT NULL, 
    energy_cents INTEGER, 
    overstay_cents INTEGER, 
    charge_cents INTEGER, 
    waived_cents INTEGER NOT NULL, 
    uncollected_cents INTEGER NOT NULL, 
    captured_cents INTEGER NOT NULL, 
    refunded_cents INTEGER NOT NULL, 
    provider_fee_cents INTEGER, 
    price_per_kwh NUMERIC(10, 4) NOT NULL, 
    base_price_per_kwh NUMERIC(10, 4) NOT NULL, 
    demand_multiplier NUMERIC(4, 2) NOT NULL, 
    discount_percent INTEGER NOT NULL, 
    coupon_code VARCHAR(50), 
    max_duration_minutes INTEGER NOT NULL, 
    max_power_kw NUMERIC(10, 3), 
    quote JSONB NOT NULL, 
    provider_checkout_id VARCHAR(100), 
    provider_payment_intent_id VARCHAR(100), 
    provider_status VARCHAR(40), 
    method VARCHAR(30), 
    checkout_url TEXT, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    start_deadline TIMESTAMP WITH TIME ZONE, 
    authorized_at TIMESTAMP WITH TIME ZONE, 
    settled_at TIMESTAMP WITH TIME ZONE, 
    last_provider_check_at TIMESTAMP WITH TIME ZONE, 
    settle_attempts INTEGER NOT NULL, 
    last_error VARCHAR(200), 
    kiosk_token_hash VARCHAR(64), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT payment_origin CHECK (origin IN ('app', 'kiosk')), 
    CONSTRAINT payment_environment_test CHECK (environment = 'test'), 
    CONSTRAINT payment_status CHECK (status IN ('awaiting_payment', 'declined', 'authorized', 'paid', 'in_use', 'expired', 'canceled', 'completed')), 
    CONSTRAINT payment_settlement_status CHECK (settlement_status IN ('none', 'due', 'settling', 'done', 'failed')), 
    CONSTRAINT payment_amounts CHECK (amount_cents > 0 AND energy_cap_cents > 0 AND fixed_fee_cents >= 0 AND overstay_reserve_cents >= 0 AND amount_cents = energy_cap_cents + fixed_fee_cents + overstay_reserve_cents), 
    CONSTRAINT payment_settlement_amounts CHECK (captured_cents >= 0 AND refunded_cents >= 0 AND waived_cents >= 0 AND uncollected_cents >= 0 AND captured_cents <= amount_cents AND refunded_cents <= captured_cents AND (charge_cents IS NULL OR charge_cents BETWEEN 0 AND amount_cents)), 
    CONSTRAINT payment_discount_range CHECK (discount_percent BETWEEN 0 AND 100), 
    FOREIGN KEY(user_id) REFERENCES profiles (id), 
    FOREIGN KEY(connector_id) REFERENCES connectors (id), 
    UNIQUE (session_id), 
    FOREIGN KEY(session_id) REFERENCES charging_sessions (id), 
    UNIQUE (provider_checkout_id), 
    UNIQUE (provider_payment_intent_id)
);

CREATE INDEX ix_payments_user_id ON payments (user_id);

CREATE INDEX ix_payments_connector_status ON payments (connector_id, status);

CREATE INDEX ix_payments_settlement ON payments (settlement_status) WHERE settlement_status IN ('due', 'settling');

CREATE UNIQUE INDEX one_open_app_payment_user ON payments (user_id) WHERE origin = 'app' AND status IN ('awaiting_payment', 'declined', 'authorized', 'paid');

ALTER TABLE payments ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE ON TABLE payments TO chargegrid_api;

CREATE POLICY api_only ON payments FOR ALL TO chargegrid_api USING (true) WITH CHECK (true);

DO $$ BEGIN
        EXECUTE 'REVOKE ALL ON TABLE payments FROM PUBLIC';
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
          EXECUTE 'REVOKE ALL ON TABLE payments FROM anon';
        END IF;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
          EXECUTE 'REVOKE ALL ON TABLE payments FROM authenticated';
        END IF;
        END $$;

CREATE TABLE payment_events (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY, 
    provider VARCHAR(20) NOT NULL, 
    event_id VARCHAR(100) NOT NULL, 
    type VARCHAR(80) NOT NULL, 
    payment_id UUID, 
    payload_sha256 VARCHAR(64) NOT NULL, 
    received_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (provider, event_id), 
    FOREIGN KEY(payment_id) REFERENCES payments (id)
);

CREATE INDEX ix_payment_events_payment_id ON payment_events (payment_id);

ALTER TABLE payment_events ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE ON TABLE payment_events TO chargegrid_api;

GRANT USAGE ON SEQUENCE payment_events_id_seq TO chargegrid_api;

CREATE POLICY api_only ON payment_events FOR ALL TO chargegrid_api USING (true) WITH CHECK (true);

DO $$ BEGIN
        EXECUTE 'REVOKE ALL ON TABLE payment_events FROM PUBLIC';
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
          EXECUTE 'REVOKE ALL ON TABLE payment_events FROM anon';
        END IF;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
          EXECUTE 'REVOKE ALL ON TABLE payment_events FROM authenticated';
        END IF;
        END $$;

UPDATE alembic_version SET version_num='e5a1c7f3b9d2' WHERE alembic_version.version_num = 'b6d2f9a4c8e1';

-- Running upgrade e5a1c7f3b9d2 -> b7d2f4a91c36

ALTER TABLE stations ADD COLUMN site_limit_kw NUMERIC(10, 3);

ALTER TABLE stations ADD COLUMN building_load_kw NUMERIC(10, 3);

ALTER TABLE stations ADD COLUMN building_load_source VARCHAR(20);

ALTER TABLE stations ADD COLUMN building_load_updated_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE stations ADD COLUMN rebalance_enabled BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE stations ADD CONSTRAINT station_site_limit_positive CHECK (site_limit_kw IS NULL OR site_limit_kw > 0);

ALTER TABLE stations ADD CONSTRAINT station_building_load_range CHECK (building_load_kw IS NULL OR building_load_kw >= 0);

ALTER TABLE stations ADD CONSTRAINT station_building_load_source CHECK (building_load_source IS NULL OR building_load_source IN ('simulated'));

ALTER TABLE devices ADD COLUMN capabilities JSONB DEFAULT '[]'::jsonb NOT NULL;

ALTER TABLE devices ADD COLUMN charger JSONB;

ALTER TABLE charging_sessions ADD COLUMN requested_power_kw NUMERIC(10, 3);

ALTER TABLE charging_sessions ADD COLUMN target_power_kw NUMERIC(10, 3);

ALTER TABLE charging_sessions ADD COLUMN applied_power_kw NUMERIC(10, 3);

ALTER TABLE charging_sessions ADD COLUMN power_state VARCHAR(20);

ALTER TABLE charging_sessions ADD COLUMN power_reason VARCHAR(300);

ALTER TABLE charging_sessions ADD COLUMN power_reason_short VARCHAR(60);

ALTER TABLE charging_sessions ADD COLUMN power_reason_code VARCHAR(30);

ALTER TABLE charging_sessions ADD COLUMN power_decision_id BIGINT;

ALTER TABLE charging_sessions ADD CONSTRAINT session_power_state CHECK (power_state IS NULL OR power_state IN ('applied','reducing','raising','waiting','paused','fixed'));

ALTER TABLE charging_sessions ADD CONSTRAINT session_applied_power_range CHECK (applied_power_kw IS NULL OR applied_power_kw >= 0);

ALTER TABLE session_events ADD COLUMN data JSONB;

CREATE TABLE power_decisions (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY, 
    station_id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    trigger VARCHAR(40) NOT NULL, 
    inputs JSONB NOT NULL, 
    available_kw NUMERIC(10, 3), 
    exceeded_kw NUMERIC(10, 3) NOT NULL, 
    summary VARCHAR(300) NOT NULL, 
    input_hash VARCHAR(64) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(station_id) REFERENCES stations (id)
);

CREATE INDEX ix_power_decisions_station_created ON power_decisions (station_id, created_at);

ALTER TABLE power_decisions ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
        REVOKE ALL ON TABLE power_decisions FROM PUBLIC;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
          REVOKE ALL ON TABLE power_decisions FROM anon;
        END IF;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
          REVOKE ALL ON TABLE power_decisions FROM authenticated;
        END IF;
        END $$;

GRANT SELECT, INSERT ON TABLE power_decisions TO chargegrid_api;

GRANT USAGE ON SEQUENCE power_decisions_id_seq TO chargegrid_api;

CREATE POLICY api_only ON power_decisions FOR ALL TO chargegrid_api USING (true) WITH CHECK (true);

UPDATE alembic_version SET version_num='b7d2f4a91c36' WHERE alembic_version.version_num = 'e5a1c7f3b9d2';

-- Running upgrade b7d2f4a91c36 -> c5f0a7e3d912

CREATE TABLE connector_hourly_stats (
    connector_id UUID NOT NULL, 
    hour_start TIMESTAMP WITH TIME ZONE NOT NULL, 
    origin VARCHAR(12) NOT NULL, 
    busy_seconds INTEGER DEFAULT '0' NOT NULL, 
    energy_wh NUMERIC(16, 3) DEFAULT '0' NOT NULL, 
    energy_basis VARCHAR(16) NOT NULL, 
    sessions_started INTEGER DEFAULT '0' NOT NULL, 
    max_power_w NUMERIC(12, 1), 
    generator VARCHAR(20), 
    computed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (connector_id, hour_start, origin), 
    CONSTRAINT hourly_stats_origin CHECK (origin IN ('measured', 'simulated', 'synthetic')), 
    CONSTRAINT hourly_stats_basis CHECK (energy_basis IN ('telemetry', 'session_spread', 'synthetic')), 
    CONSTRAINT hourly_stats_ranges CHECK (busy_seconds BETWEEN 0 AND 3600 AND energy_wh >= 0 AND sessions_started >= 0), 
    CONSTRAINT hourly_stats_hour_aligned CHECK (mod(CAST(EXTRACT(EPOCH FROM hour_start) AS bigint), 3600) = 0), 
    FOREIGN KEY(connector_id) REFERENCES connectors (id)
);

CREATE INDEX ix_connector_hourly_stats_hour ON connector_hourly_stats (hour_start);

CREATE TABLE aggregate_watermarks (
    name VARCHAR(50) NOT NULL, 
    rolled_until TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (name)
);

ALTER TABLE connector_hourly_stats ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE connector_hourly_stats TO chargegrid_api;

CREATE POLICY api_only ON connector_hourly_stats FOR ALL TO chargegrid_api USING (true) WITH CHECK (true);

REVOKE ALL ON TABLE connector_hourly_stats FROM PUBLIC;

ALTER TABLE aggregate_watermarks ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE aggregate_watermarks TO chargegrid_api;

CREATE POLICY api_only ON aggregate_watermarks FOR ALL TO chargegrid_api USING (true) WITH CHECK (true);

REVOKE ALL ON TABLE aggregate_watermarks FROM PUBLIC;

DO $$ DECLARE table_name text; BEGIN
        FOREACH table_name IN ARRAY string_to_array('connector_hourly_stats,aggregate_watermarks', ',') LOOP
          IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
            EXECUTE 'REVOKE ALL ON TABLE ' || quote_ident(table_name) || ' FROM anon';
          END IF;
          IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
            EXECUTE 'REVOKE ALL ON TABLE ' || quote_ident(table_name) || ' FROM authenticated';
          END IF;
        END LOOP; END $$;

UPDATE alembic_version SET version_num='c5f0a7e3d912' WHERE alembic_version.version_num = 'b7d2f4a91c36';

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

