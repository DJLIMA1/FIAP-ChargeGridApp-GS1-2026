"""Permanência após a recarga (overstay): "carga encerrada" e "veículo desconectado" são fatos distintos.

* Abre quando uma sessão termina ``completed`` e o equipamento ainda relata ``connected=true``
  no mesmo sync (hora do servidor; nada é retroagido). ``failed``/``interrupted`` não abrem.
* Cada sync aceito com ``connected=true`` soma o tempo desde a última evidência, até 45 s;
  um intervalo maior (equipamento offline) não é cobrado (evento ``overstay_gap``). Repetições
  de sync nunca chegam aqui.
* Fecha no primeiro sync com ``connected=false`` (``disconnected``), num boot novo
  (``device_reboot``) ou sem notícia do equipamento por 15 min (``observation_lost``). A taxa
  fica congelada até a última evidência de conexão.
* Sem termos aceitos (app antigo, início só pelo código #F) o intervalo é registrado com taxa zero.

Eventos (chave única por sessão): ``vehicle_disconnected``, ``overstay_started``,
``overstay_billing_started``, ``overstay_capped``, ``overstay_gap``, ``overstay_ended`` e
``settlement_ready`` (o valor final não muda mais: o acerto da frente de pagamento pode rodar).
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from chargegrid_core import overstay as rules
from chargegrid_core import pricing

from .errors import fail
from .models import ChargingSession, Profile, Station, now
from .session_events import record

GAP = timedelta(seconds=45)
OBSERVATION_TIMEOUT = timedelta(minutes=15)
SYNC_INTERVAL_SECONDS = 5
TERMINAL = ("completed", "failed", "interrupted")


# ------------------------------------------------------------------------------- termos


def station_terms(station):
    """Termos vigentes do posto (``None`` com a taxa desligada)."""
    if station is None:
        return None
    return rules.terms_from_rotation(pricing.stored_rules(station.pricing)["rotation"])


def public_terms(station):
    return rules.public(station_terms(station))


def terms_for_start(db, connector, data, payment=None):
    """Cópia dos termos aceitos que vale para esta recarga.

    Pré-pago: os termos travados no orçamento pago (o motorista os viu ao pagar). Sem pagamento:
    o app envia a versão que mostrou; versão diferente da vigente -> 409; sem versão -> sem taxa.
    """
    if payment is not None:
        quote = payment.quote if isinstance(payment.quote, dict) else {}
        return rules.clean_terms(quote.get("overstay"))
    current = station_terms(db.get(Station, connector.station_id))
    version = getattr(data, "overstay_terms_version", None)
    if current is None or version is None:
        return None
    if version != current["version"]:
        fail("overstay_terms_changed", "As condições da taxa de permanência mudaram. Revise e confirme de novo.", 409)
    return current


def start_parameters(session):
    """Campo aditivo ``overstay`` do START: o equipamento mantém o cabo conectado ao parar."""
    terms = rules.clean_terms(session.overstay_terms)
    if not terms:
        return {}
    return {"overstay": {"grace_minutes": terms["grace_minutes"], "interval_minutes": terms["interval_minutes"],
                         "amount": terms["amount"], "max_amount": terms["max_amount"]}}


def payment_terms(station):
    """Contrato da frente de pagamento: reserva do teto na autorização e termos mostrados."""
    terms = station_terms(station)
    if not terms:
        return {"reserve_cents": 0, "fee_per_minute": None, "tolerance_minutes": None, "max_billable_minutes": None}
    return {
        "reserve_cents": rules.cents(terms["max_amount"]),
        "fee_per_minute": rules.fee_per_minute(terms),
        "tolerance_minutes": terms["grace_minutes"],
        "max_billable_minutes": rules.max_billable_minutes(terms),
        **terms,
    }


# ------------------------------------------------------------------------------- estado


def is_open(session):
    return session.overstay_started_at is not None and session.overstay_ended_at is None


def _terms(session):
    return rules.clean_terms(session.overstay_terms)


def _fee(session):
    return rules.fee_due(_terms(session), session.overstay_billable_seconds or 0)


def is_final(session):
    """O valor devido não muda mais (sessão encerrada e permanência fechada, ausente ou no teto)."""
    if session.status not in TERMINAL:
        return False
    if session.overstay_started_at is None or session.overstay_ended_at is not None:
        return True
    return rules.capped(_terms(session), session.overstay_billable_seconds or 0)


def charge(db, session):
    """``(centavos, final)`` para o acerto do pagamento."""
    return rules.cents(_fee(session)), is_final(session)


def open_on(db, connector_id):
    return db.scalar(select(ChargingSession).where(
        ChargingSession.connector_id == connector_id,
        ChargingSession.overstay_started_at.is_not(None),
        ChargingSession.overstay_ended_at.is_(None),
    ))


def _event(db, session, kind, key=None, source="device_sync"):
    record(db, session, kind, source, key or f"{kind}:{session.id}")


def _settlement_ready(db, session, source="device_sync"):
    _event(db, session, "settlement_ready", source=source)


def _close(db, session, reason, moment, source="device_sync"):
    was_capped = rules.capped(_terms(session), session.overstay_billable_seconds or 0)
    session.overstay_ended_at = moment
    session.overstay_end_reason = reason
    session.overstay_fee = _fee(session)
    _event(db, session, "overstay_ended", source=source)
    if reason == "disconnected":
        _event(db, session, "vehicle_disconnected", source=source)
    if not was_capped:
        _settlement_ready(db, session, source)


def _accrue(db, session, moment, sync_key):
    terms = _terms(session)
    before = session.overstay_billable_seconds or 0
    gap = moment - session.overstay_last_connected_at
    if gap <= GAP:
        session.overstay_billable_seconds = before + max(0, int(gap.total_seconds()))
    else:
        _event(db, session, "overstay_gap", f"overstay_gap:{sync_key}")
    session.overstay_last_connected_at = moment
    after = session.overstay_billable_seconds
    session.overstay_fee = rules.fee_due(terms, after)
    if terms and rules.phase(terms, before) == "grace" and rules.phase(terms, after) != "grace":
        _event(db, session, "overstay_billing_started")
    if terms and not rules.capped(terms, before) and rules.capped(terms, after):
        _event(db, session, "overstay_capped")
        _settlement_ready(db, session)


def on_sync(db, connector, data, *, reboot, finished):
    """Chamado em cada sync aceito, com a trava do ponto, depois do processamento dos ACKs.

    ``finished``: sessões que terminaram neste sync (``finish``). Roda antes do acerto do
    pagamento do mesmo sync, para que ele já veja a permanência aberta (``final=False``).
    """
    moment = now()
    sync_key = hashlib.sha256(f"{data.boot_id}:{data.sequence}".encode()).hexdigest()[:24]
    current = open_on(db, connector.id)
    if current is not None:
        if reboot:
            _close(db, current, "device_reboot", current.overstay_last_connected_at)
        elif data.connected:
            _accrue(db, current, moment, sync_key)
        else:
            _close(db, current, "disconnected", moment)
    for session in finished:
        if session.status == "completed" and data.connected and not reboot and open_on(db, connector.id) is None:
            session.overstay_started_at = moment
            session.overstay_last_connected_at = moment
            session.overstay_billable_seconds = 0
            session.overstay_fee = Decimal("0")
            _event(db, session, "overstay_started")
            if _terms(session) and rules.capped(_terms(session), 0):  # teto zero: nada a esperar
                _settlement_ready(db, session)
        else:
            if not data.connected:
                _event(db, session, "vehicle_disconnected")
            _settlement_ready(db, session)


def reconcile(db, connector, device):
    """Fecha uma permanência sem notícia do equipamento há 15 min (chamado com a trava do ponto)."""
    current = open_on(db, connector.id)
    if current is None:
        return None
    last = device.last_seen if device is not None and device.last_seen else current.overstay_last_connected_at
    if last > now() - OBSERVATION_TIMEOUT:
        return None
    _close(db, current, "observation_lost", current.overstay_last_connected_at, source="api")
    from .modules.payments.funding import prepare_settlement_for_session  # evita import circular

    prepare_settlement_for_session(db, current)
    return current


# ------------------------------------------------------------------------------- visões


def view(session):
    """Bloco ``overstay`` da sessão (app, recibo, painel do vendedor)."""
    terms = _terms(session)
    seconds = session.overstay_billable_seconds or 0
    if session.overstay_started_at is None:
        status = "none"
    else:
        status = rules.phase(terms, seconds, closed=session.overstay_ended_at is not None)
    return {
        "status": status,
        "fee_applies": terms is not None,
        "started_at": session.overstay_started_at.isoformat() if session.overstay_started_at else None,
        "ended_at": session.overstay_ended_at.isoformat() if session.overstay_ended_at else None,
        "end_reason": session.overstay_end_reason,
        "billable_seconds": seconds,
        "billable_minutes": rules.billable_minutes(terms, seconds),
        "grace_remaining_seconds": rules.grace_remaining_seconds(terms, seconds)
        if status in ("grace", "billing", "capped") else 0,
        "fee_due": str(rules.fee_due(terms, seconds)),
        "max_fee": terms["max_amount"] if terms else None,
        "as_of": session.overstay_last_connected_at.isoformat() if session.overstay_last_connected_at else None,
        "terms": rules.public(terms) if terms else None,
    }


def session_fields(session):
    return {"overstay": view(session), "settlement_ready": is_final(session)}


def sync_block(db, connector):
    """Campo aditivo ``overstay`` da resposta do sync (painel físico), ou ``None``."""
    current = open_on(db, connector.id)
    if current is None:
        return None
    shown = view(current)
    terms = _terms(current)
    return {
        "session_id": str(current.id),
        "status": shown["status"],
        "grace_remaining_seconds": shown["grace_remaining_seconds"],
        "fee_due": shown["fee_due"],
        "max_fee": shown["max_fee"],
        "amount": terms["amount"] if terms else None,
        "interval_minutes": terms["interval_minutes"] if terms else None,
    }


def driver_label(profile, vehicle=None):
    """Primeiro nome + veículo informado (sem e-mail nem telefone)."""
    first = (profile.name or "").strip().split(" ")[0] if profile else ""
    label = first or "Motorista"
    vehicle = (vehicle if vehicle is not None else (profile.vehicle_description if profile else None)) or ""
    return f"{label} · {vehicle.strip()}" if vehicle.strip() else label


def occupancy_by_connector(db, connector_ids):
    """``{connector_id: bloco}`` das permanências abertas (painel do vendedor ao vivo)."""
    if not connector_ids:
        return {}
    rows = db.execute(
        select(ChargingSession, Profile)
        .join(Profile, Profile.id == ChargingSession.user_id)
        .where(
            ChargingSession.connector_id.in_(connector_ids),
            ChargingSession.overstay_started_at.is_not(None),
            ChargingSession.overstay_ended_at.is_(None),
        )
    ).all()
    result = {}
    for session, profile in rows:
        shown = view(session)
        result[session.connector_id] = {
            "session_id": str(session.id),
            "status": shown["status"],
            "started_at": shown["started_at"],
            "grace_remaining_seconds": shown["grace_remaining_seconds"],
            "billable_minutes": shown["billable_minutes"],
            "fee_due": shown["fee_due"],
            "max_fee": shown["max_fee"],
            "fee_applies": shown["fee_applies"],
            "driver_label": driver_label(profile),
            "as_of": shown["as_of"],
        }
    return result


def current_for_user(db, user):
    """Permanência aberta da pessoa (``GET /overstays/current``), ou ``None``."""
    return db.scalar(
        select(ChargingSession)
        .where(
            ChargingSession.user_id == user.id,
            ChargingSession.overstay_started_at.is_not(None),
            ChargingSession.overstay_ended_at.is_(None),
        )
        .order_by(ChargingSession.overstay_started_at.desc())
        .limit(1)
    )


def receipt_extras(db, sessions):
    """Seção ``overstay`` do recibo e da margem (frente C): uma linha por sessão com permanência."""
    result = {}
    for session in sessions:
        if session.overstay_started_at is None:
            continue
        shown = view(session)
        terms = _terms(session)
        result[session.id] = {
            # ``phase`` (não ``status``): o recibo marca a seção como ``status: "available"``.
            "phase": shown["status"],
            "grace_minutes": terms["grace_minutes"] if terms else None,
            "started_at": shown["started_at"],
            "ended_at": shown["ended_at"],
            "end_reason": shown["end_reason"],
            "billable_minutes": shown["billable_minutes"],
            "rate": str(rules.fee_per_minute(terms)) if terms else None,
            "max_amount": terms["max_amount"] if terms else None,
            # Sem termos aceitos não há taxa (``None`` não entra na receita).
            "amount": shown["fee_due"] if terms else None,
            "final": is_final(session),
            "summary": rules.summary(terms),
            "waived": False,
        }
    return result
