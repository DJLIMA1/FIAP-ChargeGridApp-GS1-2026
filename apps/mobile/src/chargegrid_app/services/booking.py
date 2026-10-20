"""Regras do assistente de recarga (consumidor): agrupamento de conectores, horários, estimativas e totais.

Tudo aqui é puro (sem Flet) para ser testável. O pagamento é SIMULADO: nenhum dado de cartão é guardado
nem enviado, e o saldo usa ``services.wallet``.
"""

import zlib
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from chargegrid_core import power as power_rules

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
        # ``price``: o que o motorista paga agora (base × demanda, calculado pela API).
        group = groups.setdefault(key, {'key': key, 'type': point.get('connector_type') or 'Conector',
                                        'power_kw': to_decimal(point.get('power_kw')), 'price': to_decimal(
                                            point.get('dynamic_price_per_kwh') or point.get('price_per_kwh')),
                                        'base_price': to_decimal(point.get('price_per_kwh')),
                                        'connectors': [], 'free': []})
        group['connectors'].append(point)
        if is_available(station, point):
            group['free'].append(point)
    for group in groups.values():
        # Potência efetiva (limites do vendedor e divisão do posto, calculados pela API).
        pool = group['free'] or group['connectors']
        group['effective_kw'] = max(to_decimal(p.get('effective_power_kw') or p.get('power_kw')) for p in pool)
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


def driver_power(group, car=None):
    """Limite geral do motorista neste grupo: ``min(efetivo do conector, carro)``.

    ``car``: ``{'max_ac_kw', 'max_dc_kw'}`` (``vehicle_state.car_specs``). Devolve ``{'kw', 'by'}`` com
    ``by`` = ``'car'`` (o carro é o gargalo), ``'station'`` (o posto limita o conector) ou ``None``."""
    rating = group['power_kw']
    effective = min(rating, group.get('effective_kw') or rating)
    result = power_rules.driver_limit(effective, group['type'], max_ac_kw=(car or {}).get('max_ac_kw'),
                                      max_dc_kw=(car or {}).get('max_dc_kw'))
    by = 'car' if result['limited_by'] == 'car' and result['kw'] < effective else (
        'station' if effective < rating else None)
    return {'kw': result['kw'], 'by': by}


POWER_BADGES = {'station': 'limitado pelo posto', 'car': 'limite do seu carro'}


def power_title(group, key, car=None):
    """``Até 40 kW · limitado pelo posto`` (o selo só aparece na opção máxima)."""
    value = power_options(group, car)[key][0]
    badge = POWER_BADGES.get(driver_power(group, car)['by']) if key == 'max' else None
    return f'Até {fmt_number(value)} kW' + (f' · {badge}' if badge else '')


def power_options(group, car=None):
    """Opções de potência: máxima permitida (conector efetivo ∩ carro) e uma reduzida (metade)."""
    top = driver_power(group, car)['kw'] if 'effective_kw' in group or car else group['power_kw']
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


def estimate(power_kw, price_per_kwh, *, minutes=None, value=None, energy=None):
    """Estimativa de recarga: devolve ``{minutes, energy_kwh, cost}`` (custo da energia, sem taxa).

    Por tempo: energia = potência x horas. Por valor: energia = valor / tarifa.
    Por autonomia (``energy`` em kWh, de ``autonomy_energy``): tempo = energia / potência, custo = energia x tarifa.
    """
    power, price = to_decimal(power_kw), to_decimal(price_per_kwh)
    if power <= 0:
        raise ValueError('Potência inválida.')
    if energy is not None:
        amount = max(Decimal(0), to_decimal(energy))
        needed = (amount * 60 / power).to_integral_value(rounding=ROUND_CEILING) if amount else Decimal(0)
        return {'minutes': int(needed), 'energy_kwh': amount.quantize(CENT, rounding=ROUND_HALF_UP),
                'cost': (amount * price).quantize(CENT, rounding=ROUND_HALF_UP)}
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


def parse_km(text):
    raw = str(text or '').strip().lower().replace('km', '').strip()
    if not raw.isascii() or not raw.isdigit() or not 1 <= int(raw) <= 2000:
        raise ValueError('Informe a autonomia em km inteiros (ex.: 120).')
    return int(raw)


def autonomy_energy(km, consumption_kwh_per_100km, soc_percent, usable_kwh):
    """Energia para ``km`` de autonomia: ``km x consumo / 100``, limitada ao espaço livre da bateria
    (``(100 - SoC)% x bateria útil``). Devolve ``{energy_kwh, wanted_kwh, free_kwh, capped, km}``
    (``km`` = autonomia efetivamente adicionada)."""
    consumption = to_decimal(consumption_kwh_per_100km)
    if consumption <= 0:
        raise ValueError('Consumo do carro inválido.')
    wanted = to_decimal(km) * consumption / 100
    soc = min(Decimal(100), max(Decimal(0), to_decimal(soc_percent)))
    free = (Decimal(100) - soc) / 100 * max(Decimal(0), to_decimal(usable_kwh))
    capped = wanted > free
    energy = free if capped else wanted
    return {'energy_kwh': energy.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP),
            'wanted_kwh': wanted.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP),
            'free_kwh': free.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP), 'capped': capped,
            'km': int((energy / consumption * 100).to_integral_value(rounding=ROUND_HALF_UP))}


def autonomy_note(result):
    """Aviso gentil quando a bateria não comporta toda a autonomia pedida (nunca mostra o SoC)."""
    if not result or not result.get('capped'):
        return None
    if result['energy_kwh'] <= 0:
        return 'A bateria do carro já está cheia: não há autonomia para adicionar agora.'
    return (f"A bateria comporta cerca de {result['km']} km agora; a recarga vai até encher "
            '(o restante não é cobrado).')


def autonomy_limits(km, car, power_kw, price_per_kwh, max_minutes=None):
    """Autonomia → limites que a API entende: ``{max_duration_minutes, max_cost?, energy_kwh, capped, km}``.

    ``car``: ``{'consumption', 'usable_kwh', 'soc'}`` (``services.vehicle_state.snapshot``).
    Tempo = energia / potência (arredondado para cima, 1..``max_minutes``); valor = energia x tarifa.
    """
    result = autonomy_energy(km, car['consumption'], car['soc'], car['usable_kwh'])
    if result['energy_kwh'] <= 0:
        raise ValueError('A bateria do carro já está cheia: não há autonomia para adicionar agora.')
    quote = estimate(power_kw, price_per_kwh, energy=result['energy_kwh'])
    minutes = max(1, quote['minutes'])
    if max_minutes:
        minutes = min(minutes, int(max_minutes))
    limits = {'max_duration_minutes': minutes, 'energy_kwh': quote['energy_kwh'], 'capped': result['capped'],
              'km': result['km'], 'cost': quote['cost']}
    if to_decimal(price_per_kwh) > 0:
        limits['max_cost'] = max(CENT, quote['cost'])
    return limits


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
