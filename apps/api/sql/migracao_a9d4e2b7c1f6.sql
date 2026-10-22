BEGIN;

-- Running upgrade d8b3f6a2c5e7 -> a9d4e2b7c1f6

ALTER TABLE stations ADD COLUMN removed_at TIMESTAMP WITH TIME ZONE;

UPDATE alembic_version SET version_num='a9d4e2b7c1f6' WHERE alembic_version.version_num = 'd8b3f6a2c5e7';

COMMIT;

