"""Planejador de turno e recarga para motoristas de app com carro elétrico.

Modelo
------
O turno é discretizado em slots de 15 min. Em cada slot o motorista pode:

* **rodar** — ganha ``ganho/h × demanda(slot)`` e gasta energia;
* **parar para recarregar** num posto por 1–8 slots (inclui deslocamento e fila);
* **fazer uma refeição** (obrigatória dentro da janela de flexibilidade), sozinha
  ou **acoplada a uma recarga** num posto com restaurante/café/shopping —
  o tempo da refeição já seria perdido, então a recarga nele não custa oportunidade.

Programação dinâmica sobre (slot, refeições feitas, SoC em faixas de 1%)
maximiza ``ganhos − custo de energia − penalidades + energia final × valor de
reposição``. O custo de oportunidade aparece naturalmente: parar no pico deixa
de somar o ganho alto daquele horário. SoC abaixo da reserva é penalizado
fortemente (restrição "macia" para sempre devolver um plano com alertas).
Os postos são podados por slot (melhor custo efetivo por kWh) para manter
o tempo de execução abaixo de ~200 ms para ~30 postos.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..formatting import brl, duration, km
from .demand import (
    PEAK_THRESHOLD,
    SLOT_MINUTES,
    DemandSignal,
    HeuristicDemand,
    peak_windows,
)
from .models import (
    AMENITY_LABELS,
    ChargerOption,
    DriverPreferences,
    Meal,
    haversine_km,
    hhmm,
)
from .vehicles import ChargeCurve, VehicleProfile, is_dc

CITY_SPEED_KMH = 24.0
ROAD_FACTOR = 1.3
DETOUR_BASE_KM = 1.0
NEAR_TERM_MINUTES = 45
UNKNOWN_QUEUE_MINUTES = 5.0
MIN_CHARGE_MINUTES = 8.0
BELOW_RESERVE_PENALTY = 60.0   # R$ por kWh abaixo da reserva, por slot
EMPTY_BATTERY_PENALTY = 500.0  # R$ por slot parado por falta de bateria
MISSED_MEAL_PENALTY = 1000.0
MEAL_DEVIATION_COST = 0.08     # R$ por minuto longe do horário preferido
MEAL_TRAVEL_ALLOWANCE = 10.0   # min de trajeto que o motorista faria de qualquer jeito para comer
DC_DURATIONS = (1, 2, 3, 4)
AC_DURATIONS = (2, 4, 8)
MEAL_EXTRA_SLOTS = (0, 2)
TOP_OPTIONS = 3
TOP_MEAL_OPTIONS = 2
BUCKET_PERCENT = 3.0
BEAM_WIDTH = 12
ENOUGH_MARGIN_PERCENT = 3.0
STOP_OVERHEAD_COST = 4.0       # incômodo por parada (manobra, plugar); só desempata, não entra no lucro


@dataclass(frozen=True)
class _Slot:
    index: int
    start: datetime
    demand: float
    earnings: float
    km: float
    kwh: float

    @property
    def minute(self) -> int:
        return self.start.hour * 60 + self.start.minute


@dataclass(frozen=True)
class _StopResult:
    soc_kwh: float
    kwh: float
    cost: float
    price: float
    detour_km: float
    detour_minutes: float
    queue_minutes: float
    charge_minutes: float
    soc_after_detour: float


@dataclass
class _MealSlots:
    meal: Meal
    allowed: dict[int, int]  # slot → desvio em minutos do horário preferido
    slots: int


@dataclass
class Plan:
    """Resultado serializável (``to_dict``) do planejamento."""

    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.data


class _Context:
    def __init__(self, vehicle: VehicleProfile, preferences: DriverPreferences, options: list[ChargerOption],
                 start: datetime, end: datetime, soc_percent: float, demand: DemandSignal,
                 origin: tuple[float, float] | None):
        if end <= start:
            raise ValueError('O fim do planejamento deve ser depois do início')
        self.vehicle, self.preferences, self.options = vehicle, preferences, list(options)
        self.start, self.end, self.demand, self.origin = start, end, demand, origin
        self.battery = vehicle.usable_battery_kwh
        self.soc0 = max(0.0, min(100.0, float(soc_percent))) / 100 * self.battery
        self.reserve = preferences.reserve_percent / 100 * self.battery
        self.cap = preferences.max_charge_percent / 100 * self.battery
        self.value_end = preferences.end_energy_value
        count = max(1, math.ceil((end - start).total_seconds() / 60 / SLOT_MINUTES))
        hourly, per_slot = preferences.hourly_earnings, SLOT_MINUTES / 60
        self.slots = []
        for index in range(count):
            when = start + timedelta(minutes=SLOT_MINUTES * index)
            factor = float(demand.multiplier(when))
            distance = preferences.km_per_hour * per_slot * min(1.25, max(0.6, 0.55 + 0.45 * factor))
            self.slots.append(_Slot(index, when, factor, hourly * per_slot * factor, distance,
                                    distance * vehicle.consumption_kwh_per_100km / 100))
        self.T = len(self.slots)
        if origin is None and self.options:
            origin_guess = (sum(o.latitude for o in self.options) / len(self.options),
                            sum(o.longitude for o in self.options) / len(self.options))
            self.center, self.exact_origin = origin_guess, False
        else:
            self.center, self.exact_origin = origin, origin is not None
        self.distance = [haversine_km(self.center[0], self.center[1], o.latitude, o.longitude)
                         if self.center else 3.0 for o in self.options]
        self.meals = self._meal_slots()
        self.need = [0.0] * (self.T + 1)
        for t in range(self.T - 1, -1, -1):
            self.need[t] = self.need[t + 1] + self.slots[t].kwh
        self.option_dc = [is_dc(o.connector_type) for o in self.options]
        self.option_curve = [ChargeCurve.for_connector(o.connector_type) for o in self.options]
        # kWh de uma carga de referência de 30 min a partir de 40% (para ranquear postos).
        self.option_kwh30 = [(curve.charge(self.battery, o.power_kw, 0.4, 30, 1.0) - 0.4) * self.battery
                             for o, curve in zip(self.options, self.option_curve, strict=True)]
        self._stop_cache: dict = {}
        self._candidates = [self._rank(t) for t in range(self.T)]

    # --- geometria e tempo -------------------------------------------------
    def near_term(self, t: int) -> bool:
        return t * SLOT_MINUTES < NEAR_TERM_MINUTES

    def detour_km(self, index: int, t: int) -> float:
        distance = self.distance[index]
        if self.exact_origin and self.near_term(t):
            return max(0.3, distance * ROAD_FACTOR)
        # Mais tarde o motorista estará em algum ponto da área de atuação: desvio
        # típico = base + fração da distância do posto ao centro dessa área.
        return DETOUR_BASE_KM + min(distance, 20.0) * 0.35

    def queue_minutes(self, option: ChargerOption, t: int) -> float:
        if self.near_term(t):
            return 0.0 if option.available else option.queue_minutes or UNKNOWN_QUEUE_MINUTES
        return UNKNOWN_QUEUE_MINUTES

    def _meal_slots(self) -> list[_MealSlots]:
        result = []
        for meal in self.preferences.meals:
            if not meal.enabled:
                continue
            slots = math.ceil(meal.duration_minutes / SLOT_MINUTES)
            allowed = {}
            day0 = self.start.replace(hour=0, minute=0, second=0, microsecond=0)
            for slot in self.slots:
                if slot.index + slots > self.T:
                    break
                offset = (slot.start - day0).total_seconds() / 60
                best = None
                for day in (-1, 0, 1):
                    preferred = meal.start_minute + day * 1440
                    low, high = meal.window[0] + day * 1440, meal.window[1] + day * 1440
                    if low <= offset <= high:
                        deviation = abs(offset - preferred)
                        best = deviation if best is None else min(best, deviation)
                if best is not None:
                    allowed[slot.index] = int(best)
            if allowed:
                result.append(_MealSlots(meal, allowed, slots))
        return result

    # --- recarga -----------------------------------------------------------
    def _static(self, index, t, slots, meal):
        """Parte da parada que não depende do SoC (cacheada)."""
        key = (index, t, slots, meal.meal.kind if meal else None)
        found = self._stop_cache.get(key, False)
        if found is not False:
            return found
        option, value = self.options[index], None
        if t + slots <= self.T:
            detour = self.detour_km(index, t)
            detour_minutes = detour / CITY_SPEED_KMH * 60
            queue = self.queue_minutes(option, t)
            total = slots * SLOT_MINUTES
            if meal is None:
                lost_travel, needed = detour_minutes, 0.0
            else:
                # Para comer o motorista se deslocaria de qualquer jeito: só o trajeto além
                # da tolerância conta como tempo extra; a fila acontece durante a refeição.
                lost_travel = max(0.0, detour_minutes - MEAL_TRAVEL_ALLOWANCE)
                needed = meal.meal.duration_minutes + lost_travel
            charge_minutes = min(total - lost_travel - queue, option.max_duration_minutes)
            if total >= needed and charge_minutes >= MIN_CHARGE_MINUTES:
                price = option.price_at(self.slots[t].minute + int(detour_minutes + queue))
                value = (detour, detour_minutes, detour * self.vehicle.consumption_kwh_per_100km / 100, queue,
                         charge_minutes, price, self.option_curve[index], option.power_kw)
        self._stop_cache[key] = value
        return value

    def quick_stop(self, index, t, slots, soc, meal=None, target=None):
        """(SoC final, kWh, custo, SoC na chegada) ou None — laço interno da otimização.

        ``target`` (kWh) limita a carga abaixo do alvo máximo: carregar só o necessário
        evita pagar tarifa pública por energia que valeria menos em casa."""
        static = self._static(index, t, slots, meal)
        if static is None:
            return None
        _detour, _minutes, detour_kwh, _queue, charge_minutes, price, curve, power = static
        arrival = soc - detour_kwh
        if arrival <= 0 or (meal is None and arrival >= self.cap - 0.02 * self.battery):
            return None
        battery = self.battery
        limit = self.cap if target is None else min(self.cap, target)
        fraction = curve.charge(battery, power, arrival / battery, charge_minutes, max(limit, arrival) / battery)
        added = fraction * battery - arrival
        if added < 0.3:
            return None
        return arrival + added, added, added * price, arrival

    def stop(self, index: int, t: int, slots: int, soc: float, meal: _MealSlots | None = None,
             target: float | None = None):
        quick = self.quick_stop(index, t, slots, soc, meal, target)
        if quick is None:
            return None
        detour, detour_minutes, _kwh, queue, charge_minutes, price, _curve, _power = self._static(index, t, slots, meal)
        final, added, cost, arrival = quick
        return _StopResult(final, added, cost, price, detour, detour_minutes, queue, charge_minutes, arrival)

    def _rank(self, t: int):
        """Melhores postos para parar no slot ``t`` (custo efetivo por kWh de 30 min de carga)."""
        rate = self.slots[t].earnings / SLOT_MINUTES
        minute = self.slots[t].minute
        per_km = self.vehicle.consumption_kwh_per_100km / 100
        scored = []
        for index, option in enumerate(self.options):
            kwh = self.option_kwh30[index]
            if kwh <= 0:
                continue
            detour = self.detour_km(index, t)
            minutes = detour / CITY_SPEED_KMH * 60 + self.queue_minutes(option, t)
            price = option.price_at(minute) if option.price_schedule else option.price_per_kwh
            scored.append(((price * (kwh + detour * per_km) + rate * minutes) / kwh, index))
        scored.sort()
        general = [index for _, index in scored[:TOP_OPTIONS]]
        meals = {}
        for meal in self.meals:
            if t in meal.allowed:
                meals[meal.meal.kind] = [index for _, index in scored
                                         if self.options[index].meal_amenity(meal.meal.kind)][:TOP_MEAL_OPTIONS]
        return general, meals

    def durations(self, option: ChargerOption):
        return DC_DURATIONS if is_dc(option.connector_type) else AC_DURATIONS

    def durations_at(self, index: int):
        return DC_DURATIONS if self.option_dc[index] else AC_DURATIONS

    def penalty(self, soc: float) -> float:
        return BELOW_RESERVE_PENALTY * (self.reserve - soc) if soc < self.reserve else 0.0


# --- programação dinâmica ------------------------------------------------------

def _optimize(ctx: _Context):
    meal_bits = {m.meal.kind: 1 << i for i, m in enumerate(ctx.meals)}
    full = (1 << len(ctx.meals)) - 1
    battery, reserve, cap = ctx.battery, ctx.reserve, ctx.cap
    width = BUCKET_PERCENT / 100 * battery
    need = ctx.need
    margin = ENOUGH_MARGIN_PERCENT / 100 * battery

    def targets(t_end):
        enough = need[min(t_end, ctx.T)] + reserve + margin
        return (None, enough) if enough < cap - 0.01 * battery else (None,)
    prices = sorted(o.price_per_kwh for o in ctx.options) or [ctx.value_end]
    public_value = max(ctx.value_end, prices[len(prices) // 2])
    layers: list[dict] = [dict() for _ in range(ctx.T + 1)]

    value_end = ctx.value_end

    def relax(t, mask, soc, score, back):
        # Valor heurístico p/ desempate na mesma faixa: energia ainda necessária vale o preço público.
        useful = need[t] + reserve
        value = score + (soc * public_value if soc <= useful
                         else useful * public_value + (soc - useful) * value_end)
        key = (mask, int(soc / width))
        layer = layers[t]
        current = layer.get(key)
        if current is None or value > current[3] + 1e-9:
            layer[key] = (score, soc, back, value)

    def frontier(layer):
        """Remove estados dominados (menos SoC e menos pontos que outro com as mesmas refeições)
        e mantém no máximo ``BEAM_WIDTH`` estados por combinação de refeições (busca com poda)."""
        best, groups = {}, {}
        for key, (score, soc, _back, value) in sorted(layer.items(), key=lambda item: (-item[1][1], -item[1][0])):
            if score > best.get(key[0], -math.inf) + 1e-9:
                best[key[0]] = score
                groups.setdefault(key[0], []).append((value, key, score, soc))
        kept = []
        for group in groups.values():
            if len(group) > BEAM_WIDTH:
                group = sorted(group, key=lambda item: -item[0])[:BEAM_WIDTH]
            kept.extend((key, score, soc) for _value, key, score, soc in group)
        return kept

    relax(0, 0, ctx.soc0, 0.0, None)
    for t in range(ctx.T):
        slot = ctx.slots[t]
        general, meal_options = ctx._candidates[t]
        charge_limit = min(cap - 0.02 * battery, need[t] + reserve + 0.1 * battery)
        for key, score, soc in frontier(layers[t]):
            mask = key[0]
            origin = (t, key)
            after = soc - slot.kwh
            if after >= 0:
                relax(t + 1, mask, after, score + slot.earnings - ctx.penalty(after), (origin, ('drive',)))
            else:
                relax(t + 1, mask, soc, score - EMPTY_BATTERY_PENALTY, (origin, ('pause',)))
            can_charge = soc < charge_limit
            if can_charge:
                for index in general:
                    for slots in ctx.durations_at(index):
                        for target in targets(t + slots):
                            result = ctx.quick_stop(index, t, slots, soc, None, target)
                            if result is not None:
                                relax(t + slots, mask, result[0], score - result[2] - STOP_OVERHEAD_COST - ctx.penalty(result[3]) * 0.5,
                                      (origin, ('charge', index, slots, target)))
            for meal in ctx.meals:
                bit = meal_bits[meal.meal.kind]
                if mask & bit or t not in meal.allowed:
                    continue
                deviation = 0.0 if meal.meal.flexible else meal.allowed[t] * MEAL_DEVIATION_COST
                relax(t + meal.slots, mask | bit, soc, score - deviation, (origin, ('meal', meal.meal.kind)))
                if not can_charge:
                    continue
                for index in meal_options.get(meal.meal.kind, ()):
                    travel = max(0.0, ctx.detour_km(index, t) / CITY_SPEED_KMH * 60 - MEAL_TRAVEL_ALLOWANCE)
                    base = max(meal.slots, math.ceil((travel + meal.meal.duration_minutes) / SLOT_MINUTES))
                    for extra in MEAL_EXTRA_SLOTS:
                        for target in (targets(t + base) if not extra else (None,)):
                            result = ctx.quick_stop(index, t, base + extra, soc, meal, target)
                            if result is not None:
                                relax(t + base + extra, mask | bit, result[0],
                                      score - result[2] - STOP_OVERHEAD_COST - deviation - ctx.penalty(result[3]) * 0.5,
                                      (origin, ('meal_charge', meal.meal.kind, index, base + extra, target)))
    best = None
    for key, (score, soc, _back, _value) in layers[ctx.T].items():
        missing = bin(full & ~key[0]).count('1')
        total = score + soc * ctx.value_end - missing * MISSED_MEAL_PENALTY
        if best is None or total > best[0]:
            best = (total, key)
    actions, cursor = [], (ctx.T, best[1])
    while True:
        t, key = cursor
        back = layers[t][key][2]
        if back is None:
            break
        previous, action = back
        actions.append((previous[0], action))
        cursor = previous
    actions.reverse()
    return actions


def _naive_actions(ctx: _Context):
    """Estratégia ingênua: roda até a bateria ficar baixa e carrega no posto mais próximo até o alvo."""
    trigger = max(ctx.preferences.reserve_percent + 5, 20) / 100 * ctx.battery
    actions, t, soc, done = [], 0, ctx.soc0, set()
    preferred = {m.meal.kind: min(m.allowed, key=lambda s: (m.allowed[s], s)) for m in ctx.meals}
    while t < ctx.T:
        meal = next((m for m in ctx.meals if m.meal.kind not in done and t in m.allowed
                     and t >= preferred[m.meal.kind]), None)
        if meal is not None:
            done.add(meal.meal.kind)
            actions.append((t, ('meal', meal.meal.kind)))
            t += meal.slots
            continue
        if soc < trigger and ctx.options:
            nearest = min(range(len(ctx.options)), key=lambda i: (ctx.detour_km(i, t), i))
            chosen = None
            for slots in ctx.durations(ctx.options[nearest]):
                result = ctx.stop(nearest, t, slots, soc)
                if result is not None:
                    chosen = (slots, result)
                    if result.soc_kwh >= ctx.cap - 0.01 * ctx.battery:
                        break
            if chosen is not None:
                actions.append((t, ('charge', nearest, chosen[0], None)))
                soc = chosen[1].soc_kwh
                t += chosen[0]
                continue
        slot = ctx.slots[t]
        if soc - slot.kwh >= 0:
            actions.append((t, ('drive',)))
            soc -= slot.kwh
        else:
            actions.append((t, ('pause',)))
        t += 1
    return actions


# --- simulação e saída ------------------------------------------------------------

def _meal_by_kind(ctx, kind):
    return next(m for m in ctx.meals if m.meal.kind == kind)


def _simulate(ctx: _Context, actions):
    """Reexecuta as ações exatamente e produz slots, paradas e totais."""
    soc = ctx.soc0
    timeline, stops = [], []
    gross = cost = energy = distance = 0.0
    for t, action in actions:
        kind = action[0]
        slot = ctx.slots[t]
        if kind == 'drive':
            timeline.append((t, 'rodando', soc, soc - slot.kwh, None))
            gross += slot.earnings
            distance += slot.km
            soc -= slot.kwh
        elif kind == 'pause':
            timeline.append((t, 'pausa', soc, soc, None))
        elif kind == 'meal':
            meal = _meal_by_kind(ctx, action[1])
            for offset in range(meal.slots):
                timeline.append((t + offset, 'refeicao', soc, soc, meal.meal.label))
        else:
            meal = _meal_by_kind(ctx, action[1]) if kind == 'meal_charge' else None
            index, slots, target = action[-3:]
            result = ctx.stop(index, t, slots, soc, meal, target)
            option = ctx.options[index]
            stop_id = len(stops)
            for offset in range(slots):
                before = soc + (result.soc_kwh - soc) * offset / slots
                after = soc + (result.soc_kwh - soc) * (offset + 1) / slots
                timeline.append((t + offset, 'refeicao_recarga' if meal else 'recarga', before, after, stop_id))
            stops.append({'t': t, 'slots': slots, 'option': option, 'index': index, 'result': result,
                          'meal': meal, 'soc_before': soc})
            cost += result.cost
            energy += result.kwh
            distance += result.detour_km
            soc = result.soc_kwh
    return {'timeline': timeline, 'stops': stops, 'gross': gross, 'cost': cost, 'energy': energy,
            'distance': distance, 'end_soc': soc,
            'min_soc': min([ctx.soc0] + [row[3] for row in timeline])}


def _net(ctx, sim):
    return sim['gross'] - sim['cost'] - (ctx.soc0 - sim['end_soc']) * ctx.value_end


def _pct(ctx, kwh):
    return round(kwh / ctx.battery * 100, 1)


def _when(ctx, t):
    return ctx.slots[t].start if t < ctx.T else ctx.end


def _totals(ctx, sim):
    stop_minutes = sum(stop['slots'] * SLOT_MINUTES for stop in sim['stops'])
    peak_minutes = sum(SLOT_MINUTES for t, activity, *_ in sim['timeline']
                       if activity in ('recarga', 'refeicao_recarga') and ctx.slots[t].demand >= PEAK_THRESHOLD)
    return {
        'energy_kwh': round(sim['energy'], 2),
        'charging_cost': round(sim['cost'], 2),
        'gross_earnings': round(sim['gross'], 2),
        'battery_value_delta': round((ctx.soc0 - sim['end_soc']) * ctx.value_end, 2),
        'net_profit': round(_net(ctx, sim), 2),
        'driving_km': round(sim['distance'], 1),
        'stops': len(sim['stops']),
        'stop_minutes': stop_minutes,
        'peak_stop_minutes': peak_minutes,
        'start_soc_percent': _pct(ctx, ctx.soc0),
        'end_soc_percent': _pct(ctx, sim['end_soc']),
        'min_soc_percent': _pct(ctx, sim['min_soc']),
    }


def _peaks(ctx):
    windows = peak_windows([(slot.start, slot.demand) for slot in ctx.slots])
    return [{'start': hhmm(s.hour * 60 + s.minute), 'end': hhmm(e.hour * 60 + e.minute),
             'start_at': s.isoformat(), 'end_at': e.isoformat(), 'max_demand': round(v, 2),
             'label': f'Pico estimado {hhmm(s.hour * 60 + s.minute)}–{hhmm(e.hour * 60 + e.minute)}'}
            for s, e, v in windows]


def _hour_label(when: datetime) -> str:
    return f'{when.hour}h' if not when.minute else f'{when.hour}h{when.minute:02d}'


def _dec(value: float, digits: int = 1) -> str:
    return f'{value:.{digits}f}'.replace('.', ',')


_MASCULINE = ('posto', 'hub', 'estacionamento', 'shopping', 'aeroporto', 'eletroposto', 'carregador', 'ponto',
              'restaurante', 'mercado', 'supermercado', 'centro')


def _at_station(name: str) -> str:
    first = (name.split() or [''])[0].casefold()
    return f'no {name}' if first in _MASCULINE else f'em {name}'


def _reason(ctx, stop, peaks, needed_at):
    option, result, meal = stop['option'], stop['result'], stop['meal']
    start = _when(ctx, stop['t'])
    slot = ctx.slots[stop['t']]
    where = _at_station(option.station_name)
    if meal is not None:
        amenity = option.meal_amenity(meal.meal.kind)
        place = AMENITY_LABELS.get(amenity.kind, amenity.kind) if amenity else 'comodidades'
        if amenity and amenity.distance_m == 0:
            place += ' no local'
        elif amenity and amenity.distance_m is not None:
            place += f' a {amenity.distance_m} m'
        text = (f'{meal.meal.label} às {_hour_label(start)} {where} ({place}) — '
                f'carrega {_dec(result.kwh)} kWh enquanto você come')
    else:
        text = (f'Recarga às {_hour_label(start)} {where} — '
                f'+{_dec(result.kwh)} kWh em {duration(result.charge_minutes)}')
    details = []
    if slot.demand < PEAK_THRESHOLD and peaks:
        nearest = min(peaks, key=lambda p: abs((datetime.fromisoformat(p['start_at']) - start).total_seconds()))
        details.append(f"evita parar no pico de demanda das {_hour_label(datetime.fromisoformat(nearest['start_at']))}"
                       f" às {_hour_label(datetime.fromisoformat(nearest['end_at']))}")
    elif slot.demand >= PEAK_THRESHOLD:
        details.append('parada em horário de pico, inevitável pela autonomia')
    if slot.demand < 0.9 and meal is None:
        details.append('horário de demanda baixa')
    if is_dc(option.connector_type) and option.power_kw >= 40:
        details.append(f'carga rápida de {option.power_kw:.0f} kW')
    if needed_at is not None and stop['t'] <= needed_at:
        limit = _when(ctx, needed_at)
        details.append(f'sem parar, a bateria ficaria abaixo da reserva às {_hour_label(limit)}')
    if details:
        text += ' — ' + '; '.join(details)
    return text + '.'


def _stop_dict(ctx, stop, peaks, needed_at):
    option, result, meal = stop['option'], stop['result'], stop['meal']
    start, end = _when(ctx, stop['t']), _when(ctx, stop['t'] + stop['slots'])
    lost = sum(ctx.slots[t].earnings for t in range(stop['t'], min(ctx.T, stop['t'] + stop['slots'])))
    if meal is not None:
        lost = max(0.0, lost - sum(ctx.slots[t].earnings for t in range(stop['t'], stop['t'] + meal.slots)))
    amenity = option.meal_amenity(meal.meal.kind) if meal else None
    return {
        'station_id': option.station_id, 'connector_id': option.connector_id, 'public_code': option.public_code,
        'station_name': option.station_name, 'address': option.address,
        'latitude': option.latitude, 'longitude': option.longitude,
        'connector_type': option.connector_type, 'power_kw': round(option.power_kw, 1),
        'price_per_kwh': round(result.price, 2), 'available_now': option.available,
        'start': hhmm(start.hour * 60 + start.minute), 'end': hhmm(end.hour * 60 + end.minute),
        'start_at': start.isoformat(), 'end_at': end.isoformat(),
        'minutes': stop['slots'] * SLOT_MINUTES, 'charge_minutes': round(result.charge_minutes),
        'detour_km': round(result.detour_km, 1), 'detour_minutes': round(result.detour_minutes),
        'queue_minutes': round(result.queue_minutes),
        'kwh': round(result.kwh, 2), 'cost': round(result.cost, 2),
        'soc_before': _pct(ctx, stop['soc_before']), 'soc_after': _pct(ctx, result.soc_kwh),
        'opportunity_cost': round(lost, 2), 'demand': round(ctx.slots[stop['t']].demand, 2),
        'in_peak': ctx.slots[stop['t']].demand >= PEAK_THRESHOLD,
        'meal': meal.meal.label if meal else None,
        'amenity': {'kind': amenity.kind, 'name': amenity.name, 'distance_m': amenity.distance_m} if amenity else None,
        'amenities': [{'kind': a.kind, 'name': a.name, 'distance_m': a.distance_m} for a in option.amenities],
        'reason': _reason(ctx, stop, peaks, needed_at),
    }


def _blocks(ctx, sim):
    blocks = []
    for t, activity, before, after, tag in sim['timeline']:
        last = blocks[-1] if blocks else None
        if last and last['kind'] == activity and last['_tag'] == tag and last['_end'] == t:
            last['_end'] = t + 1
            last['soc_end'] = _pct(ctx, after)
            continue
        blocks.append({'kind': activity, '_tag': tag, '_start': t, '_end': t + 1,
                       'soc_start': _pct(ctx, before), 'soc_end': _pct(ctx, after)})
    labels = {'rodando': 'Rodando', 'recarga': 'Recarga', 'refeicao': 'Refeição',
              'refeicao_recarga': 'Refeição + recarga', 'pausa': 'Pausa'}
    result = []
    for block in blocks:
        start, end = _when(ctx, block['_start']), _when(ctx, block['_end'])
        label = labels[block['kind']]
        if block['kind'] == 'refeicao' and isinstance(block['_tag'], str):
            label = block['_tag']
        elif block['kind'] in ('recarga', 'refeicao_recarga'):
            stop = sim['stops'][block['_tag']]
            label = (f"{stop['meal'].meal.label} + recarga" if stop['meal'] else 'Recarga') + ' · ' + stop['option'].station_name
        demand = [ctx.slots[t].demand for t in range(block['_start'], block['_end'])]
        result.append({'kind': block['kind'], 'label': label,
                       'start': hhmm(start.hour * 60 + start.minute), 'end': hhmm(end.hour * 60 + end.minute),
                       'start_at': start.isoformat(), 'end_at': end.isoformat(),
                       'minutes': (block['_end'] - block['_start']) * SLOT_MINUTES,
                       'soc_start': block['soc_start'], 'soc_end': block['soc_end'],
                       'stop_index': block['_tag'] if isinstance(block['_tag'], int) else None,
                       'avg_demand': round(sum(demand) / len(demand), 2)})
    return result


def _slots_out(ctx, sim):
    activity = {t: (name, before) for t, name, before, _after, _tag in sim['timeline']}
    rows = []
    for slot in ctx.slots:
        name, before = activity.get(slot.index, ('rodando', None))
        rows.append({'time': hhmm(slot.minute), 'at': slot.start.isoformat(), 'activity': name,
                     'soc': _pct(ctx, before) if before is not None else None,
                     'demand': round(slot.demand, 2), 'expected_earnings': round(slot.earnings, 2)})
    rows.append({'time': hhmm(ctx.end.hour * 60 + ctx.end.minute), 'at': ctx.end.isoformat(), 'activity': 'fim',
                 'soc': _pct(ctx, sim['end_soc']), 'demand': None, 'expected_earnings': 0.0})
    return rows


def _no_stop_check(ctx):
    """Primeiro slot em que, sem nenhuma recarga, o SoC fica abaixo da reserva (ou None)."""
    soc, t = ctx.soc0, 0
    meals = {}
    for meal in ctx.meals:
        start = min(meal.allowed, key=lambda s: (meal.allowed[s], s))
        meals[start] = meal
    while t < ctx.T:
        if t in meals:
            t += meals[t].slots
            continue
        soc -= ctx.slots[t].kwh
        if soc < ctx.reserve:
            return t, soc
        t += 1
    return None, soc


def plan_shift(vehicle: VehicleProfile, preferences: DriverPreferences, options: list[ChargerOption],
               start: datetime, end: datetime, soc_percent: float, demand: DemandSignal | None = None,
               origin: tuple[float, float] | None = None, notes: list[dict] | None = None) -> Plan:
    """Planeja o turno inteiro entre ``start`` e ``end`` (horário local, sem fuso)."""
    demand = demand or HeuristicDemand()
    ctx = _Context(vehicle, preferences, options, start, end, soc_percent, demand, origin)
    plan_actions = _optimize(ctx)
    naive_actions = _naive_actions(ctx)
    plan_sim, naive_sim = _simulate(ctx, plan_actions), _simulate(ctx, naive_actions)
    if _net(ctx, naive_sim) > _net(ctx, plan_sim) + 0.01 and naive_sim['min_soc'] >= min(ctx.reserve, plan_sim['min_soc']):
        plan_sim = naive_sim  # salvaguarda: o plano nunca é pior que a estratégia ingênua
    peaks = _peaks(ctx)
    needed_at, _ = _no_stop_check(ctx)
    stops = [_stop_dict(ctx, stop, peaks, needed_at) for stop in plan_sim['stops']]
    naive_stops = [_stop_dict(ctx, stop, peaks, None) for stop in naive_sim['stops']]
    totals, naive_totals = _totals(ctx, plan_sim), _totals(ctx, naive_sim)
    alerts = _alerts(ctx, plan_sim, stops, peaks, needed_at, notes or [])
    gain = round(totals['net_profit'] - naive_totals['net_profit'], 2)
    saved = round(naive_totals['charging_cost'] - totals['charging_cost'], 2)
    peak_avoided = naive_totals['peak_stop_minutes'] - totals['peak_stop_minutes']
    if gain >= 1:
        message = f'O plano rende cerca de {brl(gain)} a mais que recarregar só quando a bateria fica baixa.'
    elif naive_totals['stops'] == totals['stops'] == 0:
        message = 'Nenhuma recarga necessária: as duas estratégias rodam o turno inteiro sem parar.'
    else:
        message = 'Neste turno o plano empata com a estratégia de recarregar só quando a bateria fica baixa.'
    if peak_avoided > 0:
        message += f' Evita {duration(peak_avoided)} parado em horário de pico.'
    data = {
        'estimate': True,
        'window': {'start': hhmm(ctx.slots[0].minute), 'end': hhmm(end.hour * 60 + end.minute),
                   'start_at': start.isoformat(), 'end_at': end.isoformat(), 'date': start.date().isoformat(),
                   'weekday': start.weekday(), 'minutes': ctx.T * SLOT_MINUTES},
        'vehicle': vehicle.to_dict(),
        'preferences': preferences.to_dict(),
        'demand': {'source': getattr(demand, 'source', 'heuristica'), 'label': 'estimativa',
                   'description': 'Curva típica de grandes cidades brasileiras; não é dado oficial de aplicativos.'},
        'stations_considered': len(ctx.options),
        'slots': _slots_out(ctx, plan_sim),
        'blocks': _blocks(ctx, plan_sim),
        'stops': stops,
        'peaks': peaks,
        'alerts': alerts,
        'totals': totals,
        'baseline': {'strategy': 'Recarregar só quando a bateria fica baixa, no posto mais próximo',
                     'totals': naive_totals, 'stops': naive_stops},
        'comparison': {'net_profit_gain': gain, 'charging_cost_saving': saved,
                       'peak_stop_minutes_avoided': peak_avoided, 'message': message},
        'assumptions': [
            f'Consumo de {_dec(vehicle.consumption_kwh_per_100km)} kWh/100 km e bateria útil de '
            f'{_dec(vehicle.usable_battery_kwh)} kWh (estimativa).',
            f'Ganho médio de {brl(preferences.hourly_earnings)}/h ajustado pela demanda estimada do horário.',
            f'Energia restante ao fim do turno vale {brl(preferences.end_energy_value)}/kWh (custo de repor).',
            'Desvio até o posto estimado em linha reta × 1,3 a 24 km/h; disponibilidade futura é estimada.',
        ],
    }
    return Plan(data)


def _alerts(ctx, sim, stops, peaks, needed_at, notes):
    alerts = list(notes)
    if needed_at is not None:
        when = _when(ctx, needed_at)
        alerts.append({'level': 'warning', 'code': 'needs_charge',
                       'message': f'SoC insuficiente para terminar o turno sem parar: a bateria ficaria abaixo '
                                  f'da reserva ({ctx.preferences.reserve_percent:.0f}%) por volta das '
                                  f'{hhmm(when.hour * 60 + when.minute)}.'})
        if not ctx.options:
            alerts.append({'level': 'error', 'code': 'no_station',
                           'message': 'Nenhum posto compatível com o seu carro foi encontrado na região.'})
    elif not stops:
        alerts.append({'level': 'info', 'code': 'no_charge_needed',
                       'message': 'A bateria atual cobre o turno inteiro acima da reserva — nenhuma parada necessária.'})
    if sim['min_soc'] < ctx.reserve - 0.05:
        alerts.append({'level': 'error', 'code': 'reserve_violated',
                       'message': f'Mesmo com o plano a bateria chega a {_pct(ctx, sim["min_soc"]):.0f}%, abaixo da '
                                  f'reserva. Considere encurtar o turno ou carregar antes de sair.'})
    if any(activity == 'pausa' for _, activity, *_ in sim['timeline']):
        alerts.append({'level': 'error', 'code': 'battery_empty',
                       'message': 'O plano inclui período parado por falta de bateria.'})
    for peak in peaks:
        alerts.append({'level': 'info', 'code': 'peak',
                       'message': f'{peak["label"]}: evite recarregar nesse horário (estimativa).'})
    for stop in stops:
        if stop['queue_minutes'] >= 10:
            alerts.append({'level': 'warning', 'code': 'queue',
                           'message': f'{stop["station_name"]} está ocupado agora; consideramos cerca de '
                                      f'{stop["queue_minutes"]} min de espera.'})
    coupled = {stop['meal'] for stop in stops if stop['meal']}
    for meal in ctx.meals:
        if meal.meal.label not in coupled and stops and not any(
                o.meal_amenity(meal.meal.kind) for o in ctx.options):
            alerts.append({'level': 'info', 'code': 'meal_not_coupled',
                           'message': f'Nenhum posto próximo tem comodidade para o {meal.meal.label.lower()}; '
                                      'cadastre restaurantes/cafés nos postos para acoplar refeição e recarga.'})
    return alerts


def next_stop(vehicle: VehicleProfile, preferences: DriverPreferences, options: list[ChargerOption],
              now: datetime, end: datetime, soc_percent: float, demand: DemandSignal | None = None,
              origin: tuple[float, float] | None = None) -> dict:
    """Modo rápido: qual posto e quando parar, a partir do SoC e do local atuais."""
    demand = demand or HeuristicDemand()
    start = now.replace(second=0, microsecond=0)
    start -= timedelta(minutes=start.minute % SLOT_MINUTES)
    if end <= start + timedelta(minutes=SLOT_MINUTES):
        end = start + timedelta(hours=4)
    plan = plan_shift(vehicle, preferences, options, start, end, soc_percent, demand, origin).to_dict()
    ctx = _Context(vehicle, preferences, options, start, end, soc_percent, demand, origin)
    first = ctx.slots[0]
    alternatives = []
    for index, option in enumerate(ctx.options):
        best = None
        for slots in ctx.durations(option):
            result = ctx.stop(index, 0, slots, ctx.soc0)
            if result is None:
                continue
            lost = sum(ctx.slots[t].earnings for t in range(min(ctx.T, slots)))
            total = result.cost + lost
            score = total / result.kwh
            if best is None or score < best[0]:
                best = (score, slots, result, lost)
        if best is None:
            continue
        score, slots, result, lost = best
        distance = ctx.distance[index]
        alternatives.append({
            'station_id': option.station_id, 'connector_id': option.connector_id, 'station_name': option.station_name,
            'address': option.address, 'distance_km': round(distance, 1) if ctx.exact_origin else None,
            'available_now': option.available, 'queue_minutes': round(result.queue_minutes),
            'connector_type': option.connector_type, 'power_kw': round(option.power_kw, 1),
            'price_per_kwh': round(result.price, 2), 'minutes': slots * SLOT_MINUTES,
            'kwh': round(result.kwh, 2), 'cost': round(result.cost, 2), 'opportunity_cost': round(lost, 2),
            'cost_per_kwh_effective': round(score, 2), 'soc_after': _pct(ctx, result.soc_kwh),
            'amenities': [{'kind': a.kind, 'name': a.name, 'distance_m': a.distance_m} for a in option.amenities],
        })
    alternatives.sort(key=lambda a: (a['cost_per_kwh_effective'], a['station_id']))
    stops = plan['stops']
    usable = max(0.0, ctx.soc0 - ctx.reserve)
    hourly_kwh = sum(s.kwh for s in ctx.slots[:4]) or 1e-9
    range_km = usable / vehicle.consumption_kwh_per_100km * 100
    status = {'soc_percent': round(soc_percent, 1), 'range_above_reserve_km': round(range_km),
              'hours_until_reserve': round(usable / hourly_kwh, 1), 'demand_now': round(first.demand, 2),
              'in_peak': first.demand >= PEAK_THRESHOLD}
    needs_charge = any(alert.get('code') in ('needs_charge', 'battery_empty') for alert in plan['alerts'])
    if stops and stops[0]['start_at'] == start.isoformat():
        recommendation = {'action': 'stop_now', **stops[0],
                          'headline': f"Pare agora {_at_station(stops[0]['station_name'])}",
                          'message': stops[0]['reason']}
    elif stops:
        recommendation = {'action': 'stop_later', **stops[0],
                          'headline': f"Siga rodando — próxima parada às {stops[0]['start']}",
                          'message': stops[0]['reason']}
    elif needs_charge:
        # Sem parada viável (bateria quase vazia, nenhum posto alcançável/compatível): nunca dizer
        # "nenhuma recarga necessária" quando a bateria não cobre o período.
        recommendation = _charge_needed(ctx)
    else:
        recommendation = {'action': 'keep_driving', 'headline': 'Siga rodando: nenhuma recarga necessária',
                          'message': f'A bateria cobre o período planejado (até {plan["window"]["end"]}) '
                                     f'com cerca de {km(range_km)} acima da reserva.'}
    if status['in_peak'] and recommendation['action'] in ('stop_later', 'keep_driving'):
        recommendation['message'] += ' Agora é horário de pico estimado: melhor continuar rodando.'
    return {'estimate': True, 'now': start.isoformat(), 'status': status, 'recommendation': recommendation,
            'alternatives': alternatives[:3], 'plan_window': plan['window'], 'alerts': plan['alerts'],
            'demand': plan['demand']}


def _charge_needed(ctx: _Context) -> dict:
    """Recomendação quando a bateria não cobre o período e o plano não achou parada viável."""
    if not ctx.options:
        return {'action': 'charge_needed', 'headline': 'Recarregue antes de continuar',
                'message': 'A bateria não cobre o período acima da reserva e nenhum posto compatível com o seu '
                           'carro foi encontrado na região. Amplie o raio de busca antes de aceitar novas corridas.'}
    index = min(range(len(ctx.options)), key=lambda i: (ctx.distance[i], i))
    option = ctx.options[index]
    reachable = ctx.soc0 - ctx.detour_km(index, 0) * ctx.vehicle.consumption_kwh_per_100km / 100 > 0
    message = ('A bateria não cobre o período acima da reserva. Siga para o posto compatível mais próximo antes '
               'de aceitar novas corridas.' if reachable else
               'A bateria está praticamente vazia e pode não chegar a um posto. Siga direto ao posto compatível '
               'mais próximo, sem aceitar corridas, e acione assistência se necessário.')
    return {'action': 'charge_needed', 'station_id': option.station_id, 'connector_id': option.connector_id,
            'public_code': option.public_code, 'station_name': option.station_name, 'address': option.address,
            'latitude': option.latitude, 'longitude': option.longitude, 'available_now': option.available,
            'headline': f'Recarregue o quanto antes {_at_station(option.station_name)}', 'message': message}
