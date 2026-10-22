BEGIN;

-- Running upgrade e2c7a9d4f6b3 -> c4f1a8e6d2b9

ALTER TABLE devices ADD COLUMN created_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE devices ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE devices ADD COLUMN revoked_at TIMESTAMP WITH TIME ZONE;

CREATE OR REPLACE FUNCTION device_revoked_at() RETURNS trigger AS $$
        BEGIN
            IF NEW.revoked AND NEW.revoked_at IS NULL AND (TG_OP = 'INSERT' OR NOT OLD.revoked) THEN
                NEW.revoked_at := now();
            END IF;
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;

CREATE TRIGGER device_revoked_at BEFORE INSERT OR UPDATE OF revoked ON devices
        FOR EACH ROW EXECUTE FUNCTION device_revoked_at();

CREATE TABLE central_rent_rates (
    id UUID NOT NULL, 
    station_id UUID, 
    monthly_amount NUMERIC(10, 2), 
    effective_from DATE NOT NULL, 
    note VARCHAR(200), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT central_rent_amount_range CHECK (monthly_amount IS NULL OR monthly_amount BETWEEN 0 AND 10000), 
    CONSTRAINT central_rent_default_amount CHECK (station_id IS NOT NULL OR monthly_amount IS NOT NULL), 
    FOREIGN KEY(station_id) REFERENCES stations (id)
);

CREATE INDEX ix_central_rent_rates_station_id ON central_rent_rates (station_id);

CREATE UNIQUE INDEX uq_central_rent_default ON central_rent_rates (effective_from) WHERE station_id IS NULL;

CREATE UNIQUE INDEX uq_central_rent_station ON central_rent_rates (station_id, effective_from) WHERE station_id IS NOT NULL;

UPDATE alembic_version SET version_num='c4f1a8e6d2b9' WHERE alembic_version.version_num = 'e2c7a9d4f6b3';

COMMIT;

