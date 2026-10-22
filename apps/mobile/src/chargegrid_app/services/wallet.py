"""Saldo (carteira) do consumidor — SIMULADO, 100% no aparelho. Nenhum dinheiro real se move.

* Conta demo: em memória; começa com R$ 214,80 e as transações de referência.
* Conta real: arquivo JSON em ``FLET_APP_STORAGE_DATA`` (como ``preferences.py``), por id de usuário, começa em 0.

Interface: ``balance(app)``, ``transactions(app)``, ``credit(app, amount, description)``,
``debit(app, amount, description)`` (levanta ``ApiError('Saldo insuficiente…')``).
Nunca guarda dados de cartão.
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..api_client import ApiError

DEMO_BALANCE = Decimal('214.80')
_demo_state = None


def _demo_initial():
    now = datetime.now(timezone.utc)
    return {'balance': str(DEMO_BALANCE), 'transactions': [
        {'kind': 'credit', 'title': 'Pix Recebido', 'amount': '250.00',
         'created_at': (now - timedelta(days=1)).isoformat()},
        {'kind': 'credit', 'title': 'Transferência Recebida', 'amount': '20.00',
         'created_at': (now - timedelta(days=4)).isoformat()},
    ]}


def _is_demo(app):
    return bool(getattr(getattr(app, 'api', None), 'is_demo', False))


def _path():
    storage = Path(os.environ.get('FLET_APP_STORAGE_DATA') or Path.home() / '.chargegrid')
    return storage / 'wallet.json'


def _user_id(app):
    return str((getattr(app, 'profile', None) or {}).get('id') or 'anonymous')


def reset_demo():
    """Reinicia o saldo demo (testes)."""
    global _demo_state
    _demo_state = None


def _load(app):
    global _demo_state
    if _is_demo(app):
        if _demo_state is None:
            _demo_state = _demo_initial()
        return _demo_state
    cached = getattr(app, 'shared_wallet', None)
    if isinstance(cached, dict) and cached.get('user_id') == _user_id(app):
        return cached
    try:
        data = json.loads(_path().read_text())
        entry = data.get(_user_id(app)) if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        entry = None
    if not isinstance(entry, dict) or not isinstance(entry.get('transactions'), list):
        return {'balance': '0', 'transactions': []}
    return entry


def _save(app, state):
    if _is_demo(app):
        return
    path = _path()
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError, TypeError):
        data = {}
    data[_user_id(app)] = state
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False))
    except OSError:
        pass


def _amount(value):
    try:
        number = Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        raise ApiError('Informe um valor válido.', 422, 'invalid_amount') from None
    if number <= 0:
        raise ApiError('Informe um valor maior que zero.', 422, 'invalid_amount')
    return number


def balance(app) -> Decimal:
    """Saldo disponível atual."""
    try:
        return Decimal(str(_load(app).get('balance', '0')))
    except InvalidOperation:
        return Decimal('0')


def transactions(app) -> list:
    """Extrato, mais recentes primeiro: ``[{kind, title, amount, created_at}]`` (kind: credit|debit)."""
    rows = []
    for item in _load(app).get('transactions', []):
        if isinstance(item, dict):
            rows.append({'kind': item.get('kind', 'credit'), 'title': item.get('title', ''),
                         'amount': Decimal(str(item.get('amount', '0'))), 'created_at': item.get('created_at', '')})
    return sorted(rows, key=lambda row: str(row['created_at']), reverse=True)


def _apply(app, kind, amount, description):
    state = _load(app)
    value = _amount(amount)
    current = balance(app)
    new = current + value if kind == 'credit' else current - value
    state['balance'] = str(new)
    state.setdefault('transactions', []).append({
        'kind': kind, 'title': description, 'amount': str(value),
        'created_at': datetime.now(timezone.utc).isoformat()})
    _save(app, state)
    return new


def credit(app, amount, description):
    """Adiciona saldo (simulado) e registra no extrato. Retorna o novo saldo."""
    return _apply(app, 'credit', amount, description)


def debit(app, amount, description):
    """Desconta do saldo; ``ApiError('Saldo insuficiente…')`` se não houver o bastante."""
    value = _amount(amount)
    if value > balance(app):
        raise ApiError('Saldo insuficiente. Adicione saldo para continuar.', 402, 'insufficient_balance')
    return _apply(app, 'debit', value, description)


async def refresh(app):
    """Refresh the shared SIMULATED balance. Older APIs keep the local wallet."""
    if _is_demo(app):
        return False
    try:
        remote = await app.api.request('GET', 'me/wallet')
        if not isinstance(remote, dict) or remote.get('simulated') is not True:
            return False
        # A one-time server flag makes legacy import safe across devices/retries.
        legacy = balance(app)
        if not remote.get('legacy_imported'):
            remote = await app.api.request('POST', 'me/wallet/simulate',
                {'kind': 'import', 'amount': str(max(Decimal('0'), legacy)), 'title': 'Saldo simulado do app'},
                key='wallet-legacy-import')
        app.shared_wallet = {**remote, 'user_id': _user_id(app)}
        return True
    except ApiError as error:
        if error.status == 401:
            raise
        # Saldo compartilhado é opcional: API antiga (404/410), rede ou servidor fora não derrubam a
        # reserva nem a carteira; seguem com o último saldo conhecido (ou o local).
        return False


async def _remote_move(app, kind, amount, description, operation_key=None):
    if _is_demo(app) or not isinstance(getattr(app, 'shared_wallet', None), dict):
        return credit(app, amount, description) if kind == 'credit' else debit(app, amount, description)
    pending = getattr(app, 'wallet_pending', None)
    body = {'kind': kind, 'amount': str(_amount(amount)), 'title': description}
    if not isinstance(pending, dict) or pending.get('body') != body:
        pending = {'body': body, 'key': operation_key or uuid.uuid4().hex}
        app.wallet_pending = pending
    remote = await app.api.request('POST', 'me/wallet/simulate', body, key=pending['key'])
    app.shared_wallet = {**remote, 'user_id': _user_id(app)}
    app.wallet_pending = None
    return balance(app)


async def shared_credit(app, amount, description, operation_key=None):
    return await _remote_move(app, 'credit', amount, description, operation_key)


async def shared_debit(app, amount, description):
    return await _remote_move(app, 'debit', amount, description)
