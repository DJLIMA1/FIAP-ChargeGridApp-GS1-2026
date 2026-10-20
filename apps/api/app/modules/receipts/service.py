"""Monta os fatos do recibo e do histórico do motorista a partir do banco.

O cálculo e o formato ficam em ``chargegrid_core.receipt``; aqui só se lê o que foi
observado (sessão, termos travados, eventos, amostras de potência) e as seções que as
outras frentes registraram em ``registry``.
"""

from sqlalchemy import and_, select

from chargegrid_core import analytics
from chargegrid_core import receipt as receipts

from ...errors import fail
from ...models import ChargingSession, Connector, SessionEvent, Station, Telemetry, now
from ...service import row
from .registry import sections_for

MAX_SAMPLES = 20000  # ~7 dias a cada 30 s; a curva é reduzida a 120 pontos no núcleo
HISTORY_LIMIT = 10000


def own_session(db, user, session_id):
    session = db.get(ChargingSession, session_id)
    if not session or session.user_id != user.id:
        fail("not_found", "Sessão não encontrada", 404)
    return session


def receipt_facts(db, session) -> dict:
    connector = db.get(Connector, session.connector_id)
    station = db.get(Station, connector.station_id)
    events = db.scalars(
        select(SessionEvent).where(SessionEvent.session_id == session.id).order_by(SessionEvent.id)
    ).all()
    samples = db.execute(
        select(Telemetry.captured_at, Telemetry.data["power_w"].astext.label("power_w"))
        .where(Telemetry.session_id == session.id)
        .order_by(Telemetry.captured_at)
        .limit(MAX_SAMPLES)
    ).mappings().all()
    return {
        "session": row(session),
        "station": {"name": station.name, "address": station.address},
        "point": {"public_code": connector.public_code, "connector_type": connector.connector_type,
                  "power_kw": connector.power_kw},
        "events": [{"kind": event.kind, "source": event.source, "observed_at": event.observed_at}
                   for event in events],
        "samples": [dict(sample) for sample in samples],
        "sections": sections_for(db, session),
        "now": now(),
    }


def build(db, session) -> dict:
    return receipts.build_receipt(receipt_facts(db, session))


def history_report(db, user, window) -> dict:
    """Sessões do motorista encerradas no período (fim em ``[from, to)``), com totais."""
    records = db.execute(
        select(ChargingSession, Station.name.label("station_name"), Connector.public_code)
        .join(Connector, Connector.id == ChargingSession.connector_id)
        .join(Station, Station.id == Connector.station_id)
        .where(
            ChargingSession.user_id == user.id,
            and_(ChargingSession.ended_at >= window.start, ChargingSession.ended_at < window.end),
        )
        .order_by(ChargingSession.ended_at.desc(), ChargingSession.id.desc())
        .limit(HISTORY_LIMIT + 1)
    ).all()
    if len(records) > HISTORY_LIMIT:
        fail("export_too_large", f"Mais de {HISTORY_LIMIT} recargas. Reduza o período.", 413)
    moment = now()
    items = [receipts.history_row({**row(session), "station_name": name, "public_code": code}, moment)
             for session, name, code in records]
    return {
        "schema_version": 1,
        "period": {"from": window.start.isoformat(), "to": window.end.isoformat(),
                   "timezone": analytics.REPORT_TZ_NAME},
        "basis": "ended_at",
        "currency": "BRL",
        "generated_at": moment.isoformat(),
        "totals": receipts.history_totals(items),
        "items": items,
        "total": len(items),
    }
