"""Gerador de histórico sintético **rotulado** (``origin = "synthetic"``, versão ``syn-v1``).

Serve para treinar/avaliar o modelo offline, para a conta demo e para o seed opcional de
um posto de demonstração. Nada aqui é dado real: todo resultado leva o rótulo.

Modelo gerador (determinístico pela semente)
--------------------------------------------
* Arquétipos de posto (shopping, escritório, residencial, rodovia) com taxa de chegada
  por conector e por hora, em dia útil e fim de semana, e duração típica da recarga.
* Chegadas Poisson por hora × escala do posto × tendência semanal × amadurecimento de
  posto novo (40 % → 100 %) × ruído diário × feriado × chuva (dia compartilhado entre
  postos) × evento local × preço.
* Preço: alguns postos passam a ter tarifa por horário a partir de uma semana; a
  procura reage com elasticidade −1,2 à razão de preço (é uma hipótese do gerador).
* Capacidade de N conectores: quem chega com o posto cheio desiste (procura perdida).
* Energia = potência × tempo × eficiência, limitada a 60 kWh (bateria cheia encerra).
* As sessões passam pelo **mesmo agregador da produção** (:mod:`aggregate`).
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from .aggregate import hourly_rows
from .calendar import is_holiday, to_utc
from .series import build_series

VERSION = "syn-v1"
BATTERY_KWH = 60.0
ELASTICITY = -1.2

_SHOP = (0, 0, 0, 0, 0, 0, .02, .05, .12, .25, .40, .55, .70, .62, .48, .45, .50, .60, .78, .72, .50, .28, .10, .02)
_SHOP_WE = (0, 0, 0, 0, 0, 0, 0, .02, .08, .25, .50, .70, .80, .78, .70, .65, .70, .75, .70, .55, .40, .25, .10, .03)
_OFFICE = (0, 0, 0, 0, 0, 0, .05, .30, .55, .40, .22, .12, .25, .22, .12, .08, .08, .12, .08, .04, .02, 0, 0, 0)
_OFFICE_WE = tuple(round(v * 0.15, 3) for v in _OFFICE)
_HOME = (.02, .01, 0, 0, 0, 0, .02, .04, .03, .02, .02, .03, .04, .03, .03, .05, .08, .15, .30, .38, .32, .22, .12, .05)
_HOME_WE = (.03, .02, .01, 0, 0, 0, .01, .02, .04, .06, .08, .10, .10, .08, .08, .10, .12, .18, .25, .28, .25, .18, .10, .05)
_ROAD = (.03, .02, .01, .01, .02, .05, .15, .30, .40, .42, .40, .42, .48, .45, .40, .40, .45, .50, .45, .35, .25, .15, .08, .05)
_ROAD_WE = tuple(round(v * 1.1, 3) for v in _ROAD)

ARCHETYPES = {
    # taxa por conector/h (dia útil, fim de semana), duração média (h), potências, fator feriado, fator chuva
    "shopping": {"weekday": _SHOP, "weekend": _SHOP_WE, "hours": 1.2, "power": (7.4, 11.0, 22.0),
                 "holiday": 1.3, "rain": 1.25},
    "escritorio": {"weekday": _OFFICE, "weekend": _OFFICE_WE, "hours": 2.4, "power": (7.4, 11.0),
                   "holiday": 0.2, "rain": 1.05},
    "residencial": {"weekday": _HOME, "weekend": _HOME_WE, "hours": 3.0, "power": (7.4,),
                    "holiday": 1.1, "rain": 1.0},
    "rodovia": {"weekday": _ROAD, "weekend": _ROAD_WE, "hours": 0.6, "power": (50.0, 60.0),
                "holiday": 1.6, "rain": 0.85},
}
ARCHETYPE_ORDER = ("shopping", "escritorio", "residencial", "rodovia")
SCHEDULES = {
    # (início, fim, razão de preço): fim < início cruza a meia-noite
    "noturno_barato": (22, 6, 0.8),
    "pico_caro": (18, 21, 1.2),
    "tarde_barata": (13, 16, 0.85),
}


def _rain(seed, day: date) -> bool:
    return random.Random(f"{seed}-rain-{day.isoformat()}").random() < 0.12


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    limit, count, product = math.exp(-lam), 0, rng.random()
    while product > limit:
        count += 1
        product *= rng.random()
    return count


def station_profile(seed, index: int) -> dict:
    """Parâmetros fixos do posto sintético ``index`` (independente dos outros postos)."""
    rng = random.Random(f"{seed}-station-{index}")
    archetype = ARCHETYPE_ORDER[index % len(ARCHETYPE_ORDER)]
    spec = ARCHETYPES[archetype]
    schedule = None
    if rng.random() < 0.5:
        schedule = {"name": rng.choice(sorted(SCHEDULES)), "from_day": rng.randint(56, 160)}
    return {
        "index": index, "archetype": archetype, "connectors": rng.choice((1, 2, 2, 3, 4)),
        "scale": rng.uniform(0.55, 1.35), "growth": rng.uniform(-0.01, 0.03),
        "power_kw": rng.choice(spec["power"]), "schedule": schedule, "seed": seed,
        # Posto novo: a procura sobe de 40 % até o nível maduro ao longo de ``ramp_days``.
        "ramp_days": rng.randint(30, 150) if rng.random() < 0.6 else 0,
    }


def price_ratio(profile: dict, start: datetime, hours: int) -> list[float]:
    """Razão tarifa do horário / tarifa base, por hora local, a partir de ``start``."""
    ratios = [1.0] * hours
    schedule = profile.get("schedule")
    if not schedule:
        return ratios
    first, last, ratio = SCHEDULES[schedule["name"]]
    for i in range(hours):
        moment = start + timedelta(hours=i)
        if (moment - start).days < schedule["from_day"]:
            continue
        inside = first <= moment.hour < last if first < last else (moment.hour >= first or moment.hour < last)
        if inside:
            ratios[i] = ratio
    return ratios


def sessions_for(profile: dict, start: datetime, days: int, connector_ids=None) -> list[dict]:
    """Sessões sintéticas (dicionários no formato da API) em ``[start, start + days)`` local."""
    seed, index = profile["seed"], profile["index"]
    spec = ARCHETYPES[profile["archetype"]]
    rng = random.Random(f"{seed}-sessions-{index}")
    connectors = connector_ids or [f"syn-{index}-c{k + 1}" for k in range(profile["connectors"])]
    free_at = [start] * len(connectors)
    ratios = price_ratio(profile, start, days * 24)
    sigma = 0.5
    mu = math.log(spec["hours"]) - sigma * sigma / 2
    sessions = []
    for day_index in range(days):
        day = (start + timedelta(days=day_index)).date()
        week = day_index / 7
        level = profile["scale"] * (1 + profile["growth"]) ** week * rng.lognormvariate(0, 0.2)
        if profile.get("ramp_days"):
            level *= min(1.0, 0.4 + 0.6 * day_index / profile["ramp_days"])
        if is_holiday(day):
            level *= spec["holiday"]
        if _rain(seed, day):
            level *= spec["rain"]
        event = rng.random() < 0.03
        curve = spec["weekend"] if day.weekday() >= 5 else spec["weekday"]
        if profile["archetype"] == "rodovia" and day.weekday() in (4, 6):
            curve = tuple(v * 1.5 if 14 <= h <= 21 else v for h, v in enumerate(curve))
        for hour in range(24):
            lam = curve[hour] * level * len(connectors)
            if event and 17 <= hour <= 22:
                lam *= 1.7
            ratio = ratios[day_index * 24 + hour]
            if ratio != 1.0:
                lam *= ratio ** ELASTICITY
            arrivals = sorted(rng.random() for _ in range(_poisson(rng, lam)))
            for fraction in arrivals:
                began = datetime(day.year, day.month, day.day, hour) + timedelta(seconds=int(fraction * 3600))
                duration = min(8.0, max(8 / 60, rng.lognormvariate(mu, sigma)))
                efficiency = rng.uniform(0.75, 0.95)
                kw = profile["power_kw"] * efficiency
                duration = min(duration, BATTERY_KWH / kw)
                slot = next((k for k, moment in enumerate(free_at) if moment <= began), None)
                if slot is None:
                    continue  # posto cheio: o motorista desiste (procura perdida)
                ended = began + timedelta(hours=duration)
                free_at[slot] = ended
                energy = Decimal(str(round(kw * duration * 1000, 3)))
                sessions.append({
                    "id": f"syn-{index}-{len(sessions) + 1}", "connector_id": connectors[slot],
                    "status": "completed", "started_at": to_utc(began), "ended_at": to_utc(ended),
                    "energy_wh": energy, "source": "synthetic",
                })
    return sessions


def station_rows(profile: dict, start: datetime, days: int, connector_ids=None) -> list[dict]:
    """Agregados horários sintéticos (mesmo formato do rollup de produção)."""
    sessions = sessions_for(profile, start, days, connector_ids)
    first, last = to_utc(start), to_utc(start + timedelta(days=days))
    return hourly_rows(sessions, [], first, last, last, origin="synthetic")


def station_series(profile: dict, start: datetime, days: int):
    """``(StationSeries, razões de preço)`` de um posto sintético."""
    rows = station_rows(profile, start, days)
    series = build_series(rows, profile["connectors"], start, start + timedelta(days=days), history_start=start)
    return series, price_ratio(profile, start, days * 24)
