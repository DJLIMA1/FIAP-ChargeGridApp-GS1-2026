BEGIN;

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

COMMIT;

