"""Tarifa do posto: base por horário × demanda (estilo "preço dinâmico" de app de corrida).

O dono do posto só define dados base; o cálculo é do ChargeGrid e é o mesmo na API,
na conta demo e no app. Tudo determinístico, stdlib e ``Decimal``.

Dados base do dono (``rules``)
------------------------------
* ``demand``: ``enabled``, ``max_increase_percent`` (teto do acréscimo, 0–100 %) e
  ``sensitivity`` (``low`` | ``medium`` | ``high``: quão cedo o preço reage).
* ``schedule``: tarifação por horário. ``intervals`` = ``[{start, end, days, prices}]``:
  ``start``/``end`` ``HH:MM``, ``days`` (0 = segunda) é o dia em que o horário **começa**
  (``Seg 22:00–06:00`` vai de segunda à noite até terça de manhã) e ``prices`` é a tarifa
  base de cada conector nesse horário (``{connector_id: "1.2000"}``). Fora dos horários,
  ou para um conector sem preço no horário, vale a tarifa base do conector. Horários não
  podem se sobrepor.
* ``rotation``: taxa de ocupação após a recarga (tolerância, intervalo e valor). Fica
  registrada com as regras; não entra no preço por kWh.
* ``peak`` (legado): o antigo "horário de pico". Continua aceito e devolvido para apps
  antigos, mas não entra mais no cálculo (``peak_now`` é sempre ``False``).

Sinais (``signals``), medidos pelo servidor em cada posto
---------------------------------------------------------
* ``connectors``: conectores publicados e online; ``in_use``: recargas ativas;
  ``reserved``: reservas ativas (procura já comprometida);
* ``busy_15m``: fração média de conectores ocupados nos últimos 15 min (0–1),
  ponderada pelo tempo — suaviza o preço para ele não oscilar a cada recarga;
* ``starts_60m``: recargas iniciadas na última hora; ``baseline_60m``: média de
  inícios no mesmo dia da semana e horário nas 4 semanas anteriores;
* ``local_now``: horário local do posto (tarifação por horário).

Cálculo
-------
1. Ocupação ``u = 0,6·(em uso + reservados)/conectores + 0,4·busy_15m``. Abaixo de 50 %
   não há pressão; de 50 % a 100 % a pressão de ocupação vai de 0 a 1.
2. Tendência ``(inícios na última hora + 1) / (média histórica + 1)`` (suavização de
   Laplace: poucas recargas não disparam o preço). 1× = normal; 3× ou mais = pressão 1.
3. Fila: posto lotado com reserva aguardando soma 0,15.
4. Pressão ``p = 0,65·ocupação + 0,35·tendência + fila`` (0–1).
5. ``p`` é curvada pela sensibilidade (``p^1,6`` baixa, ``p`` média, ``p^0,6`` alta).
6. Multiplicador ``1 + teto·p``, arredondado para baixo em passos de 0,05×; abaixo de
   1,05× fica 1,00× (sem acréscimo por ruído).
7. Preço = base do horário (ou base do conector) × multiplicador. O motivo exibido
   (``reason_label``) é "Alta demanda", "Horário 22:00–06:00", os dois ou "Preço normal".

O preço é travado quando o motorista reserva (vale até a recarga) ou, sem reserva,
quando a recarga começa: mudanças posteriores não alteram uma recarga em curso.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation

DEFAULT_RULES = {
    "demand": {"enabled": True, "max_increase_percent": 50, "sensitivity": "medium"},
    "schedule": {"enabled": True, "intervals": []},
    "peak": {"enabled": True, "start": "18:00", "end": "21:00", "days": [0, 1, 2, 3, 4, 5, 6]},  # legado
    "rotation": {"enabled": True, "start_after_min": 30, "interval_min": 10, "amount": "0.20"},
}
SENSITIVITY = {"low": Decimal("1.6"), "medium": Decimal("1"), "high": Decimal("0.6")}
SENSITIVITY_LABELS = {"low": "Baixa", "medium": "Média", "high": "Alta"}
LEVELS = (  # (pressão mínima, chave, rótulo)
    (Decimal("0.70"), "very_high", "Muito alta"),
    (Decimal("0.45"), "high", "Alta"),
    (Decimal("0.20"), "normal", "Normal"),
    (Decimal("0"), "low", "Baixa"),
)
STEP = Decimal("0.05")
WINDOW_MINUTES = 15
DAY_LABELS = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
MAX_INTERVALS = 12
MAX_PRICE = Decimal(100)
DAY = 24 * 60
WEEK = 7 * DAY


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _clamp(value: Decimal, low=Decimal(0), high=Decimal(1)) -> Decimal:
    return max(low, min(high, value))


def _time(value) -> str:
    text = str(value or "").strip()
    try:
        hour, minute = (int(part) for part in text.split(":"))
    except ValueError:
        raise ValueError("Informe horários no formato 18:00.") from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Informe horários entre 00:00 e 23:59.")
    return f"{hour:02d}:{minute:02d}"


def clean_rules(raw) -> dict:
    """Regras completas e validadas (campos ausentes vêm do padrão); ``ValueError`` em pt-BR."""
    rules = deepcopy(DEFAULT_RULES)
    raw = raw if isinstance(raw, dict) else {}
    for key in rules:
        if isinstance(raw.get(key), dict):
            rules[key].update({field: raw[key][field] for field in rules[key] if field in raw[key]})
    demand, peak, rotation = rules["demand"], rules["peak"], rules["rotation"]
    for rule in (demand, peak, rotation, rules["schedule"]):
        if not isinstance(rule["enabled"], bool):
            raise ValueError("Status da regra inválido.")
    try:
        increase = int(demand["max_increase_percent"])
    except (TypeError, ValueError):
        raise ValueError("Informe o acréscimo máximo em porcentagem inteira.") from None
    if not 0 <= increase <= 100:
        raise ValueError("O acréscimo máximo vai de 0% a 100%.")
    demand["max_increase_percent"] = increase
    if demand["sensitivity"] not in SENSITIVITY:
        raise ValueError("Escolha a sensibilidade: baixa, média ou alta.")
    peak["start"], peak["end"] = _time(peak["start"]), _time(peak["end"])
    if peak["start"] == peak["end"]:
        raise ValueError("O início e o fim do horário de pico devem ser diferentes.")
    days = peak["days"]
    if not isinstance(days, list) or not all(isinstance(d, int) and 0 <= d <= 6 for d in days):
        raise ValueError("Dias do horário de pico inválidos.")
    if peak["enabled"] and not days:
        raise ValueError("Escolha ao menos um dia para o horário de pico.")
    peak["days"] = sorted(set(days))
    try:
        rotation["start_after_min"] = int(rotation["start_after_min"])
        rotation["interval_min"] = int(rotation["interval_min"])
        amount = _dec(rotation["amount"])
    except (TypeError, ValueError, InvalidOperation):
        raise ValueError("Preencha a taxa de rotatividade com números.") from None
    if not (1 <= rotation["start_after_min"] <= 1440 and 1 <= rotation["interval_min"] <= 1440):
        raise ValueError("Os tempos da rotatividade vão de 1 a 1440 minutos.")
    if not amount.is_finite() or not Decimal(0) <= amount <= Decimal(100):
        raise ValueError("O valor da rotatividade vai de R$ 0,00 a R$ 100,00.")
    rotation["amount"] = str(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    rules["schedule"] = _clean_schedule(rules["schedule"])
    return rules


def _minutes(text: str) -> int:
    hour, minute = text.split(":")
    return int(hour) * 60 + int(minute)


def window_label(interval) -> str:
    return f"{interval['start']}–{interval['end']}"


def _segments(interval):
    """Trechos ``[início, fim)`` em minutos da semana (0 = segunda 00:00) de um horário."""
    start = _minutes(interval["start"])
    length = (_minutes(interval["end"]) - start) % DAY
    result = []
    for day in interval["days"]:
        begin = day * DAY + start
        finish = begin + length
        result += [(begin, finish)] if finish <= WEEK else [(begin, WEEK), (0, finish - WEEK)]
    return result


def _clean_interval(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Horário da tarifa inválido.")
    start, end = _time(raw.get("start")), _time(raw.get("end"))
    if start == end:
        raise ValueError("O início e o fim de cada horário devem ser diferentes.")
    days = raw.get("days")
    if not isinstance(days, list) or not all(
            isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6 for d in days):
        raise ValueError("Dias do horário inválidos.")
    if not days:
        raise ValueError("Escolha ao menos um dia para cada horário.")
    prices = raw.get("prices")
    if not isinstance(prices, dict) or not prices:
        raise ValueError("Informe a tarifa de cada horário.")
    cleaned = {}
    for connector_id, value in prices.items():
        try:
            amount = _dec(value)
        except (TypeError, ValueError, InvalidOperation):
            amount = Decimal("NaN")
        if isinstance(value, bool) or not amount.is_finite() or not Decimal(0) <= amount <= MAX_PRICE:
            raise ValueError("A tarifa de cada horário vai de R$ 0,00 a R$ 100,00.")
        cleaned[str(connector_id)] = str(amount.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
    return {"start": start, "end": end, "days": sorted(set(days)), "prices": cleaned}


def _clean_schedule(schedule) -> dict:
    intervals = schedule.get("intervals")
    if not isinstance(intervals, list):
        raise ValueError("Horários da tarifa inválidos.")
    if len(intervals) > MAX_INTERVALS:
        raise ValueError(f"Cadastre no máximo {MAX_INTERVALS} horários.")
    intervals = sorted((_clean_interval(item) for item in intervals),
                       key=lambda item: (item["days"][0], item["start"], item["end"]))
    for index, first in enumerate(intervals):
        for second in intervals[index + 1:]:
            overlap = [max(a, c) for a, b in _segments(first) for c, d in _segments(second) if a < d and c < b]
            if overlap:
                raise ValueError(f"Os horários {window_label(first)} e {window_label(second)} se sobrepõem "
                                 f"({DAY_LABELS[min(overlap) // DAY]}).")
    return {"enabled": schedule["enabled"], "intervals": intervals}


def merge_rules(stored, body, connector_ids) -> dict:
    """Regras de um PUT sobre as salvas, campo a campo (o que faltar continua como está).

    Preços de horário de conectores fora de ``connector_ids`` (outro posto) são descartados.
    O resultado ainda passa por ``clean_rules``.
    """
    merged = deepcopy(stored)
    for key, value in (body if isinstance(body, dict) else {}).items():
        merged[key] = ({**merged[key], **deepcopy(value)} if isinstance(value, dict) and isinstance(merged.get(key), dict)
                       else deepcopy(value))
    schedule = merged.get("schedule")
    intervals = schedule.get("intervals") if isinstance(schedule, dict) else None
    allowed = {str(item) for item in connector_ids}
    for interval in intervals if isinstance(intervals, list) else ():
        if isinstance(interval, dict) and isinstance(interval.get("prices"), dict):
            interval["prices"] = {key: value for key, value in interval["prices"].items() if str(key) in allowed}
    return merged


def stored_rules(raw) -> dict:
    """Regras salvas no banco; um valor antigo inválido volta ao padrão em vez de falhar."""
    try:
        return clean_rules(raw)
    except ValueError:
        return deepcopy(DEFAULT_RULES)


def active_interval(rules, local_now: datetime | None) -> dict | None:
    """Horário da tarifação vigente em ``local_now`` (com ``index``) ou ``None``."""
    schedule = (rules or {}).get("schedule") or {}
    if not schedule.get("enabled") or local_now is None:
        return None
    minute = local_now.weekday() * DAY + local_now.hour * 60 + local_now.minute
    for index, interval in enumerate(schedule.get("intervals") or []):
        if any(begin <= minute < end for begin, end in _segments(interval)):
            return {**interval, "index": index}
    return None


def base_now(interval, connector_id, base) -> Decimal:
    """Tarifa base do conector agora: a do horário vigente ou, sem ela, a base do conector."""
    price = ((interval or {}).get("prices") or {}).get(str(connector_id))
    return _dec(price if price is not None else base).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def connector_price(status, connector_id, base) -> tuple[Decimal, Decimal]:
    """``(base agora, preço agora)`` de um conector a partir de ``demand_status``."""
    current = base_now(status.get("schedule_now"), connector_id, base)
    return current, dynamic_price(current, status["multiplier"])


def tariff_reason(multiplier, level, interval) -> tuple[str, str]:
    """Motivo da tarifa atual: ``(chave, rótulo)`` — demanda, horário, os dois ou preço normal."""
    surge = _dec(multiplier) > 1
    demand = "Demanda muito alta" if level == "very_high" else "Alta demanda"
    if surge and interval:
        return "demand_schedule", f"{demand} · Horário {window_label(interval)}"
    if surge:
        return "demand", demand
    if interval:
        return "schedule", f"Horário {window_label(interval)}"
    return "normal", "Preço normal"


def busy_fraction(intervals, now: datetime, connectors: int, minutes: int = WINDOW_MINUTES) -> Decimal:
    """Fração média de conectores ocupados na janela ``[now - minutes, now]``.

    ``intervals``: pares ``(início, fim)`` de recargas (``fim`` ``None`` = em curso).
    """
    if connectors <= 0:
        return Decimal(0)
    start = now - timedelta(minutes=minutes)
    busy = Decimal(0)
    for begin, end in intervals:
        if begin is None:
            continue
        overlap = (min(end or now, now) - max(begin, start)).total_seconds()
        if overlap > 0:
            busy += Decimal(str(overlap))
    return _clamp(busy / Decimal(minutes * 60 * connectors))


def _level(pressure: Decimal) -> tuple[str, str]:
    return next((key, label) for minimum, key, label in LEVELS if pressure >= minimum)


def demand_status(rules, signals) -> dict:
    """Multiplicador atual, nível da demanda e os fatores que levaram a ele."""
    rules = stored_rules(rules)
    demand = rules["demand"]
    connectors = max(0, int(signals.get("connectors") or 0))
    in_use = max(0, int(signals.get("in_use") or 0))
    reserved = max(0, int(signals.get("reserved") or 0))
    busy_15m = _clamp(_dec(signals.get("busy_15m") or 0))
    starts = max(0, int(signals.get("starts_60m") or 0))
    baseline = max(Decimal(0), _dec(signals.get("baseline_60m") or 0))
    interval = active_interval(rules, signals.get("local_now"))

    occupancy_now = _clamp(Decimal(in_use + reserved) / connectors) if connectors else Decimal(0)
    utilization = occupancy_now * Decimal("0.6") + busy_15m * Decimal("0.4")
    occupancy_pressure = _clamp((utilization - Decimal("0.5")) / Decimal("0.5"))
    trend = (Decimal(starts) + 1) / (baseline + 1)
    trend_pressure = _clamp((trend - 1) / 2)
    queue = Decimal("0.15") if connectors and in_use + reserved >= connectors and reserved else Decimal(0)
    raw = _clamp(occupancy_pressure * Decimal("0.65") + trend_pressure * Decimal("0.35") + queue)
    shaped = _clamp(Decimal(str(float(raw) ** float(SENSITIVITY[demand["sensitivity"]])))) if raw else Decimal(0)

    cap = Decimal(demand["max_increase_percent"]) / 100
    multiplier = Decimal(1)
    if demand["enabled"] and connectors:
        multiplier = (1 + cap * shaped)
        multiplier = (multiplier / STEP).to_integral_value(rounding=ROUND_FLOOR) * STEP
        if multiplier < Decimal("1.05"):
            multiplier = Decimal(1)
    multiplier = multiplier.quantize(Decimal("0.01"))
    level, label = _level(shaped)
    percent = int((occupancy_now * 100).to_integral_value(rounding=ROUND_HALF_UP))
    factors = [
        {"key": "occupancy", "label": "Ocupação agora",
         "value": f"{in_use + reserved} de {connectors}" if connectors else "Sem conectores online",
         "detail": f"{percent}% ({in_use} em recarga, {reserved} reservado{'s' if reserved != 1 else ''})"},
        {"key": "average", "label": "Ocupação média (15 min)",
         "value": f"{int((busy_15m * 100).to_integral_value(rounding=ROUND_HALF_UP))}%", "detail": None},
        {"key": "trend", "label": "Recargas na última hora",
         "value": str(starts), "detail": f"normal neste horário: {baseline.quantize(Decimal('0.1'))}".replace(".", ",")},
    ]
    reason, reason_label = tariff_reason(multiplier, level, interval)
    return {
        "enabled": demand["enabled"],
        "multiplier": str(multiplier),
        "increase_percent": int(((multiplier - 1) * 100).to_integral_value(rounding=ROUND_HALF_UP)),
        "max_multiplier": str((1 + cap).quantize(Decimal("0.01"))),
        "pressure": int((shaped * 100).to_integral_value(rounding=ROUND_HALF_UP)),
        "level": level,
        "level_label": label,
        "peak_now": False,  # legado (app 0.6.8): o horário de pico não entra mais no cálculo
        "schedule_now": interval,
        "reason": reason,
        "reason_label": reason_label,
        "factors": factors,
    }


def dynamic_price(base, multiplier) -> Decimal:
    """Preço por kWh com o multiplicador (4 casas, como ``price_per_kwh``)."""
    return (_dec(base) * _dec(multiplier)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def multiplier_label(multiplier) -> str:
    """``1.30`` -> ``1,3×``; ``1.00`` -> ``1×``."""
    value = _dec(multiplier).normalize()
    return f"{value:f}".replace(".", ",") + "×"


def days_label(days) -> str:
    names = [DAY_LABELS[d] for d in sorted(set(days)) if 0 <= d < 7]
    if not names:
        return "Nenhum dia"
    if len(names) == 7:
        return "Todos os dias"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " e " + names[-1]
