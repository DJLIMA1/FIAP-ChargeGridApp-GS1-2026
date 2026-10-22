"""Regras do assistente de recarga (consumidor): agrupamento de conectores, horários, estimativas e totais.

Tudo aqui é puro (sem Flet) para ser testável. O pagamento é SIMULADO: nenhum dado de cartão é guardado
nem enviado, e o saldo usa ``services.wallet``.
"""

import zlib
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from chargegrid_core import power as power_rules
from chargegrid_core.charge_plan import autonomy_energy, charge_maxima
from chargegrid_core.charge_plan import autonomy_note as autonomy_note
from chargegrid_core.charge_plan import parse_km as parse_km
from chargegrid_core.chargers import link as charger_link

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


def kiosk_held(group):
    """Conectores do grupo travados por um pedido do totem (``kiosk_in_use`` do ponto)."""
    return sum(1 for point in group['connectors'] if point.get('kiosk_in_use') is True)


def charger_offline_text(count, total=None):
    """``Carregador offline`` (o único do grupo) ou ``2 carregadores offline``."""
    if count == 1:
        return charger_link.CHARGER_OFFLINE_SHORT if total == 1 else '1 carregador offline'
    return f'{count} carregadores offline'


def group_subtitle(group):
    total, free = len(group['connectors']), len(group['free'])
    held = kiosk_held(group)
    # Tela da estação com contato, mas o carregador do ponto sem resposta: nunca conta como livre.
    down = sum(1 for point in group['connectors'] if point.get('unavailable_reason') == charger_link.CHARGER_OFFLINE)
    if down:
        offline = charger_offline_text(down, total)
        if down == total:
            return f'{offline} · use outro ponto desta estação'
        head = (f"{free} de {total} conectores {'livre' if free == 1 else 'livres'}" if free
                else 'Nenhum conector livre')
        return f'{head} · {offline}'
    if total == 1:
        return '1 conector livre' if free else ('Ponto em uso no totem' if held else 'Indisponível no momento')
    if free == total:
        return f'{total} conectores livres'
    if not free:
        return 'Nenhum conector livre' + (f' · {held} em uso no totem' if held else '')
    return (f"{free} de {total} conectores {'livre' if free == 1 else 'livres'}"
            + (f' · {held} em uso no totem' if held else ''))


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


def tier_price(point, tier='max'):
    """Preço comercial escolhido; um limite físico menor nunca seleciona o desconto."""
    values = point.get('speed_prices') or {}
    maximum = to_decimal(values.get('max', point.get('dynamic_price_per_kwh')
                                    if point.get('dynamic_price_per_kwh') is not None
                                    else point.get('price_per_kwh', point.get('price', 0))))
    return to_decimal(values.get('reduced', maximum * Decimal('0.8'))) if tier == 'reduced' else maximum


def group_price(group, tier='max', connector_id=None):
    pool = group.get('free') or group.get('connectors') or []
    point = next((p for p in pool if p.get('id') == connector_id), pool[0] if pool else group)
    return tier_price(point, tier)


def speed_subtitle(group, tier='max', car=None, connector_id=None):
    label = 'Mais rápida' if tier == 'max' else 'Mais econômica'
    return f'{label} · {money(group_price(group, tier, connector_id))}/kWh'


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


# ---------------------------------------------------------------------- máximos por modo
# Atalhos (chips) de cada modo; o último chip é sempre o máximo ("Máx. 120 min"). Atalhos acima do
# máximo não aparecem (mesma regra dos atalhos de duração da etapa "Definir limites").
TIME_PRESETS = (15, 30, 60)
VALUE_PRESETS = (20, 50, 100)
KM_PRESETS = (50, 100, 200)
UNITS = {'time': ('', 'min'), 'value': ('R$', ''), 'autonomy': ('', 'km')}  # (prefixo, sufixo)


def point_minutes(point):
    """Duração máxima do ponto (``max_duration_minutes``); sem o dado, 24 h (teto da API)."""
    try:
        return max(1, min(1440, int((point or {}).get('max_duration_minutes') or 1440)))
    except (TypeError, ValueError):
        return 1440


def selected_point(group, connector_id=None):
    pool = group.get('free') or group.get('connectors') or []
    return next((p for p in pool if p.get('id') == connector_id),
                next((p for p in group.get('connectors') or [] if p.get('id') == connector_id),
                     pool[0] if pool else {}))


def amount_limits(power_kw, price_per_kwh, max_minutes, car=None):
    """Máximos (``charge_plan.charge_maxima``) com a potência e a tarifa final (velocidade, horário e
    demanda já aplicados pela API) e o carro do perfil (``vehicle_state.snapshot``; SoC escondido)."""
    car = car or {}
    result = charge_maxima(power_kw, price_per_kwh, max_minutes, consumption=car.get('consumption'),
                           soc=car.get('soc'), usable_kwh=car.get('usable_kwh'))
    if to_decimal(power_kw) <= 0:  # potência desconhecida: só o tempo do ponto tem máximo
        result.update(value=None, km=None)
    return {**result, 'power_kw': to_decimal(power_kw), 'price_per_kwh': to_decimal(price_per_kwh)}


def group_limits(group, tier='max', connector_id=None, car_power=None, car=None):
    """Máximos do assistente para o conector escolhido, na velocidade ``tier``."""
    tier = tier or 'max'
    return amount_limits(power_options(group, car_power)[tier][0], group_price(group, tier, connector_id),
                         point_minutes(selected_point(group, connector_id)), car)


def _reason(limits):
    if limits['bound'] == 'battery':
        return 'o que cabe na bateria do seu carro'
    return f"o que cabe em {limits['minutes']} min a {fmt_number(limits['power_kw'])} kW"


def _value_text(value):
    return f"{to_decimal(value).quantize(CENT):f}".replace('.', ',')


def amount_max_label(by, limits):
    """``120 min`` · ``R$ 61,15`` · ``192 km`` (ou ``None`` quando o modo não tem máximo)."""
    if by == 'value':
        return money(limits['value']).replace('R$', 'R$ ') if limits.get('value') is not None else None
    if by == 'autonomy':
        return f"{limits['km']} km" if limits.get('km') is not None else None
    return f"{limits['minutes']} min"


def amount_hint(by, limits):
    """Linha "Máx.: …" mostrada antes de o motorista digitar."""
    if by == 'value' and limits.get('value') is None:
        free = limits.get('price_per_kwh') is not None and limits['price_per_kwh'] <= 0
        return 'Este ponto não cobra pela energia: defina a recarga por tempo.' if free else None
    if by == 'autonomy' and limits.get('km') is not None and limits['km'] < 1:
        return 'A bateria do carro já está cheia: não há autonomia para adicionar agora.'
    label = amount_max_label(by, limits)
    if label is None:
        return None
    if by == 'time':
        return f'Máx.: {label} (limite deste carregador)'
    return f'Máx.: {label} · {_reason(limits)}'


def amount_presets(by, limits):
    """Chips ``[(rótulo, texto do campo)]``: atalhos abaixo do máximo e, por último, ``Máx. …``."""
    if by == 'value':
        top = limits.get('value')
        if top is None or top < CENT:
            return []
        chips = [(f'R$ {value}', f'{value},00') for value in VALUE_PRESETS if value < top]
        return chips + [(f'Máx. {amount_max_label(by, limits)}', _value_text(top))]
    if by == 'autonomy':
        top = limits.get('km')
        if top is None or top < 1:
            return []
        return [(f'{km} km', str(km)) for km in KM_PRESETS if km < top] + [(f'Máx. {top} km', str(top))]
    top = limits['minutes']
    return [(f'{minutes} min', str(minutes)) for minutes in TIME_PRESETS if minutes < top] + \
        [(f'Máx. {top} min', str(top))]


def chip_width(label):
    """Largura do chip pelo texto (como os atalhos do cadastro de ponto): o ``Row`` com quebra não estica."""
    return max(66, len(label) * 8 + 32)


def amount_error(by, text, limits):
    """Erro do campo enquanto o motorista digita (``None`` = ok ou ainda vazio)."""
    if not str(text or '').strip():
        return None
    try:
        if by == 'value':
            amount, top = parse_value(text), limits.get('value')
        elif by == 'autonomy':
            if limits.get('km') is not None and limits['km'] < 1:
                return 'A bateria do carro já está cheia: não há autonomia para adicionar agora.'
            amount, top = parse_km(text), limits.get('km')
        else:
            amount, top = parse_minutes(text), limits['minutes']
    except (ValueError, ArithmeticError) as exc:
        return str(exc)
    if top is not None and amount > top:
        return f'Acima do máximo ({amount_max_label(by, limits)}). Toque em Máx. ou diminua.'
    return None


def clamp_text(by, text, limits):
    """Texto padrão (ex.: ``30``) limitado ao máximo do modo."""
    label = amount_presets(by, limits)
    if amount_error(by, text, limits) is None or not label:
        return text
    return label[-1][1]


def reservation_code(reservation_id):
    """Código curto estável ``CG-0842`` derivado do id da reserva."""
    return f'CG-{zlib.crc32(str(reservation_id).encode()) % 10000:04d}'
