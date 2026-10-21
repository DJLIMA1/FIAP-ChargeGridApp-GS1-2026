BEGIN;

-- Running upgrade f4b9d2c7e1a3 -> a3e8c5d1f7b9

ALTER TABLE stations ADD COLUMN building_profile VARCHAR(20);

ALTER TABLE stations ADD COLUMN building_size VARCHAR(10);

ALTER TABLE stations ALTER COLUMN rebalance_enabled SET DEFAULT true;

UPDATE stations SET rebalance_enabled = true WHERE rebalance_enabled IS DISTINCT FROM true;

UPDATE stations SET prepay_required = false, kiosk_payments = false WHERE prepay_required OR kiosk_payments;

UPDATE alembic_version SET version_num='a3e8c5d1f7b9' WHERE alembic_version.version_num = 'f4b9d2c7e1a3';

COMMIT;

