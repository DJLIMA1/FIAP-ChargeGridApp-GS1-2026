"""Janelas de lotação/ociosidade previstas e sugestões acionáveis para o dono.

As sugestões só usam instrumentos que já existem: o preço dinâmico (``demand``) e a
tarifa por horário (``schedule``) de :mod:`chargegrid_core.pricing`. Cada uma traz um
``patch`` aceito por ``PUT /stations/{id}/pricing`` (PUT parcial) e a prévia dos preços.
Nada é aplicado sem o dono confirmar; nenhuma receita é inventada (a elasticidade real
é desconhecida).
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from .. import pricing
from .calendar import WEEKDAYS_LONG, day_word, iso, window_text

FULL = 0.8
IDLE = 0.15
IDLE_HOURS = 3
IDLE_DAY = (8, 22)
TARGET_CAP = 30
PEAK_FACTOR = Decimal("1.10")
IDLE_FACTOR = Decimal("0.90")


def windows(hours, predicate, minimum: int = 1) -> list[dict]:
    """Agrupa horas consecutivas ``(início local, ocupação)`` que satisfazem ``predicate``."""
    found, current = [], None
    for when, occ in hours:
        if occ is not None and predicate(when, occ):
            if current and current["end"] == when:
                current["end"] = when + timedelta(hours=1)
                current["values"].append(occ)
            else:
                current = {"start": when, "end": when + timedelta(hours=1), "values": [occ]}
                found.append(current)
        else:
            current = None
    return [w for w in found if len(w["values"]) >= minimum]


def _labeled(window: dict, today, verb: str, key: str) -> dict:
    values = window.pop("values")
    value = max(values) if key == "max" else min(values)
    return {"start": iso(window["start"]), "end": iso(window["end"]),
            f"{key}_percent": f"{100 * value:.1f}",
            "label": f"{day_word(window['start'].date(), today)} {window_text(window['start'], window['end'])} {verb}",
            "_start": window["start"], "_end": window["end"]}


def peaks_and_idle(hours, today) -> tuple[list[dict], list[dict]]:
    peaks = [_labeled(w, today, "deve lotar", "max") for w in windows(hours, lambda _, occ: occ >= FULL)]
    idle = [_labeled(w, today, "deve ficar vazio", "min")
            for w in windows(hours, lambda when, occ: occ < IDLE and IDLE_DAY[0] <= when.hour < IDLE_DAY[1], IDLE_HOURS)]
    return peaks, idle


def _hhmm(moment) -> str:
    return f"{moment.hour:02d}:00"


def _interval(window: dict, connectors, factor: Decimal) -> dict:
    prices = {str(c["id"]): str((Decimal(str(c["price_per_kwh"])) * factor).quantize(Decimal("0.0001"),
                                                                                     rounding=ROUND_HALF_UP))
              for c in connectors}
    return {"start": _hhmm(window["_start"]), "end": _hhmm(window["_end"]),
            "days": [window["_start"].weekday()], "prices": prices}


def _schedule_patch(rules: dict, interval: dict) -> dict | None:
    """Patch com o novo horário somado aos existentes; ``None`` se conflitar ou exceder o limite."""
    current = deepcopy((rules.get("schedule") or {}).get("intervals") or [])
    schedule = {"enabled": True, "intervals": current + [interval]}
    try:
        pricing.clean_rules({**rules, "schedule": schedule})
    except ValueError:
        return None
    return {"schedule": schedule}


def _preview(connectors, interval: dict) -> list[dict]:
    return [{"connector_id": str(c["id"]), "public_code": c.get("public_code") or "",
             "from": str(Decimal(str(c["price_per_kwh"])).quantize(Decimal("0.0001"))),
             "to": interval["prices"][str(c["id"])]} for c in connectors]


def suggestions(rules: dict, connectors: list[dict], peaks: list[dict], idle: list[dict]) -> list[dict]:
    """Até três sugestões, da mais urgente para a menos."""
    rules = pricing.stored_rules(rules)
    demand = rules["demand"]
    result = []
    if peaks and connectors:
        peak = peaks[0]
        if not demand["enabled"]:
            result.append({
                "kind": "enable_demand", "title": "Ative o preço dinâmico para o pico",
                "detail": f"{peak['label']}. Com o preço dinâmico, a tarifa sobe sozinha quando o posto enche "
                          f"(até {demand['max_increase_percent']}% sobre a base) e volta ao normal depois.",
                "window": {"start": peak["start"], "end": peak["end"]},
                "action": {"type": "pricing_rules", "patch": {"demand": {"enabled": True}}}})
        elif demand["max_increase_percent"] < TARGET_CAP:
            result.append({
                "kind": "raise_demand_cap", "title": f"Aumente o acréscimo máximo para {TARGET_CAP}%",
                "detail": f"{peak['label']}. Hoje o preço dinâmico sobe no máximo "
                          f"{demand['max_increase_percent']}%; com {TARGET_CAP}% o pico fica mais valorizado "
                          "e parte da procura migra para horários livres.",
                "window": {"start": peak["start"], "end": peak["end"]},
                "action": {"type": "pricing_rules", "patch": {"demand": {"max_increase_percent": TARGET_CAP}}}})
        interval = _interval(peak, connectors, PEAK_FACTOR)
        patch = _schedule_patch(rules, interval)
        if patch:
            weekday = WEEKDAYS_LONG[peak["_start"].weekday()]
            result.append({
                "kind": "schedule_peak", "title": f"Tarifa de pico {interval['start']}–{interval['end']}",
                "detail": f"{peak['label']}. Crie um horário com tarifa base 10% maior toda {weekday} "
                          f"das {interval['start']} às {interval['end']}. O preço dinâmico continua por cima.",
                "window": {"start": peak["start"], "end": peak["end"]},
                "action": {"type": "pricing_rules", "patch": patch, "preview": _preview(connectors, interval)}})
    if idle and connectors:
        quiet = idle[0]
        interval = _interval(quiet, connectors, IDLE_FACTOR)
        patch = _schedule_patch(rules, interval)
        if patch:
            weekday = WEEKDAYS_LONG[quiet["_start"].weekday()]
            result.append({
                "kind": "schedule_idle", "title": f"Tarifa menor {interval['start']}–{interval['end']}",
                "detail": f"{quiet['label']}. Uma tarifa base 10% menor toda {weekday} das {interval['start']} "
                          f"às {interval['end']} aparece para o motorista como melhor horário no app.",
                "window": {"start": quiet["start"], "end": quiet["end"]},
                "action": {"type": "pricing_rules", "patch": patch, "preview": _preview(connectors, interval)}})
    return result[:3]


def public(windows_list: list[dict]) -> list[dict]:
    """Remove os campos internos (``_start``/``_end``)."""
    return [{key: value for key, value in item.items() if not key.startswith("_")} for item in windows_list]
