BEGIN;

-- Running upgrade c8e3a5f2d914 -> f4b9d2c7e1a3

ALTER TABLE profiles ADD COLUMN presentation_mode BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE stations ADD COLUMN kiosk_mode BOOLEAN DEFAULT false NOT NULL;

CREATE TABLE kiosk_orders (
    id UUID NOT NULL, 
    connector_id UUID NOT NULL, 
    guest_id UUID NOT NULL, 
    payment_id UUID, 
    session_id UUID, 
    status VARCHAR(20) NOT NULL, 
    method VARCHAR(20) NOT NULL, 
    mode VARCHAR(10) NOT NULL, 
    quote JSONB NOT NULL, 
    quote_hash VARCHAR(64) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE, 
    token_salt VARCHAR(32) NOT NULL, 
    token_hash VARCHAR(64) NOT NULL, 
    last_error VARCHAR(200), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    closed_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    CONSTRAINT kiosk_order_status CHECK (status IN ('held', 'awaiting_payment', 'paid', 'charging', 'finished', 'canceled', 'expired', 'failed')), 
    CONSTRAINT kiosk_order_method CHECK (method IN ('simulated', 'stripe')), 
    CONSTRAINT kiosk_order_mode CHECK (mode IN ('value', 'time', 'energy')), 
    FOREIGN KEY(connector_id) REFERENCES connectors (id), 
    FOREIGN KEY(guest_id) REFERENCES profiles (id), 
    UNIQUE (payment_id), 
    FOREIGN KEY(payment_id) REFERENCES payments (id), 
    UNIQUE (session_id), 
    FOREIGN KEY(session_id) REFERENCES charging_sessions (id)
);

CREATE INDEX ix_kiosk_orders_connector_created ON kiosk_orders (connector_id, created_at);

CREATE UNIQUE INDEX one_open_kiosk_order_connector ON kiosk_orders (connector_id) WHERE status IN ('held', 'awaiting_payment', 'paid');

ALTER TABLE kiosk_orders ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE ON TABLE kiosk_orders TO chargegrid_api;

CREATE POLICY api_only ON kiosk_orders FOR ALL TO chargegrid_api USING (true) WITH CHECK (true);

DO $$ BEGIN
        EXECUTE 'REVOKE ALL ON TABLE kiosk_orders FROM PUBLIC';
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
          EXECUTE 'REVOKE ALL ON TABLE kiosk_orders FROM anon';
        END IF;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
          EXECUTE 'REVOKE ALL ON TABLE kiosk_orders FROM authenticated';
        END IF;
        END $$;

UPDATE alembic_version SET version_num='f4b9d2c7e1a3' WHERE alembic_version.version_num = 'c8e3a5f2d914';

COMMIT;

