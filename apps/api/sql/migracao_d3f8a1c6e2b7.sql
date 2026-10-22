BEGIN;

-- Running upgrade c5e9a2d7f4b1 -> d3f8a1c6e2b7

ALTER TABLE devices ADD COLUMN parent_device_id UUID;

ALTER TABLE devices ADD CONSTRAINT devices_parent_device_id_fkey FOREIGN KEY(parent_device_id) REFERENCES devices (id);

CREATE INDEX ix_devices_parent_device_id ON devices (parent_device_id);

ALTER TABLE devices ADD CONSTRAINT device_parent_not_self CHECK (parent_device_id IS NULL OR parent_device_id <> id);

UPDATE alembic_version SET version_num='d3f8a1c6e2b7' WHERE alembic_version.version_num = 'c5e9a2d7f4b1';

COMMIT;

