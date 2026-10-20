"""Carteira e resgate do vendedor (simulado, nada movimenta dinheiro de verdade).

Demo: saldo inicial R$ 2.485,90 em memória (guardado no próprio ``app``). Conta real: saldo =
**repasse** ao dono (``owner_net`` de ``GET /v1/owner/margin`` nos últimos 12 meses: receita cobrada menos a
comissão da plataforma e a tarifa do pagamento; receita bruta não é saldo), guardado em ``app`` por
``load_owner_net``, menos os resgates registrados localmente em ``payouts.json`` (``FLET_APP_STORAGE_DATA``,
como ``preferences.py``).
"""

import json
import os
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

FEE_RATE = Decimal('0.02')
DEMO_BALANCE = Decimal('2485.90')
DEMO_DESTINATION = 'Banco Inter •••• 0378'
REAL_DESTINATION = 'Conta cadastrada'
DEMO_FIRST_PROTOCOL = 1026
CENT = Decimal('0.01')
NET_DAYS = 365  # janela do repasse acumulado (a API aceita até 366 dias)

_DEMO_MOVEMENTS = [
    {'title': 'Recargas concluídas', 'subtitle': 'Hoje - 24 transações', 'amount': Decimal('486.20')},
    {'title': 'Recargas concluídas', 'subtitle': '10/10 - 15 transações', 'amount': Decimal('578.30')},
]


def _cents(value):
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def is_demo(app):
    return bool(getattr(getattr(app, 'api', None), 'is_demo', False))


def _path():
    storage = Path(os.environ.get('FLET_APP_STORAGE_DATA') or Path.home() / '.chargegrid')
    return storage / 'payouts.json'


def _load_payouts(app):
    if is_demo(app):
        return getattr(app, '_demo_payouts', [])
    try:
        data = json.loads(_path().read_text())
        return data if isinstance(data, list) else []
    except (OSError, ValueError, TypeError):
        return []


def _save_payouts(app, items):
    if is_demo(app):
        app._demo_payouts = items
        return
    try:
        _path().parent.mkdir(parents=True, exist_ok=True)
        _path().write_text(json.dumps(items, ensure_ascii=False))
    except OSError:
        app._demo_payouts = items  # sem armazenamento: vale só nesta sessão


def set_owner_net(app, owner_net):
    """Guarda o repasse ao dono (``totals.owner_net`` de ``/owner/margin``), base do saldo da conta real."""
    app._payout_net = _cents(owner_net)


async def load_owner_net(app, now=None):
    """Busca o repasse dos últimos ``NET_DAYS`` dias e guarda em ``app``; sem rede, mantém o último valor."""
    if is_demo(app):
        return None
    end = now or datetime.now(timezone.utc)
    params = {'from': (end - timedelta(days=NET_DAYS)).isoformat(), 'to': end.isoformat(), 'limit': 1}
    api = app.api
    report = await (api.owner_margin(params) if hasattr(api, 'owner_margin') else
                    api.request('GET', 'owner/margin', params=params))
    net = ((report or {}).get('totals') or {}).get('owner_net')
    if net is not None:
        set_owner_net(app, net)
    return getattr(app, '_payout_net', None)


def _gross_total(app):
    if is_demo(app):
        return sum((m['amount'] for m in _DEMO_MOVEMENTS), Decimal('0'))
    return _cents(getattr(app, '_payout_net', 0))


def _paid_out(app):
    return sum((_cents(p.get('gross')) for p in _load_payouts(app)), Decimal('0'))


def available(app):
    """Saldo disponível para resgate."""
    if is_demo(app):
        return max(DEMO_BALANCE - _paid_out(app), Decimal('0'))
    return max(_gross_total(app) - _paid_out(app), Decimal('0'))


def movements(app):
    """Movimentações (mais recentes primeiro): ``[{title, subtitle, amount: Decimal}]`` (resgates negativos)."""
    paid = [{'title': 'Resgate' + (' (sexta-feira)' if p.get('mode') == 'friday' else ' (agora)'),
             'subtitle': f"{p.get('protocol', '')} · {p.get('status', '')}", 'amount': -_cents(p.get('gross'))}
            for p in reversed(_load_payouts(app))]
    if is_demo(app):
        return paid + [dict(m) for m in _DEMO_MOVEMENTS]
    revenue = _gross_total(app)
    base = [{'title': 'Repasse das recargas', 'subtitle': 'Após a comissão da plataforma · últimos 12 meses',
             'amount': revenue}] if revenue > 0 else []
    return paid + base


def quote(app, mode):
    """Valores de um resgate sem registrá-lo: gross, fee, net."""
    gross = available(app)
    fee = _cents(gross * FEE_RATE) if mode == 'now' else Decimal('0.00')
    return {'gross': gross, 'fee': fee, 'net': gross - fee}


def destination(app):
    return DEMO_DESTINATION if is_demo(app) else REAL_DESTINATION


def request(app, mode):
    """Registra o resgate (simulado). ``mode``: ``'now'`` (taxa 2%) ou ``'friday'`` (sem taxa)."""
    if mode not in ('now', 'friday'):
        raise ValueError('modalidade inválida')
    values = quote(app, mode)
    if values['gross'] <= 0:
        raise ValueError('sem saldo disponível')
    items = list(_load_payouts(app))
    base = DEMO_FIRST_PROTOCOL if is_demo(app) else 1001
    result = {**values, 'mode': mode, 'destination': destination(app), 'status': 'Em processamento',
              'protocol': f'CG-RS-{base + len(items)}'}
    items.append({'mode': mode, 'gross': str(values['gross']), 'fee': str(values['fee']), 'net': str(values['net']),
                  'destination': result['destination'], 'status': result['status'], 'protocol': result['protocol']})
    _save_payouts(app, items)
    return result
