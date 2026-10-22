"""Limits: estimated store margin (``stations.store_min_kw``/``store_peak_kw``) replaces the simulated store load.

The store that hosts the chargers has no meter, so its consumption is no longer simulated as if it
were live: the owner sets a fixed ESTIMATE (typical minimum and peak) and the estimated peak is
reserved all the time (``chargegrid_core.site_load``): chargers = min(cap, contracted − peak).

* ``stations.store_min_kw`` / ``stations.store_peak_kw`` NUMERIC(10,3) NULL (NULL = 14–22 kW default).
* CHECKs: min >= 0; 0 <= peak <= 10000; min <= peak.
* Backfill keeps each station close to what it had:
  - rows with a building type/size get that type's typical peak × size and the lowest weekday
    fraction of the old curve as the minimum (``LEGACY_PROFILES`` / ``LEGACY_SIZES`` below);
  - with a contracted limit stored, the peak never exceeds 85 % of it (the old simulated load had
    the same ceiling), so no station ends up with nothing left for the chargers;
  - rows with only a small contracted limit (< 22 kW / 0.85) get the default store clamped the same way.
* ``building_profile``, ``building_size`` and ``building_load_*`` are left untouched (unused,
  dropped in a later migration) so a rollback of the API keeps working.

Downgrade drops the two columns and their CHECKs.

Revision ID: d8b3f6a2c5e7
Revises: e2c7a9d4f6b3
"""

import sqlalchemy as sa
from alembic import op

revision = "d8b3f6a2c5e7"
down_revision = "e2c7a9d4f6b3"
branch_labels = None
depends_on = None

# Old simulated curves (chargegrid_core.site_load before this revision): typical peak (medium size,
# summer weekday) and the lowest weekday fraction of that peak.
LEGACY_PROFILES = {
    "conveniencia": ("22", "0.62"),
    "farmacia": ("12", "0.21"),
    "padaria": ("45", "0.30"),
    "supermercado": ("100", "0.56"),
    "restaurante": ("30", "0.17"),
    "shopping": ("750", "0.21"),
}
LEGACY_SIZES = {"pequeno": "0.6", "medio": "1", "grande": "1.6"}
RESERVE_SHARE = "0.85"
DEFAULT_MIN_KW = "14"
DEFAULT_PEAK_KW = "22"


def backfill_sql() -> str:
    profiles = ", ".join(f"('{key}', {peak}, {share})" for key, (peak, share) in LEGACY_PROFILES.items())
    sizes = ", ".join(f"('{key}', {factor})" for key, factor in LEGACY_SIZES.items())
    keys = ", ".join(f"'{key}'" for key in LEGACY_PROFILES)
    size_keys = ", ".join(f"'{key}'" for key in LEGACY_SIZES)
    return f"""
        UPDATE stations AS target
        SET store_peak_kw = estimate.peak, store_min_kw = LEAST(estimate.low, estimate.peak)
        FROM (
            SELECT st.id,
                   CASE WHEN st.site_limit_kw IS NULL THEN raw.peak
                        ELSE LEAST(raw.peak, FLOOR(st.site_limit_kw * {RESERVE_SHARE} * 10) / 10) END AS peak,
                   CASE WHEN st.building_profile IS NULL AND st.building_size IS NULL THEN {DEFAULT_MIN_KW}
                        ELSE raw.low END AS low
            FROM stations AS st
            JOIN LATERAL (
                SELECT ROUND(p.peak * z.factor, 1) AS peak,
                       ROUND(ROUND(p.peak * z.factor, 1) * p.min_share, 1) AS low
                FROM (VALUES {profiles}) AS p(key, peak, min_share),
                     (VALUES {sizes}) AS z(key, factor)
                WHERE p.key = CASE WHEN st.building_profile IN ({keys}) THEN st.building_profile
                                   ELSE 'conveniencia' END
                  AND z.key = CASE WHEN st.building_size IN ({size_keys}) THEN st.building_size
                                   ELSE 'medio' END
            ) AS raw ON TRUE
            WHERE st.building_profile IS NOT NULL OR st.building_size IS NOT NULL
               OR (st.site_limit_kw IS NOT NULL AND st.site_limit_kw * {RESERVE_SHARE} < {DEFAULT_PEAK_KW})
        ) AS estimate
        WHERE target.id = estimate.id
    """


def upgrade():
    op.add_column("stations", sa.Column("store_min_kw", sa.Numeric(10, 3), nullable=True))
    op.add_column("stations", sa.Column("store_peak_kw", sa.Numeric(10, 3), nullable=True))
    op.execute(backfill_sql())
    op.create_check_constraint("station_store_min_range", "stations", "store_min_kw IS NULL OR store_min_kw >= 0")
    op.create_check_constraint("station_store_peak_range", "stations",
                               "store_peak_kw IS NULL OR (store_peak_kw >= 0 AND store_peak_kw <= 10000)")
    op.create_check_constraint("station_store_min_le_peak", "stations",
                               "store_min_kw IS NULL OR store_peak_kw IS NULL OR store_min_kw <= store_peak_kw")


def downgrade():
    for name in ("station_store_min_le_peak", "station_store_peak_range", "station_store_min_range"):
        op.drop_constraint(name, "stations", type_="check")
    op.drop_column("stations", "store_peak_kw")
    op.drop_column("stations", "store_min_kw")
