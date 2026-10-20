"""Tarifas do posto: leitura/formatação de números e a taxa de permanência (regra ``rotation``).

As regras ficam na API (``GET/PUT stations/{id}/pricing``) e o cálculo da tarifa por demanda
é ``chargegrid_core.pricing`` (o mesmo na API e na conta demo). Aqui só há utilidades de tela.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from chargegrid_core.pricing import (  # noqa: F401 - reexportados para as telas
    days_label,
    multiplier_label,
)

_CENT = Decimal('0.01')


def parse_decimal(text, *, minimum=Decimal('0'), maximum=Decimal('9999')):
    """``1,89`` / ``1.234,50`` / ``0.2`` -> ``Decimal``; ``None`` se vazio, inválido ou fora da faixa."""
    if isinstance(text, (int, float, Decimal)):
        raw = str(text)
    else:
        raw = ''.join(ch for ch in str(text or '') if ch.isdigit() or ch in ',.')
    if not raw or not any(ch.isdigit() for ch in raw):
        return None
    if ',' in raw:
        raw = raw.replace('.', '').replace(',', '.')
    elif raw.count('.') > 1:
        raw = raw.replace('.', '')
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    if not value.is_finite() or value < minimum or value > maximum:
        return None
    return value.quantize(Decimal('0.0001'))


def parse_int(text, *, minimum=1, maximum=1440):
    """Inteiro a partir de ``30``; ``None`` se vazio, com vírgula/ponto ou fora da faixa."""
    raw = str(text or '').strip()
    if not raw.isdigit():
        return None
    value = int(raw)
    return value if minimum <= value <= maximum else None


parse_minutes = parse_int


def parse_time(text):
    """``18:00`` (ou ``18``, ``18h30``) -> ``'18:00'``; ``None`` se inválido."""
    raw = str(text or '').strip().lower().replace('h', ':')
    parts = raw.split(':')
    if len(parts) > 2 or not parts[0].isdigit() or (len(parts) == 2 and parts[1] and not parts[1].isdigit()):
        return None
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) == 2 and parts[1] else 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f'{hour:02d}:{minute:02d}'


def input_number(value, places=2):
    """``Decimal('1.8900')`` -> ``'1,89'`` para preencher um campo numérico."""
    amount = Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return str(amount).replace('.', ',')


def fmt_money(value):
    """``Decimal`` -> ``R$ 0,20`` (2 casas, meio para cima)."""
    amount = Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)
    return f"R$ {str(amount).replace('.', ',')}"


def rotation_intervals(rule, minutes):
    """Quantos intervalos de rotatividade foram cobrados após ``minutes`` de ocupação."""
    if not rule or not rule.get('enabled') or minutes is None:
        return 0
    start, step = int(rule['start_after_min']), int(rule['interval_min'])
    if minutes <= start or step <= 0:
        return 0
    return int((minutes - start) // step)


def rotation_fee(rules, minutes):
    """Valor adicional de rotatividade (R$) para ``minutes`` de ocupação, limitado ao teto ``max_amount``
    (como ``chargegrid_core.overstay.fee_due`` da API: ``min(teto, valor × intervalos)``)."""
    rule = (rules or {}).get('rotation')
    if not rule:
        return Decimal('0')
    fee = Decimal(str(rule['amount'])) * rotation_intervals(rule, minutes)
    if rule.get('max_amount') is not None:
        fee = min(fee, Decimal(str(rule['max_amount'])))
    return fee


def rotation_summary(rule):
    """``R$ 1,00 a cada 1 min após 10 min · máx. R$ 30,00`` (teto só quando a API o devolve)."""
    text = f"{fmt_money(rule['amount'])} a cada {rule['interval_min']} min após {rule['start_after_min']} min"
    if rule.get('max_amount') is not None:
        text += f" · máx. {fmt_money(rule['max_amount'])}"
    return text + ('' if rule.get('enabled') else ' · Inativa')


def base_price(connectors):
    """Menor ``price_per_kwh`` entre os conectores ativos (``None`` sem conectores)."""
    prices = []
    for connector in connectors or []:
        if connector.get('retired') or connector.get('active') is False:
            continue
        try:
            prices.append(Decimal(str(connector['price_per_kwh'])))
        except (KeyError, InvalidOperation):
            continue
    return min(prices) if prices else None
