"""Regras do assistente de recarga (consumidor): agrupamento de conectores, horários, estimativas e totais.

Tudo aqui é puro (sem Flet) para ser testável. O pagamento é SIMULADO: nenhum dado de cartão é guardado
nem enviado, e o saldo usa ``services.wallet``.
"""

import zlib
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

RESERVATION_FEE = Decimal('4.90')
TOLERANCE_MINUTES = 15
SLOT_COUNT = 3
SLOT_STEP_MINUTES = 30
MIN_LEAD_MINUTES = 10
CENT = Decimal('0.01')


def to_decimal(value, default='0'):
    try:
        return Decimal(str(value).strip().replace(',', '.'))
    except (ArithmeticError, ValueError):
        return Decimal(default)


def fmt_number(value, digits=1):
    """``60`` -> ``60``; ``7.2`` -> ``7,2`` (sem zeros à direita)."""
    number = to_decimal(value).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    text = f'{number:f}'
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text.replace('.', ',')


def money(value):
    """``R$56,70`` (formato compacto do assistente)."""
    amount = to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
    whole, cents = f'{abs(amount):.2f}'.split('.')
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return f"{'-' if amount < 0 else ''}R${'.'.join(groups)},{cents}"


def is_available(station, point):
    return (station.get('active') is not False and point.get('active') is not False
            and not point.get('retired') and point.get('online') is not False
            and point.get('available') is True
            and point.get('availability_status') in (None, 'available'))


def group_connectors(station):
    """Agrupa conectores iguais (tipo + potência): ``[{key, type, power_kw, price, connectors, free}]``."""
    groups = {}
    for point in station.get('connectors', []) or []:
        if point.get('retired') or point.get('active') is False:
            continue
        key = f"{point.get('connector_type')}|{fmt_number(point.get('power_kw'), 1)}"
        group = groups.setdefault(key, {'key': key, 'type': point.get('connector_type') or 'Conector',
                                        'power_kw': to_decimal(point.get('power_kw')), 'price': to_decimal(
                                            point.get('price_per_kwh')), 'connectors': [], 'free': []})
        group['connectors'].append(point)
        if is_available(station, point):
            group['free'].append(point)
    return sorted(groups.values(), key=lambda item: (-item['power_kw'], item['type']))


def group_title(group):
    return f"{group['type']} - {fmt_number(group['power_kw'])} kW"


def group_subtitle(group):
    total, free = len(group['connectors']), len(group['free'])
    if total == 1:
        return '1 conector livre' if free else 'Indisponível no momento'
    if free == total:
        return f'{total} conectores livres'
    if not free:
        return 'Nenhum conector livre'
    return f"{free} de {total} conectores {'livre' if free == 1 else 'livres'}"


def power_options(group):
    """Opções de potência: máxima do conector e uma reduzida (metade)."""
    top = group['power_kw']
    reduced = (top / 2).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    return {'max': (top, 'Mais rápida'), 'reduced': (reduced, 'Reduz a potência máxima')}


def time_slots(now=None, count=SLOT_COUNT):
    """Próximos horários de meia em meia hora, com pelo menos ``MIN_LEAD_MINUTES`` de antecedência."""
    now = now or datetime.now()
    base = now.replace(second=0, microsecond=0) + timedelta(minutes=MIN_LEAD_MINUTES)
    first = base.replace(minute=0) + timedelta(minutes=-(-base.minute // SLOT_STEP_MINUTES) * SLOT_STEP_MINUTES)
    if first < base:
        first += timedelta(minutes=SLOT_STEP_MINUTES)
    return [(first + timedelta(minutes=SLOT_STEP_MINUTES * index)).strftime('%H:%M') for index in range(count)]


def estimate(power_kw, price_per_kwh, *, minutes=None, value=None):
    """Estimativa de recarga: devolve ``{minutes, energy_kwh, cost}`` (custo da energia, sem taxa).

    Por tempo: energia = potência x horas. Por valor: energia = valor / tarifa.
    """
    power, price = to_decimal(power_kw), to_decimal(price_per_kwh)
    if power <= 0:
        raise ValueError('Potência inválida.')
    if value is not None:
        cost = to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
        energy = cost / price if price > 0 else Decimal(0)
        needed = (energy / power * 60).to_integral_value(rounding=ROUND_CEILING) if energy else Decimal(0)
        return {'minutes': int(needed), 'energy_kwh': energy.quantize(CENT), 'cost': cost}
    minutes = int(minutes)
    energy = power * Decimal(minutes) / 60
    return {'minutes': minutes, 'energy_kwh': energy.quantize(CENT),
            'cost': (energy * price).quantize(CENT, rounding=ROUND_HALF_UP)}


def total(cost, reserving):
    return (to_decimal(cost) + (RESERVATION_FEE if reserving else 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def parse_minutes(text):
    raw = str(text or '').strip()
    if not raw.isascii() or not raw.isdigit() or int(raw) < 1:
        raise ValueError('Informe o tempo em minutos inteiros (ex.: 30).')
    return int(raw)


def parse_value(text):
    raw = str(text or '').strip().replace('R$', '').replace(' ', '')
    if ',' in raw:
        raw = raw.replace('.', '').replace(',', '.')
    try:
        number = Decimal(raw)
    except ArithmeticError:
        raise ValueError('Informe o valor em reais (ex.: 249,90).') from None
    if number <= 0:
        raise ValueError('Informe um valor maior que zero.')
    return number.quantize(CENT, rounding=ROUND_HALF_UP)


def reservation_code(reservation_id):
    """Código curto estável ``CG-0842`` derivado do id da reserva."""
    return f'CG-{zlib.crc32(str(reservation_id).encode()) % 10000:04d}'
