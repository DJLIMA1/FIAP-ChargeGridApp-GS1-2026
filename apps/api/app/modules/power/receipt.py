"""Mudanças de potência (frente B) no recibo (frente C): ``register_section("power_changes")``.

Lê os eventos ``power_*`` da sessão (os mesmos de ``service.session_view``) e os casa pelo
comando ``SET_POWER``/``START`` que os originou (``event_key = <tipo>:<command_id>``):

* ``power_requested`` + ``power_applied`` do mesmo comando → ``applied`` (ACK do equipamento);
* ``power_failed`` ou comando falho/expirado sem ACK → ``failed``;
* pedido ainda sem resposta → ``requested`` (nunca contado como aplicado);
* ``power_applied`` do START (sem pedido) → limite inicial confirmado.

Posto sem rebalanceamento ao vivo não tem eventos: devolve ``None`` e o recibo mantém o
limite do início que ele mesmo calcula.
"""

import uuid
from datetime import timezone

from sqlalchemy import select

from ...models import Command, SessionEvent, now
from .service import POWER_EVENTS

FAILED_COMMANDS = ("failed", "expired", "canceled", "cancelled")
FAILURE_LABELS = {
    "applied_power_mismatch": "O equipamento informou uma potência diferente da pedida",
    "session_not_charging": "A recarga não estava em andamento quando o ajuste chegou",
    "unconfirmed": "O equipamento não confirmou o ajuste a tempo",
}
DIRECTION_LABELS = {"reduce": "Redução de potência", "raise": "Aumento de potência",
                    "start": "Limite de potência no início"}


def _iso(value):
    return value.astimezone(timezone.utc).isoformat() if value else None


def _command_id(event):
    try:
        return uuid.UUID(event.event_key.split(":", 1)[1])
    except (IndexError, ValueError):
        return None


def _label(direction, reason_text):
    base = DIRECTION_LABELS.get(direction, "Ajuste de potência")
    return f"{base}: {reason_text}" if reason_text else base


def power_changes(db, session):
    events = db.scalars(
        select(SessionEvent)
        .where(SessionEvent.session_id == session.id, SessionEvent.kind.in_(POWER_EVENTS))
        .order_by(SessionEvent.id)
    ).all()
    if not events:
        return None
    ids = {value for value in map(_command_id, events) if value is not None}
    commands = {cmd.id: cmd for cmd in db.scalars(select(Command).where(Command.id.in_(ids)))} if ids else {}
    by_command: dict = {}
    order = []
    for event in events:
        key = _command_id(event) or event.event_key
        if key not in by_command:
            by_command[key] = {}
            order.append(key)
        by_command[key][event.kind] = event

    moment = now()
    changes = []
    for key in order:
        found = by_command[key]
        requested, applied, failed = (found.get(kind) for kind in POWER_EVENTS)
        command = commands.get(key)
        params = (command.parameters or {}) if command else {}
        request_data = (requested.data or {}) if requested else {}
        applied_data = (applied.data or {}) if applied else {}
        direction = request_data.get("direction") or applied_data.get("direction") or params.get("direction")
        reason_text = request_data.get("reason_text") or applied_data.get("reason_text")
        reason_code = params.get("reason") or ("start_limit" if direction == "start" else None)
        failed_data = (failed.data or {}) if failed else {}
        requested_kw = request_data.get("kw") or applied_data.get("requested_kw") or failed_data.get("requested_kw")
        change = {
            "at": _iso((requested or applied or failed).observed_at),
            "requested_kw": requested_kw,
            "applied_kw": None,
            "previous_kw": request_data.get("previous_kw"),
            "status": "requested",
            "reason_code": reason_code,
            "reason_label": _label(direction, reason_text),
            "confirmed_at": None,
            "source": "rebalance",
            "direction": direction,
            "attempt": request_data.get("attempt"),
            "decision_id": request_data.get("decision_id") or applied_data.get("decision_id"),
        }
        if applied is not None:  # só o ACK do equipamento torna a mudança aplicada
            change.update(status="applied", applied_kw=applied_data.get("kw"), confirmed_at=_iso(applied.observed_at),
                          energy_wh_at=applied_data.get("energy_wh_at"))
        elif failed is not None or (command is not None and (
                command.status in FAILED_COMMANDS
                or (command.status in ("pending", "received") and command.expires_at <= moment))):
            error = failed_data.get("error") if failed is not None else (
                command.error if command is not None and command.error else "unconfirmed")
            change.update(status="failed", failure_code=error,
                          failure_label=FAILURE_LABELS.get(error, "O ajuste não foi confirmado pelo equipamento"),
                          reported_kw=failed_data.get("reported_kw"))
        changes.append(change)
    return changes


def install():
    from ..receipts.registry import register_section

    register_section("power_changes", power_changes)
