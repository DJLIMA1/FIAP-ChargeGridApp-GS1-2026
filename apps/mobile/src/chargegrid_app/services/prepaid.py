"""Pré-pagamentos do assistente de recarga e devolução da sobra como crédito — SIMULADO, no aparelho.

Quando o motorista paga ANTES de carregar (Saldo, Pix ou cartão no assistente ``booking``) e a recarga
termina gastando menos que o valor pago (ex.: bateria cheia, ``end_reason == 'battery_full'``), a
diferença volta para o saldo (``services.wallet.credit``) como "Crédito de recarga não utilizada" —
exatamente uma vez por pré-pagamento, mesmo com várias leituras/recargas da tela.

Só a parte de ENERGIA é devolvível (a taxa de reserva não). Conta demo: em memória no cliente demo;
conta real: JSON em ``FLET_APP_STORAGE_DATA`` por id de usuário.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from . import wallet

CREDIT_TITLE = 'Crédito de recarga não utilizada'
CENT = Decimal('0.01')
ACTIVE = ('starting', 'charging', 'stopping')


def _is_demo(app):
    return getattr(getattr(app, 'api', None), 'is_demo', False) is True


def _path():
    return Path(os.environ.get('FLET_APP_STORAGE_DATA') or Path.home() / '.chargegrid') / 'prepaid.json'


def _user_id(app):
    user = getattr(getattr(getattr(app, 'api', None), 'session', None), 'user', None) or {}
    profile = getattr(app, 'profile', None) or {}
    return str(profile.get('id') or (user.get('id') if isinstance(user, dict) else None) or 'anonymous')


def _load(app):
    if _is_demo(app):
        rows = getattr(app.api, 'chargegrid_prepaid', None)
        return rows if isinstance(rows, list) else []
    try:
        data = json.loads(_path().read_text())
        rows = data.get(_user_id(app)) if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        rows = None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _save(app, rows):
    if _is_demo(app):
        try:
            app.api.chargegrid_prepaid = rows
        except AttributeError:
            pass
        return
    path = _path()
    try:
        data = json.loads(path.read_text())
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        data = {}
    data[_user_id(app)] = rows
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False))
    except OSError:
        pass


def _money(value):
    try:
        return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal('0.00')


def records(app):
    return list(_load(app))


def record(app, *, amount, energy_amount, method, station_id=None, station_name='', connector_id=None,
           reservation_id=None, session_id=None):
    """Registra um pré-pagamento do assistente. ``energy_amount`` = parte devolvível (sem a taxa)."""
    rows = _load(app)
    row = {'id': uuid.uuid4().hex, 'amount': str(_money(amount)), 'energy_amount': str(_money(energy_amount)),
           'method': method, 'station_id': station_id, 'station_name': station_name or '',
           'connector_id': connector_id, 'reservation_id': reservation_id, 'session_id': session_id,
           'status': 'open', 'credited': None, 'created_at': datetime.now(timezone.utc).isoformat()}
    rows.append(row)
    _save(app, rows)
    return row


def cancel_reservation(app, reservation_id):
    """Reserva cancelada (estorno tratado pelo assistente): o pré-pagamento não gera crédito depois."""
    rows = _load(app)
    for row in rows:
        if row.get('reservation_id') == reservation_id and row.get('status') == 'open' and not row.get('session_id'):
            row['status'] = 'cancelled'
    _save(app, rows)


def link_session(app, session_id, *, reservation_id=None, connector_id=None):
    """Liga o pré-pagamento mais recente ainda livre (mesma reserva, ou mesmo conector sem reserva) à sessão."""
    if not session_id:
        return None
    rows = _load(app)
    if any(row.get('session_id') == session_id for row in rows):
        return next(row for row in rows if row.get('session_id') == session_id)
    candidates = [row for row in rows if row.get('status') == 'open' and not row.get('session_id') and (
        (reservation_id and row.get('reservation_id') == reservation_id) or
        (not row.get('reservation_id') and connector_id and row.get('connector_id') == connector_id))]
    if not candidates:
        return None
    chosen = max(candidates, key=lambda row: str(row.get('created_at')))
    chosen['session_id'] = session_id
    _save(app, rows)
    return chosen


def settle(app, session):
    """Recarga encerrada com pré-pagamento: devolve ``pago - custo`` ao saldo uma única vez.

    Retorna o valor creditado (``Decimal``) — também nas leituras seguintes, para a tela mostrar a linha —
    ou ``None`` quando não há crédito.
    """
    if not isinstance(session, dict) or not session.get('id') or session.get('status') in ACTIVE:
        return None
    rows = _load(app)
    row = next((item for item in rows if item.get('session_id') == session['id']), None)
    if row is None and session.get('reservation_id'):
        row = link_session(app, session['id'], reservation_id=session['reservation_id'])
        rows = _load(app)
        row = next((item for item in rows if item.get('session_id') == session['id']), None)
    if row is None or row.get('status') == 'cancelled':
        return None
    if row.get('status') == 'settled':
        credited = _money(row.get('credited') or 0)
        return credited if credited > 0 else None
    cost = _money(session.get('cost_estimate') or 0)
    surplus = _money(row.get('energy_amount')) - cost
    row['status'] = 'settled'
    row['credited'] = str(surplus if surplus > 0 else Decimal('0.00'))
    row['end_reason'] = session.get('end_reason')
    _save(app, rows)  # gravado antes do crédito: nunca credita duas vezes
    if surplus <= 0:
        return None
    wallet.credit(app, surplus, CREDIT_TITLE)
    return surplus
