BEGIN;

-- Running upgrade d3f8a1c6e2b7 -> b6d2e8f1a490

CREATE TABLE simulated_wallets (
    user_id UUID NOT NULL, 
    balance_cents INTEGER DEFAULT '0' NOT NULL, 
    legacy_imported BOOLEAN DEFAULT false NOT NULL, 
    transactions JSONB DEFAULT '[]'::jsonb NOT NULL, 
    PRIMARY KEY (user_id), 
    CONSTRAINT simulated_wallet_nonnegative CHECK (balance_cents >= 0), 
    FOREIGN KEY(user_id) REFERENCES profiles (id)
);

ALTER TABLE simulated_wallets ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON simulated_wallets FROM PUBLIC;

DO $$ BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
            REVOKE ALL ON simulated_wallets FROM anon;
        END IF;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
            REVOKE ALL ON simulated_wallets FROM authenticated;
        END IF;
    END $$;

GRANT SELECT, INSERT, UPDATE ON simulated_wallets TO chargegrid_api;

CREATE POLICY api_only ON simulated_wallets FOR ALL TO chargegrid_api USING (true) WITH CHECK (true);

UPDATE alembic_version SET version_num='b6d2e8f1a490' WHERE alembic_version.version_num = 'd3f8a1c6e2b7';

COMMIT;

