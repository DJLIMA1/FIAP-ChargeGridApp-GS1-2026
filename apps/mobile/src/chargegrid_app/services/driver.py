"""Apoio puro (sem Flet) da tela Modo Motorista: formulário ↔ perfil e leitura do plano."""
from datetime import timedelta

from chargegrid_core.driver import (
    PRESETS,
    DriverPreferences,
    default_profile,
    parse_hhmm,
    resolve_earnings,
    vehicle_from_dict,
)
from chargegrid_core.formatting import brl, duration, km, kwh

from ..api_client import ApiError

MEALS = (('almoco', 'Almoço', '12:30', 60, '45'), ('jantar', 'Jantar', '20:00', 45, '30'),
         ('lanche', 'Lanche', '16:30', 20, '30'))
FLEX_CHOICES = (('15', '±15 min'), ('30', '±30 min'), ('45', '±45 min'), ('60', '±1 h'), ('flex', 'Horário flexível'))
MODES = (('full_shift', 'Turno completo'), ('auto', 'Do agora até o fim do turno'))
# Refeições mostradas em Ajustes (o lanche salvo por versões antigas é mantido, só não aparece).
VISIBLE_MEALS = ('almoco', 'jantar')
AUTO_SHIFT_HOURS = 10
TIME_OPTIONS = tuple(f'{hour:02d}:{minute:02d}' for hour in range(24) for minute in (0, 30))
WEATHER_STATUS_TEXT = {
    'sem_localizacao': 'Informe onde você está para ver o clima',
    'indisponivel': 'Clima indisponível agora · usando horários típicos',
    'desativado': 'Clima desligado · usando horários típicos',
}
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


def vehicle_profile(vehicle):
    """VehicleProfile do core, ou None se o carro estiver incompleto/inválido."""
    try:
        return vehicle_from_dict(vehicle) if vehicle else None
    except (ValueError, TypeError):
        return None


def vehicle_name(vehicle):
    profile = vehicle_profile(vehicle)
    return profile.name if profile else None


def range_km(vehicle, soc_percent=100):
    """Autonomia estimada (km) com a bateria em ``soc_percent``."""
    profile = vehicle_profile(vehicle)
    return round(profile.range_km * max(0.0, float(soc_percent)) / 100) if profile else None


def vehicle_headline(vehicle):
    """'BYD Dolphin · ~321 km de autonomia' (estimativa do preset ou do carro informado)."""
    profile = vehicle_profile(vehicle)
    return f'{profile.name} · ~{round(profile.range_km)} km de autonomia' if profile else 'Carro não informado'


def battery_line(vehicle, soc_percent, reserve_percent=15):
    """Texto sob o controle de bateria: alcance agora e acima da reserva."""
    total = range_km(vehicle, soc_percent)
    if total is None:
        return 'Escolha o seu carro para estimar a autonomia.'
    spare = range_km(vehicle, max(0.0, float(soc_percent) - float(reserve_percent or 0)))
    return f'≈ {total} km de autonomia agora · {spare} km acima da reserva de {float(reserve_percent):.0f}%'


def default_preferences():
    return default_profile()['preferences']


def in_shift(preferences, now):
    """True quando ``now`` (horário local) está dentro do turno, inclusive turnos que viram a noite."""
    start = parse_hhmm(preferences.get('shift_start') or '10:00')
    end = parse_hhmm(preferences.get('shift_end') or '22:00')
    minute = now.hour * 60 + now.minute
    return start <= minute < end if start < end else minute >= start or minute < end


def auto_mode(preferences, now):
    """Durante o turno planeja do agora até o fim; fora dele, o próximo turno completo."""
    try:
        return 'auto' if in_shift(preferences, now) else 'full_shift'
    except (ValueError, TypeError):
        return 'full_shift'


def mode_line(mode, preferences):
    start, end = preferences.get('shift_start') or '10:00', preferences.get('shift_end') or '22:00'
    return f'Agora no turno: planejando até {end}' if mode == 'auto' else f'Turno completo {start}–{end}'


def shift_summary(preferences):
    """'10:00–22:00 · R$ 38/h · Almoço 12:30, Jantar 20:00' para o resumo recolhido."""
    labels = {kind: label for kind, label, *_ in MEALS}
    meals = [f"{labels.get(meal.get('kind'), meal.get('kind'))} {meal.get('start')}"
             for meal in preferences.get('meals') or () if isinstance(meal, dict) and meal.get('enabled', True)]
    earnings = preferences.get('earnings_per_hour')
    parts = [f"{preferences.get('shift_start', '10:00')}–{preferences.get('shift_end', '22:00')}"]
    if earnings is not None:
        parts.append(f'{brl(earnings)}/h')
    parts.append(', '.join(meals) if meals else 'sem refeições')
    return ' · '.join(parts)


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
    # O ponto de partida é o SoC escondido do carro: só mínimo e fim projetados viram texto.
    return (f"Bateria projetada: mínimo de {low['soc']:.0f}% às {low['time']} "
            f"e termina em {rows[-1]['soc']:.0f}%.")


def stop_line(stop):
    return (f"+{kwh(stop['kwh'])} · {brl(stop['cost'])} · {duration(stop['charge_minutes'])} de carga · "
            f"{km(stop['detour_km'])} de desvio")


def amenity_label(amenity):
    """'Restaurante Cantina da Vila', but 'Café da Sé' (no repeated kind)."""
    kind = AMENITY_TEXT.get(amenity.get('kind'), str(amenity.get('kind') or '').capitalize())
    name = str(amenity.get('name') or '').strip()
    if not name:
        return kind
    return name if name.casefold().startswith(kind.casefold()) else f'{kind} {name}'


def amenities_text(amenities):
    return ' · '.join(amenity_label(amenity) for amenity in amenities or () if isinstance(amenity, dict))


def stop_is_now(plan, stop):
    """A primeira parada começa no primeiro slot de um plano a partir de agora: dá para reservar."""
    slots = plan.get('slots') or []
    return plan.get('mode') == 'auto' and bool(slots) and stop.get('start_at') == slots[0].get('at')


# --- tela enxuta: valores que o app já considera ------------------------------------------------

def time_options(value=None):
    """Horários de 30 em 30 min; um horário salvo fora da grade (ex.: 06:15) continua na lista."""
    options = list(TIME_OPTIONS)
    if value and value not in options:
        options.append(value)
        options.sort()
    return [(option, option) for option in options]


def sources(preferences):
    """Origem de ganho/turno do perfil (perfis antigos sem ``sources``: inferida pelo core)."""
    try:
        return DriverPreferences.from_dict(preferences).to_dict()['sources']
    except (ValueError, TypeError):
        return {'earnings_per_hour': 'estimativa', 'shift': 'auto'}


def effective_preferences(preferences, now):
    """Turno que o motorista nunca informou ("auto") e que não cobre agora: planeja de agora até
    +10 h (só no pedido; o perfil salvo não muda)."""
    if sources(preferences).get('shift') != 'auto' or in_shift(preferences, now):
        return dict(preferences)
    start = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 30)
    end = start + timedelta(hours=AUTO_SHIFT_HOURS)
    return {**preferences, 'shift_start': f'{start:%H:%M}', 'shift_end': f'{end:%H:%M}'}


def merge_meals(saved, edited):
    """Refeições salvas + o que mudou em Ajustes (ligada e horário). Duração, flexibilidade e
    refeições que não aparecem na tela (lanche) ficam como estavam."""
    defaults = {kind: (start, length, flex) for kind, _, start, length, flex in MEALS}
    by_kind = {meal.get('kind'): dict(meal) for meal in saved or () if isinstance(meal, dict)}
    for kind, (enabled, start) in edited.items():
        meal = by_kind.get(kind)
        if meal is None:
            if not enabled:
                continue
            default_start, length, flex = defaults[kind]
            meal = build_meal(kind, True, start or default_start, length, flex)
        label = dict((k, name) for k, name, *_ in MEALS)[kind]
        meal.update(enabled=bool(enabled), start=clock(start or meal.get('start'), f'o horário do {label.lower()}'))
        by_kind[kind] = meal
    order = [kind for kind, *_ in MEALS]
    return sorted(by_kind.values(), key=lambda meal: order.index(meal['kind']) if meal.get('kind') in order else 9)


def earnings_info(preferences):
    """``{per_hour, source, estimated, label}`` do core ("R$ 38/h estimado" ou "R$ 45/h (seu ganho)")."""
    try:
        return resolve_earnings(DriverPreferences.from_dict(preferences))
    except (ValueError, TypeError):
        return {'per_hour': None, 'source': 'estimativa', 'estimated': True, 'label': 'Ganho por hora estimado'}


def _clock_text(value):
    """'16:45' -> '16h45', '20:00' -> '20h'."""
    hours, _, minutes = str(value or '').partition(':')
    return f'{int(hours)}h' + ('' if minutes in ('', '00') else minutes) if hours.isdigit() else str(value or '')


def shift_line(preferences, mode, context=None):
    """'No turno até 22:00 · demanda alta, pico 16h45–20h' (demanda só quando o contexto chegou)."""
    start, end = preferences.get('shift_start') or '10:00', preferences.get('shift_end') or '22:00'
    text = f'No turno até {end}' if mode == 'auto' else f'Próximo turno {start}–{end}'
    demand = (context or {}).get('demand') or {}
    if demand.get('level'):
        text += f" · demanda {demand['level']}"
        peaks = demand.get('peaks') or []
        if peaks:
            text += f", pico {_clock_text(peaks[0]['start'])}–{_clock_text(peaks[0]['end'])}"
    return text


def weather_line(weather):
    """Uma linha de clima: o resumo da API (Open-Meteo ou simulado) ou o motivo de não haver clima."""
    weather = weather or {}
    if weather.get('label'):
        return weather['label']
    return WEATHER_STATUS_TEXT.get(weather.get('status'), 'Clima ainda não consultado · usando horários típicos')


def weather_live(weather):
    return (weather or {}).get('status') in ('ok', 'simulado')
