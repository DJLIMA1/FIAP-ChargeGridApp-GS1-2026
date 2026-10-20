"""Rollup idempotente dos agregados horários (``connector_hourly_stats``).

Roda dentro do keepalive diário (``/internal/keepalive``): recalcula as horas fechadas
desde ``rolled_until − 72 h`` (absorve sessões encerradas tarde e telemetria de um
equipamento que ficou offline), troca as linhas medidas/simuladas dessas horas e avança
a marca d'água. Linhas sintéticas (seed de demonstração) nunca são tocadas aqui.
A leitura (``service``) calcula na hora as horas posteriores à marca, sem gravar.
"""

import uuid
from datetime import timedelta

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import insert

from chargegrid_core.forecast.aggregate import floor_hour, hourly_rows

from ...models import AggregateWatermark, ChargingSession, ConnectorHourlyStats, Telemetry, now

WATERMARK = "connector_hourly_stats"
MARGIN = timedelta(hours=72)
CLOSE_DELAY = timedelta(minutes=15)
CHUNK = timedelta(days=7)
MAX_BACKFILL = timedelta(days=400)


def closed_until(moment):
    """Última virada de hora já fechada (com folga para sincronizações atrasadas)."""
    return floor_hour(moment - CLOSE_DELAY)


def compute_rows(db, start, end, current, connector_ids=None) -> list[dict]:
    """Linhas de ``hourly_rows`` para ``[start, end)`` a partir de sessões e telemetria do banco.

    A ocupação inclui a permanência: ``[ended_at, overstay_ended_at)`` ou, aberta, até
    ``overstay_last_connected_at`` (``chargegrid_core.forecast.aggregate.occupied_until``).
    """
    query = select(
        ChargingSession.id, ChargingSession.connector_id, ChargingSession.status, ChargingSession.started_at,
        ChargingSession.ended_at, ChargingSession.energy_wh, ChargingSession.source,
        ChargingSession.last_measurement_at, ChargingSession.overstay_started_at,
        ChargingSession.overstay_ended_at, ChargingSession.overstay_last_connected_at,
    ).where(
        ChargingSession.started_at.is_not(None), ChargingSession.started_at < end,
        # A permanência (carro ainda conectado depois da recarga) ocupa a vaga até o unplug.
        or_(ChargingSession.ended_at.is_(None), ChargingSession.ended_at >= start,
            ChargingSession.overstay_ended_at >= start,
            and_(ChargingSession.overstay_started_at.is_not(None), ChargingSession.overstay_ended_at.is_(None),
                 ChargingSession.overstay_last_connected_at >= start)),
    )
    if connector_ids is not None:
        if not connector_ids:
            return []
        query = query.where(ChargingSession.connector_id.in_(connector_ids))
    sessions = [dict(row._mapping) for row in db.execute(query)]
    if not sessions:
        return []
    samples = []
    ids = [session["id"] for session in sessions]
    for offset in range(0, len(ids), 500):
        rows = db.execute(
            select(Telemetry.session_id, Telemetry.captured_at, Telemetry.data)
            .where(Telemetry.session_id.in_(ids[offset:offset + 500]))
        )
        for session_id, captured_at, data in rows:
            data = data or {}
            samples.append({"session_id": session_id, "captured_at": captured_at,
                            "energy_wh": data.get("energy_wh"), "power_w": data.get("power_w")})
    return hourly_rows(sessions, samples, start, end, current)


def _store(db, rows, start, end, connector_ids=None):
    condition = [ConnectorHourlyStats.hour_start >= start, ConnectorHourlyStats.hour_start < end,
                 ConnectorHourlyStats.origin != "synthetic"]
    if connector_ids is not None:
        condition.append(ConnectorHourlyStats.connector_id.in_(connector_ids))
    db.execute(delete(ConnectorHourlyStats).where(*condition))
    stamp = now()
    for offset in range(0, len(rows), 1000):
        db.execute(insert(ConnectorHourlyStats).values([
            {**row, "connector_id": uuid.UUID(str(row["connector_id"])), "generator": None, "computed_at": stamp}
            for row in rows[offset:offset + 1000]
        ]))


def watermark(db):
    return db.get(AggregateWatermark, WATERMARK)


def rollup(db, current=None, start=None) -> dict:
    """Fecha as horas até ``closed_until(current)``; idempotente (pode rodar de novo)."""
    current = current or now()
    end = closed_until(current)
    mark = watermark(db)
    if start is None:
        if mark is not None:
            start = min(mark.rolled_until, end) - MARGIN
        else:
            first = db.scalar(select(ChargingSession.started_at).where(ChargingSession.started_at.is_not(None))
                              .order_by(ChargingSession.started_at).limit(1))
            start = floor_hour(first) if first else end
    start = max(floor_hour(start), end - MAX_BACKFILL)
    total = 0
    cursor = start
    while cursor < end:
        finish = min(cursor + CHUNK, end)
        rows = compute_rows(db, cursor, finish, current)
        _store(db, rows, cursor, finish)
        total += len(rows)
        cursor = finish
    if mark is None:
        db.add(AggregateWatermark(name=WATERMARK, rolled_until=end, updated_at=current))
    else:
        mark.rolled_until = max(mark.rolled_until, end)
        mark.updated_at = current
    db.flush()
    return {"from": start.isoformat(), "to": end.isoformat(), "rows": total}
