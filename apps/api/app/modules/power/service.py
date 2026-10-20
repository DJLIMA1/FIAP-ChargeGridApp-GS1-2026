"""Rebalanceamento de potência ao vivo, disparado pelas requisições existentes.

Sem worker de fundo (Vercel): cada sync de um dispositivo em recarga (1 s) recalcula a
decisão do posto com ``chargegrid_core.balancing`` e emite comandos **só para o próprio
dispositivo** ("autoatendimento"). Assim o sync continua travando um único conector.

Ordem de locks: perfil → conector → ``pg_advisory_xact_lock('power:<posto>')``. Quem
segura o lock do posto nunca espera outro conector, então não há ciclo. O lock é de
transação (compatível com o pooler em modo transação) e serializa aumentos e inícios,
para dois pontos não ocuparem a mesma folga.

Regra de segurança: reduções saem sempre; aumentos só cabem na folga calculada com os
envelopes (aplicado confirmado ou ajuste pendente) dos outros pontos. Redução sem
confirmação é reenviada uma vez; na segunda falha o ponto recebe STOP. Ponto offline
mantém a capacidade reservada: falta de rede nunca prova parada.
"""

from datetime import timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from sqlalchemy import select, text

from chargegrid_core import balancing
from chargegrid_core import power as power_rules

from ...errors import fail
from ...models import ChargingSession, Command, Connector, Device, PowerDecision, SessionEvent, Station, now
from ...service import issue, online
from ...session_events import record as record_session_event

CAPABILITY = "set_power_v1"
SET_POWER = "SET_POWER"
ALLOCATED = ("starting", "charging")
ENVELOPED = ("starting", "charging", "stopping")
SET_POWER_SECONDS = 15
MAX_REDUCTION_ATTEMPTS = 2
ZERO = Decimal(0)
KW = Decimal("0.001")
TENTH = Decimal("0.1")
POWER_EVENTS = ("power_requested", "power_applied", "power_failed")


def kw_to_w(value) -> int:
    return int((Decimal(value) * 1000).to_integral_value(rounding=ROUND_DOWN))


def w_to_kw(value) -> Decimal:
    return (Decimal(value) / 1000).quantize(KW, rounding=ROUND_DOWN)


def _dec(value):
    return None if value is None else Decimal(value)


def _text(value):
    return None if value is None else str(Decimal(value).quantize(KW))


def adjustable(device) -> bool:
    return bool(device and CAPABILITY in (device.capabilities or []))


def lock_station(db, station_id):
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"power:{station_id}"})


class _Point:
    """Uma sessão ativa do posto com o ponto, o equipamento e os comandos pendentes."""

    def __init__(self, session, connector, device, commands, moment):
        self.session, self.connector, self.device, self.commands = session, connector, device, commands
        self.moment = moment

    @property
    def key(self):
        return str(self.session.id)

    def pending_power(self):
        """SET_POWER ainda em voo (expirado só conta se o equipamento sumiu: pode ter aplicado)."""
        alive = online(self.device)
        return [cmd for cmd in self.commands
                if cmd.type == SET_POWER and (cmd.expires_at > self.moment or not alive)]

    def start_kw(self):
        for cmd in self.commands:
            if cmd.type == "START":
                params = cmd.parameters or {}
                if params.get("power_limit_w") is not None:
                    return w_to_kw(params["power_limit_w"])
                if params.get("max_power_kw") is not None:
                    return Decimal(str(params["max_power_kw"]))
        return _dec(self.session.power_limit_kw) or Decimal(self.connector.power_kw)

    def applied(self):
        session = self.session
        if session.applied_power_kw is not None:
            return Decimal(session.applied_power_kw)
        return _dec(session.power_limit_kw) or Decimal(self.connector.power_kw)

    def envelope(self):
        if self.session.status == "starting":
            return self.start_kw()
        values = [self.applied(), *(w_to_kw((cmd.parameters or {}).get("power_limit_w", 0))
                                    for cmd in self.pending_power())]
        return max(values)

    def limits(self):
        rating = Decimal(self.connector.power_kw)
        charger = (self.device.charger if self.device else None) or {}
        floor = w_to_kw(charger["min_power_w"]) if charger.get("min_power_w") else power_rules.floor_for(rating)
        maximum = w_to_kw(charger["max_power_w"]) if charger.get("max_power_w") else None
        return floor, maximum


def _state(db, station):
    """Sessões ativas do posto, relidas do banco (depois do lock do posto, valores atuais)."""
    moment = now()
    connectors = db.scalars(select(Connector).where(Connector.station_id == station.id)).all()
    ids = [point.id for point in connectors]
    if not ids:
        return []
    by_id = {point.id: point for point in connectors}
    devices = {
        device.connector_id: device
        for device in db.scalars(
            select(Device).where(Device.connector_id.in_(ids), Device.revoked.is_(False))
            .execution_options(populate_existing=True)
        )
    }
    sessions = db.scalars(
        select(ChargingSession)
        .where(ChargingSession.connector_id.in_(ids), ChargingSession.status.in_(ENVELOPED))
        .execution_options(populate_existing=True)
    ).all()
    commands = db.scalars(
        select(Command).where(
            Command.session_id.in_([session.id for session in sessions]),
            Command.type.in_((SET_POWER, "START")),
            Command.status.in_(("pending", "received")),
        ).execution_options(populate_existing=True)
    ).all() if sessions else []
    return [
        _Point(session, by_id[session.connector_id], devices.get(session.connector_id),
               [cmd for cmd in commands if cmd.session_id == session.id], moment)
        for session in sessions
    ]


def _decide(station, points):
    participants = []
    for point in points:
        if point.session.status not in ALLOCATED:
            continue
        floor, maximum = point.limits()
        capable = adjustable(point.device)
        created = point.session.created_at or point.moment
        participants.append(balancing.Participant(
            id=point.key,
            rating_kw=Decimal(point.connector.power_kw),
            port_limit_kw=_dec(point.connector.power_limit_kw),
            driver_kw=_dec(point.session.requested_power_kw),
            device_max_kw=maximum,
            floor_kw=floor,
            adjustable=capable,
            fixed_kw=None if capable else point.envelope(),
            order=(created.timestamp(), point.key),
        ))
    return balancing.decide(
        participants,
        site_limit_kw=station.site_limit_kw,
        building_load_kw=station.building_load_kw,
        station_cap_kw=station.max_power_kw,
    )


def _labels(points):
    return {point.key: point.connector.public_code for point in points}


def record_decision(db, station, decision, envelopes, labels):
    """Grava a decisão quando entradas, alvos ou envelopes mudaram (dedupe pelo hash)."""
    snap = balancing.snapshot(decision, envelopes)
    digest = balancing.fingerprint(snap)
    last = db.scalar(
        select(PowerDecision).where(PowerDecision.station_id == station.id)
        .order_by(PowerDecision.id.desc()).limit(1)
    )
    if last and last.input_hash == digest:
        return last
    row = PowerDecision(
        station_id=station.id,
        created_at=now(),
        trigger=balancing.trigger(last.inputs if last else None, snap),
        inputs={**snap, "labels": labels},
        available_kw=decision["available_kw"],
        exceeded_kw=balancing.exceeded(envelopes.values(), decision["available_kw"]),
        summary=balancing.summary(decision, labels),
        input_hash=digest,
    )
    db.add(row)
    db.flush()
    return row


def _present(session, decision, row, capable, pending):
    """Alvo, estado e motivo da sessão: o que app, painel físico, vendedor e recibo mostram."""
    item = decision["sessions"].get(str(session.id))
    if not item:
        return
    reason = balancing.explain(decision, str(session.id))
    target = item["target_kw"]
    applied = _dec(session.applied_power_kw)
    if not capable:
        state = "fixed"
    elif pending:
        requested = w_to_kw((pending[-1].parameters or {}).get("power_limit_w", 0))
        state = "reducing" if applied is not None and requested < applied else "raising"
    elif applied is None:
        state = "raising"
    elif target == 0 and applied == 0:
        state = "paused"
    elif target > applied:
        state = "waiting"
    else:
        state = "applied"
    values = {
        "target_power_kw": target.quantize(KW),
        "power_state": state,
        "power_reason": reason["text"][:300],
        "power_reason_short": reason["short"][:60],
        "power_reason_code": reason["code"],
        "power_decision_id": row.id if row else session.power_decision_id,
    }
    for name, value in values.items():
        current = getattr(session, name)
        if (Decimal(current) if isinstance(value, Decimal) and current is not None else current) != value:
            setattr(session, name, value)


def _last_power_command(db, device, session):
    return db.scalar(
        select(Command).where(Command.device_id == device.id, Command.session_id == session.id,
                              Command.type == SET_POWER)
        .order_by(Command.version.desc()).limit(1)
    )


def _issue_power(db, connector, device, session, kind, value, applied, reason, decision_row, attempt=1):
    params = {
        "power_limit_w": kw_to_w(value),
        "previous_power_w": kw_to_w(applied),
        "direction": kind,
        "attempt": attempt,
        "decision_id": decision_row.id if decision_row else None,
        "reason": reason["code"],
        "reason_short": reason["short"],
    }
    cmd = issue(db, connector, device, SET_POWER, session=session, parameters=params, reconcile=False)
    cmd.expires_at = now() + timedelta(seconds=SET_POWER_SECONDS)
    record_session_event(db, session, "power_requested", "api", f"power_requested:{cmd.id}", data={
        "kw": _text(value), "previous_kw": _text(applied), "direction": kind, "attempt": attempt,
        "decision_id": params["decision_id"], "reason_text": reason["text"],
    })
    return cmd


def _reduction_attempt(db, device, session):
    """Próxima tentativa de redução: a anterior falhou ou expirou sem confirmação?"""
    last = _last_power_command(db, device, session)
    if not last or (last.parameters or {}).get("direction") != "reduce":
        return 1
    unconfirmed = last.status == "failed" or (last.status in ("pending", "received") and last.expires_at <= now())
    return int((last.parameters or {}).get("attempt", 1)) + 1 if unconfirmed else 1


def after_sync(db, connector, device, session):
    """Chamado no fim de cada sync aceito: ajusta só este dispositivo, se for preciso."""
    if session is None or session.status != "charging" or device is None:
        return
    station = db.get(Station, connector.station_id)
    if not station or not station.rebalance_enabled:
        return
    lock_station(db, station.id)
    points = _state(db, station)
    me = next((point for point in points if point.session.id == session.id), None)
    if me is None or me.session.status != "charging":
        return
    session = me.session
    decision = _decide(station, points)
    envelopes = {point.key: point.envelope() for point in points}
    labels = _labels(points)
    capable = adjustable(device)
    pending = me.pending_power()
    busy = db.scalar(select(Command.id).where(
        Command.device_id == device.id, Command.type != SET_POWER,
        Command.status.in_(("pending", "received")), Command.expires_at > now(),
    ).limit(1))
    action = None
    item = decision["sessions"][me.key]
    if capable and not pending and not busy:
        applied = me.applied()
        others = sum((value for key, value in envelopes.items() if key != me.key), ZERO)
        action = balancing.step(item["target_kw"], applied, others, decision["available_kw"], item["floor_kw"])
    if action:
        kind, value = action
        attempt = _reduction_attempt(db, device, session) if kind == "reduce" else 1
        if attempt > MAX_REDUCTION_ATTEMPTS:
            # Sem confirmar a redução não dá para garantir o limite: encerra este ponto.
            session.status = "stopping"
            issue(db, connector, device, "STOP", session=session, parameters={"reason": "power_limit_unconfirmed"})
            record_decision(db, station, decision, envelopes, labels)
            return
        if kind == "raise":
            envelopes[me.key] = max(envelopes[me.key], value)
        row = record_decision(db, station, decision, envelopes, labels)
        reason = balancing.explain(decision, me.key)
        cmd = _issue_power(db, connector, device, session, kind, value, me.applied(), reason, row, attempt)
        pending = [cmd]
    else:
        row = record_decision(db, station, decision, envelopes, labels)
    _present(session, decision, row, capable, pending)


def start_power(db, connector, device, session):
    """Potência inicial do START com o rebalanceamento ligado (o START ainda não foi emitido).

    Devolve parâmetros extras do START. Sem capacidade para o carro novo: 409
    ``site_power_full``. Dispositivo capaz pode começar em 0 e subir depois que os outros
    confirmarem a redução; equipamento antigo só começa com pelo menos o piso.
    """
    station = db.get(Station, connector.station_id)
    if not station or not station.rebalance_enabled:
        return {}
    lock_station(db, station.id)
    points = _state(db, station)
    decision = _decide(station, points)
    key = str(session.id)
    item = decision["sessions"][key]
    target, floor = item["target_kw"], item["floor_kw"]
    others = sum((point.envelope() for point in points if point.key != key), ZERO)
    action = balancing.step(target, ZERO, others, decision["available_kw"], floor)
    initial = action[1] if action else ZERO
    capable = adjustable(device)
    reason = balancing.explain(decision, key)
    if target <= 0:
        fail("site_power_full", "Sem potência disponível agora: " + reason["text"].removeprefix("Pausado: ")
             + " Tente novamente em alguns minutos.")
    if not capable and initial < min(floor, target):
        fail("site_power_full", "Os outros pontos ainda estão reduzindo a potência para liberar espaço. "
             "Tente novamente em alguns segundos.")
    session.power_limit_kw = target.quantize(KW)
    envelopes = {point.key: point.envelope() for point in points}
    envelopes[key] = initial
    row = record_decision(db, station, decision, envelopes, _labels(points))
    _present(session, decision, row, capable, [])
    session.power_state = "raising" if initial >= target or not capable else "waiting"
    extra = {"max_power_kw": float(initial if initial > 0 else target), "power_decision_id": row.id}
    if capable:
        extra["power_limit_w"] = kw_to_w(initial)
    return extra


def on_start_applied(db, session, cmd, data):
    """START confirmado: a potência aplicada inicial é a informada pelo equipamento, ou a do START."""
    params = cmd.parameters or {}
    if data.applied_power_w is not None:
        applied = w_to_kw(data.applied_power_w)
    elif params.get("power_limit_w") is not None:
        applied = w_to_kw(params["power_limit_w"])
    elif params.get("max_power_kw") is not None:
        applied = Decimal(str(params["max_power_kw"])).quantize(KW)
    else:
        applied = _dec(session.power_limit_kw)
    if applied is None:
        return
    session.applied_power_kw = applied
    if session.power_decision_id is None:
        return  # Posto sem rebalanceamento ao vivo: a linha do tempo de potência não se aplica.
    record_session_event(db, session, "power_applied", "device_sync", f"power_applied:{cmd.id}", data={
        "kw": _text(applied), "requested_kw": _text(applied), "direction": "start",
        "decision_id": params.get("power_decision_id"), "reason_text": session.power_reason,
        "energy_wh_at": "0.000",
    })


def observe(session, device, data):
    """Limite aplicado informado a cada sync: a verdade do equipamento (resolve ACK perdido)."""
    if (adjustable(device) and data.applied_power_w is not None and session.status == "charging"
            and data.physical_state == "charging"):
        value = w_to_kw(data.applied_power_w)
        if session.applied_power_kw is None or Decimal(session.applied_power_kw) != value:
            session.applied_power_kw = value


def acknowledge(db, session, cmd, ack, data):
    """ACK ``applied`` de um SET_POWER: só vale com a sessão carregando e o valor dentro do pedido."""
    params = cmd.parameters or {}
    requested = int(params.get("power_limit_w", -1))
    applied = ack.applied_power_w if ack.applied_power_w is not None else data.applied_power_w
    if not (session is not None and session.id == cmd.session_id and session.status == "charging"
            and data.session_id == session.id and data.physical_state == "charging"):
        cmd.status, cmd.error = "failed", "session_not_charging"
        return
    if applied is None or Decimal(applied) > requested + 1:
        cmd.status, cmd.error = "failed", "applied_power_mismatch"
        record_session_event(db, session, "power_failed", "device_sync", f"power_failed:{cmd.id}", data={
            "requested_kw": _text(w_to_kw(requested)), "reported_kw": _text(w_to_kw(applied)) if applied else None,
            "error": "applied_power_mismatch",
        })
        return
    cmd.status = "applied"
    session.applied_power_kw = w_to_kw(applied)
    record_session_event(db, session, "power_applied", "device_sync", f"power_applied:{cmd.id}", data={
        "kw": _text(w_to_kw(applied)), "requested_kw": _text(w_to_kw(requested)),
        "direction": params.get("direction"), "decision_id": params.get("decision_id"),
        "reason_text": session.power_reason, "energy_wh_at": str(Decimal(data.energy_wh).quantize(KW)),
    })


def sync_fields(session):
    """Campos de potência no ``authorized.session`` do sync (números JSON simples)."""
    return {
        "applied_power_kw": float(session.applied_power_kw) if session.applied_power_kw is not None else None,
        "target_power_kw": float(session.target_power_kw) if session.target_power_kw is not None else None,
        "power_state": session.power_state,
        "power_reason_short": session.power_reason_short,
    }


# ---- Vendedor e motorista -------------------------------------------------------------

def _quantize_kw(value):
    return Decimal(value).quantize(TENTH, rounding=ROUND_HALF_UP)


def _refresh_decision(db, station):
    lock_station(db, station.id)
    points = _state(db, station)
    decision = _decide(station, points)
    return record_decision(db, station, decision, {point.key: point.envelope() for point in points},
                           _labels(points))


def set_site(db, station, data):
    fields = data.model_fields_set
    if "site_limit_kw" in fields:
        value = data.site_limit_kw
        if value is not None:
            if value <= 0:
                fail("invalid_power_limit", "Informe um limite contratado maior que zero.", 422)
            value = _quantize_kw(value)
            if value > power_rules.STATION_MAX_KW:
                fail("invalid_power_limit",
                     f"O limite contratado deve ser de até {power_rules.kw_text(power_rules.STATION_MAX_KW)} kW.", 422)
        station.site_limit_kw = value
    if "rebalance_enabled" in fields:
        if data.rebalance_enabled is None:
            fail("null_not_allowed", "Campo não aceita null", 422)
        station.rebalance_enabled = data.rebalance_enabled
    db.flush()
    _refresh_decision(db, station)


def set_building_load(db, station, value):
    station.building_load_kw = _quantize_kw(value)
    station.building_load_source = "simulated"
    station.building_load_updated_at = now()
    db.flush()
    _refresh_decision(db, station)


def station_view(db, station):
    """Painel do vendedor: entradas, divisão atual, estado por ponto e últimas decisões."""
    points = _state(db, station)
    decision = _decide(station, points)
    envelopes = {point.key: point.envelope() for point in points}
    by_connector = {point.connector.id: point for point in points}
    connectors = db.scalars(
        select(Connector).where(Connector.station_id == station.id).order_by(Connector.public_code)
    ).all()
    devices = {
        device.connector_id: device for device in db.scalars(
            select(Device).where(Device.connector_id.in_([c.id for c in connectors]), Device.revoked.is_(False)))
    } if connectors else {}
    rows = []
    for connector in connectors:
        point = by_connector.get(connector.id)
        device = devices.get(connector.id)
        entry = {
            "connector_id": str(connector.id), "public_code": connector.public_code,
            "power_kw": _text(connector.power_kw), "online": online(device),
            "adjustable": adjustable(device), "charger": device.charger if device else None,
            "session": None,
        }
        if point:
            session = point.session
            item = decision["sessions"].get(point.key)
            reason = balancing.explain(decision, point.key) if item else None
            entry["session"] = {
                "id": point.key, "status": session.status,
                "target_kw": _text(item["target_kw"]) if item else None,
                "applied_kw": _text(session.applied_power_kw),
                "envelope_kw": _text(envelopes[point.key]),
                "power_state": session.power_state,
                "reason": reason["text"] if reason else session.power_reason,
                "reason_short": reason["short"] if reason else session.power_reason_short,
                "reason_code": reason["code"] if reason else session.power_reason_code,
            }
        rows.append(entry)
    decisions = db.scalars(
        select(PowerDecision).where(PowerDecision.station_id == station.id)
        .order_by(PowerDecision.id.desc()).limit(20)
    ).all()
    total = sum(envelopes.values(), ZERO)
    return {
        "station_id": str(station.id),
        "rebalance_enabled": station.rebalance_enabled,
        "site_limit_kw": _text(station.site_limit_kw),
        "building_load_kw": _text(station.building_load_kw),
        "building_load_source": station.building_load_source,
        "building_load_simulated": station.building_load_source == "simulated",
        "building_load_updated_at": station.building_load_updated_at,
        "station_cap_kw": _text(station.max_power_kw),
        "available_kw": _text(decision["available_kw"]),
        "allocated_kw": _text(decision["allocated_kw"]),
        "envelope_kw": _text(total),
        "exceeded_kw": _text(balancing.exceeded(envelopes.values(), decision["available_kw"])),
        "cars": decision["cars"],
        "points": rows,
        "decisions": [
            {"id": item.id, "created_at": item.created_at, "trigger": item.trigger,
             "available_kw": _text(item.available_kw), "exceeded_kw": _text(item.exceeded_kw),
             "summary": item.summary}
            for item in decisions
        ],
    }


def session_view(db, session):
    """Motorista e recibo: potência atual com o motivo e os trechos confirmados pelo equipamento."""
    events = db.scalars(
        select(SessionEvent).where(SessionEvent.session_id == session.id, SessionEvent.kind.in_(POWER_EVENTS))
        .order_by(SessionEvent.id)
    ).all()
    applied = [event for event in events if event.kind == "power_applied"]
    segments = []
    for index, event in enumerate(applied):
        data = event.data or {}
        end = applied[index + 1].observed_at if index + 1 < len(applied) else session.ended_at
        segments.append({"from": event.observed_at, "to": end, "applied_kw": data.get("kw"),
                         "reason_text": data.get("reason_text"), "decision_id": data.get("decision_id"),
                         "energy_wh_at": data.get("energy_wh_at")})
    return {
        "session_id": str(session.id),
        "current": {
            "target_kw": _text(session.target_power_kw), "applied_kw": _text(session.applied_power_kw),
            "power_state": session.power_state, "reason": session.power_reason,
            "reason_short": session.power_reason_short, "reason_code": session.power_reason_code,
        },
        "segments": segments,
        "requests": [{"at": event.observed_at, "kind": event.kind, **(event.data or {})}
                     for event in events if event.kind != "power_applied"],
    }
