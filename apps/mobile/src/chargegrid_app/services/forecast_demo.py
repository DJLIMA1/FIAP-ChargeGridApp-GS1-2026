"""Previsão na conta demo (sem rede): mesmo ``chargegrid_core.forecast`` da API.

A série vem do histórico fictício de 30 dias de ``demo_owner`` (rotulado como sintético)
mais as sessões feitas durante a demonstração, agregadas pelo mesmo agregador da API.
"""

from datetime import timedelta
from decimal import Decimal

from chargegrid_core import pricing
from chargegrid_core.forecast import engine
from chargegrid_core.forecast.aggregate import floor_hour, hourly_rows, parse_time
from chargegrid_core.forecast.calendar import to_local, to_utc
from chargegrid_core.forecast.series import build_series

HISTORY_WEEKS = 8


def _points(api, station_id):
    return [p for p in api._points.values() if p['station_id'] == station_id and p['active'] and not p.get('retired')]


def station_series(api, station_id, weeks=HISTORY_WEEKS):
    from ..demo_owner import owner_for

    all_ids = {p['id'] for p in api._points.values() if p['station_id'] == station_id}
    points = _points(api, station_id)
    now = api._now()
    end_local = floor_hour(to_local(now))
    start_local = end_local - timedelta(weeks=weeks)
    start, end = to_utc(start_local), to_utc(end_local)
    history, _, _ = owner_for(api).history()
    fictional = [s for s in history if s['connector_id'] in all_ids]
    live = [s for s in api._sessions.values() if s['connector_id'] in all_ids]
    rows = hourly_rows(fictional, [], start, end, now, origin='synthetic') + hourly_rows(live, [], start, end, now)
    starts = [parse_time(s.get('started_at')) for s in fictional + live if s.get('started_at')]
    history_start = max(start_local, to_local(floor_hour(min(starts)))) if starts else None
    series = build_series(rows, max(1, len(points)), start_local, end_local, history_start)
    connectors = [{'id': p['id'], 'public_code': p['public_code'], 'price_per_kwh': Decimal(str(p['price_per_kwh'])),
                   'power_kw': float(p.get('power_limit_kw') or p['power_kw'])} for p in points]
    return series, to_local(now), connectors


def forecast(api, station_id, horizon=36):
    series, local_now, connectors = station_series(api, station_id)
    payload = engine.station_forecast(series, local_now, rules=api._pricing.get(station_id), connectors=connectors,
                                      horizon=horizon)
    return {'station_id': station_id, 'generated_at': api._now().isoformat(), **payload}


def history(api, station_id, weeks=4):
    series, _, _ = station_series(api, station_id, weeks)
    return {'station_id': station_id, 'generated_at': api._now().isoformat(), **engine.occupancy_history(series, weeks)}


def best_times(api, station_id, hours=12):
    station = api._get(api._stations, station_id, 'Posto não encontrado.')
    series, local_now, connectors = station_series(api, station_id, 5)
    status = api._demand(station)
    now_price = min((pricing.connector_price(status, c['id'], c['price_per_kwh'])[1] for c in connectors), default=None)
    payload = engine.station_best_times(series, local_now, rules=api._pricing.get(station_id), connectors=connectors,
                                        now_price=now_price, hours=hours)
    return {'station_id': station_id, 'generated_at': api._now().isoformat(), **payload}
