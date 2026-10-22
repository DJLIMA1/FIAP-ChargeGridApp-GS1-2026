""""Melhor horário para carregar mais barato" num posto (para o motorista).

Preço esperado de cada hora = tarifa base do horário do dono (``pricing.base_now``) ×
multiplicador de demanda previsto (``pricing.demand_status`` com a ocupação prevista).
É sempre uma **estimativa**: o preço é travado ao reservar ou iniciar a recarga.
A ocupação aparece só como nível (baixa/média/alta), sem expor números do dono.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from .. import pricing
from .calendar import iso

LEVELS = ((0.4, "low", "Pouco movimento"), (0.8, "medium", "Movimento médio"), (2.0, "high", "Muito movimento"))
MAX_WINDOW = 3
DAYTIME = (6, 23)
NOTE = "Estimativa. O preço é travado quando você reserva ou inicia a recarga."


def level(occ: float) -> tuple[str, str]:
    return next((key, label) for limit, key, label in LEVELS if occ < limit)


def expected_multiplier(rules, connectors: int, occ: float, when) -> Decimal:
    """Multiplicador que a regra de preço daria com a ocupação prevista (tendência neutra)."""
    if connectors <= 0:
        return Decimal(1)
    in_use = max(0, min(connectors, round(occ * connectors)))
    status = pricing.demand_status(rules, {
        "connectors": connectors, "in_use": in_use, "reserved": 0,
        "busy_15m": Decimal(str(round(occ, 4))), "starts_60m": 0, "baseline_60m": 0, "local_now": when})
    return Decimal(status["multiplier"])


def hour_price(rules, connectors: list[dict], when, multiplier: Decimal) -> Decimal | None:
    """Menor preço por kWh entre os conectores na hora ``when`` (a partir de)."""
    interval = pricing.active_interval(rules, when)
    prices = [pricing.connector_price({"schedule_now": interval, "multiplier": multiplier, "speed": rules.get("speed")},
                                     c["id"], c["price_per_kwh"], c.get("power_tier", "max"))[1]
              for c in connectors]
    return min(prices) if prices else None


def best_times(rules, connectors: list[dict], hours, now_price: Decimal | None) -> dict:
    """``hours``: ``[(início local, ocupação prevista)]`` das próximas horas."""
    rules = pricing.stored_rules(rules)
    rows = []
    for when, occ in hours:
        occ = occ or 0.0
        multiplier = expected_multiplier(rules, len(connectors), occ, when)
        price = hour_price(rules, connectors, when, multiplier)
        key, label = level(occ)
        interval = pricing.active_interval(rules, when)
        rows.append({"start": when, "price": price, "level": key, "level_label": label, "occ": occ,
                     "multiplier": multiplier, "interval": interval})
    priced = [row for row in rows if row["price"] is not None]
    if not priced:
        return {"hours": [], "best": None, "now": None, "note": NOTE}
    stable = len({row["price"] for row in priced}) == 1
    candidates = range(len(priced))
    if stable:
        # Preço igual o dia todo: sugere o horário com menos movimento, mas não de madrugada.
        daytime = [i for i in candidates if DAYTIME[0] <= priced[i]["start"].hour < DAYTIME[1]]
        candidates = daytime or candidates
    best_index = min(candidates, key=lambda i: (priced[i]["price"], priced[i]["occ"], i))
    best = priced[best_index]
    end = best_index + 1
    while (end < len(priced) and end - best_index < MAX_WINDOW and priced[end]["price"] == best["price"]
           and priced[end]["level"] == best["level"]):
        end += 1
    if best["interval"] is not None:
        reason = f"Tarifa menor no horário {pricing.window_label(best['interval'])}"
    elif best["multiplier"] < max(row["multiplier"] for row in priced):
        reason = "Sem acréscimo de demanda previsto"
    else:
        reason = "Preço igual nas próximas horas" if stable else "Menos movimento previsto"
    reference = now_price if now_price is not None else priced[0]["price"]
    saving = None
    if reference and best["price"] < reference:
        saving = int(((reference - best["price"]) * 100 / reference).to_integral_value())
    finish = priced[end - 1]["start"].replace(minute=0)
    return {
        "hours": [{"start": iso(row["start"]), "expected_price_per_kwh": str(row["price"]),
                   "level": row["level"], "level_label": row["level_label"]} for row in priced],
        "best": {"start": iso(best["start"]), "end": iso(finish + timedelta(hours=1)),
                 "price_from": str(best["price"]), "saving_vs_now_percent": saving, "reason": reason,
                 "level_label": best["level_label"]},
        "now": {"price_per_kwh": str(reference)} if reference is not None else None,
        "stable": stable,
        "note": NOTE,
    }
