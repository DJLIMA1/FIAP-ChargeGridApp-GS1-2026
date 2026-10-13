"""Apoio puro (sem Flet) da tela Modo Motorista: formulário ↔ perfil e leitura do plano."""
from chargegrid_core.driver import PRESETS, parse_hhmm
from chargegrid_core.formatting import brl, duration, km, kwh

from ..api_client import ApiError

MEALS = (('almoco', 'Almoço', '12:30', 60, '45'), ('jantar', 'Jantar', '20:00', 45, '30'),
         ('lanche', 'Lanche', '16:30', 20, '30'))
FLEX_CHOICES = (('15', '±15 min'), ('30', '±30 min'), ('45', '±45 min'), ('60', '±1 h'), ('flex', 'Horário flexível'))
MODES = (('full_shift', 'Turno completo (hoje ou amanhã)'), ('auto', 'Do horário atual até o fim do turno'))
KIND_LABELS = {'rodando': 'Rodando', 'recarga': 'Recarga', 'refeicao_recarga': 'Refeição + recarga',
               'refeicao': 'Refeição', 'pausa': 'Pausa'}
AMENITY_TEXT = {'restaurante': 'Restaurante', 'cafe': 'Café', 'banheiro': 'Banheiro', 'shopping': 'Shopping',
                'conveniencia': 'Conveniência'}


def number(value, label, low, high, *, integer=False):
    text = str(value if value is not None else '').strip().replace(',', '.')
    try:
        result = float(text)
    except ValueError as exc:
        raise ApiError(f'Informe {label} entre {low:g} e {high:g}.') from exc
    if result != result or not low <= result <= high or (integer and result != int(result)):
        raise ApiError(f'Informe {label} entre {low:g} e {high:g}.')
    return int(result) if integer else result


def clock(value, label):
    try:
        minute = parse_hhmm(value)
    except ValueError as exc:
        raise ApiError(f'Informe {label} no formato HH:MM (ex.: 18:30).') from exc
    return f'{minute // 60:02d}:{minute % 60:02d}'


def vehicle_summary(vehicle):
    """Texto curto do carro (sempre marcado como estimativa)."""
    preset = PRESETS.get(vehicle.get('preset') or '')
    battery = vehicle.get('usable_battery_kwh') or (preset.usable_battery_kwh if preset else None)
    consumption = vehicle.get('consumption_kwh_per_100km') or (preset.consumption_kwh_per_100km if preset else None)
    if not battery or not consumption:
        return 'Informe bateria útil e consumo do seu carro.'
    autonomy = round(float(battery) / float(consumption) * 100)
    return (f'Bateria útil {kwh(battery)} · consumo {kwh(consumption)}/100 km · '
            f'autonomia ~{autonomy} km (estimativa)')


def meal_flex(meal):
    if meal.get('flexible'):
        return 'flex'
    value = str(meal.get('flex_minutes', 30))
    return value if value in dict(FLEX_CHOICES) else '30'


def build_meal(kind, enabled, start, duration_minutes, flex):
    label = dict((k, name) for k, name, *_ in MEALS)[kind]
    meal = {'kind': kind, 'enabled': bool(enabled), 'start': clock(start, f'o horário do {label.lower()}'),
            'duration_minutes': number(duration_minutes, f'a duração do {label.lower()} (min)', 10, 120, integer=True)}
    if flex == 'flex':
        meal.update(flexible=True, flex_minutes=120)
    else:
        meal.update(flexible=False, flex_minutes=int(flex))
    return meal


def plan_accessible_summary(plan):
    totals = plan.get('totals') or {}
    stops = plan.get('stops') or []
    parts = [f"Plano de {plan['window']['start']} a {plan['window']['end']}",
             f"lucro líquido estimado {brl(totals.get('net_profit'))}",
             f"{len(stops)} parada{'s' if len(stops) != 1 else ''} de recarga"]
    for stop in stops:
        parts.append(f"{stop['start']} {stop['meal'] + ' e recarga' if stop['meal'] else 'recarga'} "
                     f"em {stop['station_name']}")
    return '; '.join(parts) + '.'


def soc_summary(plan):
    rows = [row for row in plan.get('slots') or [] if row.get('soc') is not None]
    if not rows:
        return 'Sem dados de bateria.'
    low = min(rows, key=lambda row: row['soc'])
    return (f"Bateria projetada: começa em {rows[0]['soc']:.0f}%, mínimo de {low['soc']:.0f}% às {low['time']} "
            f"e termina em {rows[-1]['soc']:.0f}%.")


def stop_line(stop):
    return (f"+{kwh(stop['kwh'])} · {brl(stop['cost'])} · {duration(stop['charge_minutes'])} de carga · "
            f"{km(stop['detour_km'])} de desvio")


def amenities_text(amenities):
    names = []
    for amenity in amenities or ():
        text = AMENITY_TEXT.get(amenity.get('kind'), amenity.get('kind', ''))
        if amenity.get('name'):
            text += f" {amenity['name']}"
        names.append(text)
    return ' · '.join(names)


def stop_is_now(plan, stop):
    """A primeira parada começa no primeiro slot de um plano a partir de agora: dá para reservar."""
    slots = plan.get('slots') or []
    return plan.get('mode') == 'auto' and bool(slots) and stop.get('start_at') == slots[0].get('at')
