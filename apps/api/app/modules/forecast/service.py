"""Leitura da série horária de um posto e montagem das respostas de previsão.

A série junta os agregados duráveis (``connector_hourly_stats``) até a marca d'água e as
horas mais recentes calculadas na hora com o mesmo agregador; nada é gravado na leitura.
Todo o cálculo de previsão, métricas e sugestões é ``chargegrid_core.forecast.engine``.
"""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from chargegrid_core import pricing
from chargegrid_core.forecast import engine
from chargegrid_core.forecast.aggregate import floor_hour
from chargegrid_core.forecast.calendar import to_local, to_utc
from chargegrid_core.forecast.series import build_series

from ...http_helpers import retired_ids
from ...models import ChargingSession, Connector, ConnectorHourlyStats, now
from ..pricing.service import station_demand
from .rollup import compute_rows, watermark

HISTORY_WEEKS = 8


def points(db, station):
    """Conectores publicados do posto (ativos e não aposentados por reset de fábrica)."""
    connectors = db.scalars(select(Connector).where(Connector.station_id == station.id, Connector.active.is_(True))
                            .order_by(Connector.public_code)).all()
    retired = retired_ids(db, [point.id for point in connectors])
    return [point for point in connectors if point.id not in retired]


def connector_info(connectors) -> list[dict]:
    return [{"id": str(point.id), "public_code": point.public_code, "price_per_kwh": Decimal(point.price_per_kwh),
             "power_kw": float(point.power_limit_kw or point.power_kw)} for point in connectors]


def station_series(db, station, current=None, weeks: int = HISTORY_WEEKS):
    """``(StationSeries até a última hora fechada, hora local atual)``."""
    current = current or now()
    end_local = floor_hour(to_local(current))
    start_local = end_local - timedelta(weeks=weeks)
    start, end = to_utc(start_local), to_utc(end_local)
    all_ids = list(db.scalars(select(Connector.id).where(Connector.station_id == station.id)))
    connectors = points(db, station)
    mark = watermark(db)
    live_from = max(start, min(mark.rolled_until, end)) if mark is not None else start
    rows = [dict(row._mapping) for row in db.execute(
        select(ConnectorHourlyStats.connector_id, ConnectorHourlyStats.hour_start, ConnectorHourlyStats.origin,
               ConnectorHourlyStats.busy_seconds, ConnectorHourlyStats.energy_wh)
        .where(ConnectorHourlyStats.connector_id.in_(all_ids), ConnectorHourlyStats.hour_start >= start,
               ConnectorHourlyStats.hour_start < end,
               (ConnectorHourlyStats.origin == "synthetic") | (ConnectorHourlyStats.hour_start < live_from))
    )] if all_ids else []
    if live_from < end:
        rows += compute_rows(db, live_from, end, current, all_ids)
    first_session = db.scalar(select(func.min(ChargingSession.started_at))
                              .where(ChargingSession.connector_id.in_(all_ids))) if all_ids else None
    history_start = max(start_local, to_local(floor_hour(first_session))) if first_session else None
    series = build_series(rows, max(1, len(connectors)), start_local, end_local, history_start)
    return series, to_local(current), connectors


def now_price(db, station, connectors) -> Decimal | None:
    """Menor preço por kWh agora (o mesmo que o motorista vê na tela do posto)."""
    if not connectors:
        return None
    status = station_demand(db, station)
    return min(pricing.connector_price(status, point.id, point.price_per_kwh)[1] for point in connectors)


def owner_forecast(db, station, horizon: int) -> dict:
    series, local_now, connectors = station_series(db, station)
    payload = engine.station_forecast(series, local_now, rules=station.pricing, connectors=connector_info(connectors),
                                      horizon=horizon)
    return {"station_id": str(station.id), "generated_at": now().isoformat(), **payload}


def owner_history(db, station, weeks: int) -> dict:
    series, _, _ = station_series(db, station, weeks=weeks)
    return {"station_id": str(station.id), "generated_at": now().isoformat(),
            **engine.occupancy_history(series, weeks)}


def best_times(db, station, hours: int) -> dict:
    series, local_now, connectors = station_series(db, station, weeks=5)
    payload = engine.station_best_times(series, local_now, rules=station.pricing,
                                        connectors=connector_info(connectors),
                                        now_price=now_price(db, station, connectors), hours=hours)
    return {"station_id": str(station.id), "generated_at": now().isoformat(), **payload}
