BEGIN;

-- Running upgrade e2c7a9d4f6b3 -> d8b3f6a2c5e7

ALTER TABLE stations ADD COLUMN store_min_kw NUMERIC(10, 3);

ALTER TABLE stations ADD COLUMN store_peak_kw NUMERIC(10, 3);

UPDATE stations AS target
        SET store_peak_kw = estimate.peak, store_min_kw = LEAST(estimate.low, estimate.peak)
        FROM (
            SELECT st.id,
                   CASE WHEN st.site_limit_kw IS NULL THEN raw.peak
                        ELSE LEAST(raw.peak, FLOOR(st.site_limit_kw * 0.85 * 10) / 10) END AS peak,
                   CASE WHEN st.building_profile IS NULL AND st.building_size IS NULL THEN 14
                        ELSE raw.low END AS low
            FROM stations AS st
            JOIN LATERAL (
                SELECT ROUND(p.peak * z.factor, 1) AS peak,
                       ROUND(ROUND(p.peak * z.factor, 1) * p.min_share, 1) AS low
                FROM (VALUES ('conveniencia', 22, 0.62), ('farmacia', 12, 0.21), ('padaria', 45, 0.30), ('supermercado', 100, 0.56), ('restaurante', 30, 0.17), ('shopping', 750, 0.21)) AS p(key, peak, min_share),
                     (VALUES ('pequeno', 0.6), ('medio', 1), ('grande', 1.6)) AS z(key, factor)
                WHERE p.key = CASE WHEN st.building_profile IN ('conveniencia', 'farmacia', 'padaria', 'supermercado', 'restaurante', 'shopping') THEN st.building_profile
                                   ELSE 'conveniencia' END
                  AND z.key = CASE WHEN st.building_size IN ('pequeno', 'medio', 'grande') THEN st.building_size
                                   ELSE 'medio' END
            ) AS raw ON TRUE
            WHERE st.building_profile IS NOT NULL OR st.building_size IS NOT NULL
               OR (st.site_limit_kw IS NOT NULL AND st.site_limit_kw * 0.85 < 22)
        ) AS estimate
        WHERE target.id = estimate.id;

ALTER TABLE stations ADD CONSTRAINT station_store_min_range CHECK (store_min_kw IS NULL OR store_min_kw >= 0);

ALTER TABLE stations ADD CONSTRAINT station_store_peak_range CHECK (store_peak_kw IS NULL OR (store_peak_kw >= 0 AND store_peak_kw <= 10000));

ALTER TABLE stations ADD CONSTRAINT station_store_min_le_peak CHECK (store_min_kw IS NULL OR store_peak_kw IS NULL OR store_min_kw <= store_peak_kw);

UPDATE alembic_version SET version_num='d8b3f6a2c5e7' WHERE alembic_version.version_num = 'e2c7a9d4f6b3';

COMMIT;

