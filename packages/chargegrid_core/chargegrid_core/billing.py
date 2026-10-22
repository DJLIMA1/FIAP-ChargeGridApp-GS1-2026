"""Teto pré-pago e acerto da recarga, em centavos inteiros (mesma regra na API e no app).

Fluxo: o motorista aceita um **teto** (orçamento) → o provedor pré-autoriza (cartão) ou cobra
(Pix) esse valor → a recarga só começa depois da confirmação → no fim, a energia confirmada pelo
equipamento define o valor. Cartão: captura só o consumido e libera o resto. Pix: devolve a
diferença.

* ``quote_cap``: teto de energia de um orçamento (por tempo, valor ou energia).
* ``energy_cents``: custo da energia medida, igual ao ``cost_estimate`` da API, em centavos.
* ``settle_amounts``: quanto fica, quanto volta, o que é perdoado e o que não é cobrado.

Regras do acerto
----------------
1. Devido = energia + taxa fixa + permanência (taxa de permanência da frente de overstay).
2. Nunca se cobra acima do valor autorizado/pago (``amount_cents``). Energia + taxa acima do
   teto **de energia** aceito (``energy_cap_cents`` + taxa fixa) é **perdoada** (``waived``),
   mesmo quando a autorização também reserva a permanência; permanência além da reserva aceita
   **não é cobrada** (``uncollected``) — nada de cobrança extra silenciosa.
3. Cobrança positiva abaixo do mínimo do provedor (R$ 0,50 no cartão em BRL) é perdoada:
   ``below_minimum`` e nada é cobrado.
4. Ação no provedor: autorização retida (cartão) → ``capture`` do valor final (ou ``cancel``
   quando nada fica); valor já cobrado (Pix) → ``refund`` da diferença (ou ``none``).
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation

CURRENCY = 'BRL'
MIN_CHARGE_CENTS = 50
CENT = Decimal('0.01')
MODES = ('time', 'value', 'energy')

# Rótulos (pt-BR) dos estados de pagamento; o ambiente é sempre de teste.
STATUS_LABELS = {
    'awaiting_payment': 'Aguardando pagamento',
    'declined': 'Recusado',
    'authorized': 'Pago (teste)',
    'paid': 'Pago (teste)',
    'in_use': 'Pago (teste) · em uso',
    'expired': 'Expirado',
    'canceled': 'Cancelado',
    'completed': 'Cobrado (teste)',
}


def _decimal(value, name='valor'):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f'{name} inválido') from None
    if not number.is_finite():
        raise ValueError(f'{name} inválido')
    return number


def to_cents(value, rounding=ROUND_HALF_UP) -> int:
    """Reais → centavos inteiros (``Decimal('12.345')`` → ``1235``)."""
    return int((_decimal(value) * 100).quantize(Decimal(1), rounding=rounding))


def money(cents) -> Decimal:
    """Centavos → reais com duas casas (``1235`` → ``Decimal('12.35')``)."""
    return (Decimal(int(cents or 0)) / 100).quantize(CENT)


def energy_cost(energy_wh, price_per_kwh, discount_percent=0) -> Decimal:
    """Custo da energia em reais (4 casas), a mesma conta do ``cost_estimate`` da API."""
    return (
        _decimal(energy_wh) / Decimal(1000) * _decimal(price_per_kwh)
        * Decimal(100 - int(discount_percent or 0)) / Decimal(100)
    ).quantize(Decimal('0.0001'))


def energy_cents(energy_wh, price_per_kwh, discount_percent=0) -> int:
    return to_cents(energy_cost(energy_wh, price_per_kwh, discount_percent))


def effective_price(price_per_kwh, discount_percent=0) -> Decimal:
    return _decimal(price_per_kwh) * Decimal(100 - int(discount_percent or 0)) / Decimal(100)


def quote_cap(mode, *, power_kw, price_per_kwh, discount_percent=0, minutes=None, max_cost=None,
              energy_kwh=None, max_minutes=1440, min_cents=MIN_CHARGE_CENTS) -> dict:
    """Teto de energia de um orçamento: ``{energy_cap_cents, max_duration_minutes, energy_kwh}``.

    * ``time``: energia = potência × minutos; teto = energia × tarifa efetiva (arredondado para
      cima, para o tempo pedido caber);
    * ``value``: teto = valor pedido; duração = energia ÷ potência (para cima), até ``max_minutes``;
    * ``energy``: teto = kWh × tarifa efetiva (para cima); duração como em ``value``.

    ``ValueError`` quando faltam dados ou o teto fica abaixo do mínimo do provedor.
    """
    if mode not in MODES:
        raise ValueError('Modo de orçamento inválido')
    power = _decimal(power_kw, 'Potência')
    if power <= 0:
        raise ValueError('Potência inválida')
    price = effective_price(price_per_kwh, discount_percent)
    if price < 0:
        raise ValueError('Tarifa inválida')
    limit = max(1, int(max_minutes))

    def duration_for(kwh):
        if kwh <= 0:
            return limit
        needed = int((kwh / power * 60).to_integral_value(rounding=ROUND_CEILING))
        return max(1, min(limit, needed))

    if mode == 'time':
        if minutes is None or int(minutes) < 1:
            raise ValueError('Informe o tempo em minutos')
        duration = min(limit, int(minutes))
        kwh = power * Decimal(duration) / 60
        cap = to_cents(kwh * price, ROUND_CEILING)
    elif mode == 'value':
        if max_cost is None or _decimal(max_cost, 'Valor') <= 0:
            raise ValueError('Informe o valor')
        cap = to_cents(max_cost)
        kwh = (money(cap) / price) if price > 0 else Decimal(0)
        duration = duration_for(kwh)
    else:
        if energy_kwh is None or _decimal(energy_kwh, 'Energia') <= 0:
            raise ValueError('Informe a energia em kWh')
        kwh = _decimal(energy_kwh)
        cap = to_cents(kwh * price, ROUND_CEILING)
        duration = duration_for(kwh)
    if cap < min_cents:
        raise ValueError(f'O valor mínimo para pagamento é {format_money(min_cents)}')
    return {'energy_cap_cents': cap, 'max_duration_minutes': duration,
            'energy_kwh': kwh.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)}


def settle_amounts(*, amount_cents, energy_cents, fixed_fee_cents=0, overstay_cents=0,
                   captured_upfront=False, min_charge_cents=MIN_CHARGE_CENTS, energy_cap_cents=None) -> dict:
    """Acerto final (ver regras no topo do módulo). Todos os valores em centavos inteiros.

    ``energy_cap_cents``: teto da energia aceito no orçamento (sem a taxa fixa e sem a reserva da
    permanência). Sem ele (legado), o teto da energia é o valor autorizado inteiro.
    """
    amount = max(0, int(amount_cents))
    fixed = max(0, int(fixed_fee_cents))
    base = max(0, int(energy_cents)) + fixed
    overstay = max(0, int(overstay_cents))
    ceiling = amount if energy_cap_cents is None else min(amount, max(0, int(energy_cap_cents)) + fixed)
    waived = max(0, base - ceiling)
    kept = min(base, ceiling)
    overstay_kept = min(overstay, amount - kept)
    uncollected = overstay - overstay_kept
    charge = kept + overstay_kept
    below_minimum = 0 < charge < min_charge_cents
    if below_minimum:
        waived += kept
        uncollected += overstay_kept
        charge = 0
    returned = amount - charge
    if captured_upfront:
        action = 'refund' if returned > 0 else 'none'
    else:
        action = 'capture' if charge > 0 else 'cancel'
    return {'charge_cents': charge, 'return_cents': returned, 'waived_cents': waived,
            'uncollected_cents': uncollected, 'below_minimum': below_minimum, 'action': action}


def format_money(cents) -> str:
    """``1235`` → ``R$ 12,35``."""
    whole, frac = f'{money(cents):.2f}'.split('.')
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return f"R$ {'.'.join(groups)},{frac}"


def status_label(status, *, charge_cents=None, return_cents=None, method=None) -> str:
    """Rótulo do pagamento para o motorista, sempre identificado como teste."""
    if status == 'completed':
        if not charge_cents:
            return 'Devolvido (teste)'
        text = f'Cobrado {format_money(charge_cents)} (teste)'
        if return_cents:
            text += f' · Devolvido {format_money(return_cents)}'
        return text
    if status in ('expired', 'canceled') and method:
        return STATUS_LABELS[status] + ' · valor devolvido'
    return STATUS_LABELS.get(status, status)
