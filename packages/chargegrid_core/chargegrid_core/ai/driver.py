"""Ferramenta ``plan_driver_shift``: liga o assistente ao planejador do Modo Motorista.

Usa a fachada ``chargegrid_core.driver`` (``build_plan``) — a mesma de
``POST /v1/driver/plan`` e da demo. O import é opcional: se o pacote driver não
existir, a ferramenta simplesmente não é registrada.
"""

from __future__ import annotations

import importlib
from datetime import datetime

from .insights import LOCAL_TZ
from .places import resolve_place
from .text import clean, normalized

SCHEMA = {
    "type": "object",
    "properties": {
        "current_soc_percent": {"type": "number", "minimum": 0, "maximum": 100,
                                "description": "Bateria atual em %. Pergunte se o usuário não informou."},
        "shift_start": {"type": "string", "maxLength": 5, "description": "Início do turno HH:MM (ex.: 07:00)."},
        "shift_end": {"type": "string", "maxLength": 5, "description": "Fim do turno HH:MM (ex.: 19:00)."},
        "vehicle": {"type": "string", "maxLength": 60, "description": "Modelo do carro, se citado (ex.: BYD Dolphin)."},
        "lunch_time": {"type": "string", "maxLength": 5, "description": "Horário preferido de almoço HH:MM."},
        "dinner_time": {"type": "string", "maxLength": 5, "description": "Horário preferido de jantar HH:MM."},
        "near_place": {"type": "string", "maxLength": 80, "description": "Região onde vai começar a rodar."},
        "full_shift": {"type": "boolean", "description": "true para planejar o turno inteiro de hoje."},
    },
}
DESCRIPTION = ("Planeja o turno de um motorista de aplicativo com carro elétrico (Modo Motorista): quando e onde "
               "recarregar evitando picos de demanda e combinando com refeições, com lucro estimado vs. recarregar "
               "só quando a bateria fica baixa. Usa o perfil salvo do motorista; argumentos sobrescrevem.")
DEFAULT_SOC = 50.0


def _module():
    package = __package__.rsplit(".", 1)[0]
    try:
        module = importlib.import_module(package + ".driver")
    except ImportError:
        return None
    return module if callable(getattr(module, "build_plan", None)) else None


def planner():
    """Função de planejamento para o assistente, ou None se o Modo Motorista não estiver instalado
    ou estiver descontinuado (``chargegrid_core.driver.DISCONTINUED``)."""
    module = _module()
    return plan_for_assistant if module and not getattr(module, "DISCONTINUED", False) else None


def _preset(module, text: str | None) -> str | None:
    wanted = normalized(text)
    if not wanted:
        return None
    for key, preset in module.PRESETS.items():
        name = normalized(getattr(preset, "name", key))
        if wanted in name or name in wanted or wanted.replace(" ", "_") == key:
            return key
    return None


def _meal(preferences: dict, kind: str, start: str | None) -> None:
    if not start:
        return
    meals = [dict(m) for m in preferences.get("meals") or []]
    for meal in meals:
        if meal.get("kind") == kind:
            meal.update(start=start, enabled=True)
            break
    else:
        meals.append({"kind": kind, "start": start, "enabled": True})
    preferences["meals"] = meals


def plan_for_assistant(args: dict, stations: list[dict], now: datetime, saved_profile: dict | None = None,
                       origin: dict | None = None) -> dict:
    """Argumentos do modelo + perfil salvo -> plano compacto para a resposta do chat."""
    module = _module()
    if module is None:
        return {"error": "Modo Motorista indisponível"}
    base = module.merge_profile(saved_profile, None)
    preferences = dict(base["preferences"])
    for key in ("shift_start", "shift_end"):
        if args.get(key):
            preferences[key] = args[key]
    _meal(preferences, "almoco", args.get("lunch_time"))
    _meal(preferences, "jantar", args.get("dinner_time"))
    overrides = {"preferences": preferences}
    preset = _preset(module, args.get("vehicle"))
    if preset:
        overrides["vehicle"] = {"preset": preset}
    try:
        profile = module.validate_profile(module.merge_profile(base, overrides))
    except ValueError as exc:
        return {"error": str(exc)}
    notes = []
    soc = args.get("current_soc_percent")
    if soc is None:
        soc = DEFAULT_SOC
        notes.append(f"Bateria atual não informada: considerei {DEFAULT_SOC:.0f}%. Peça o valor real ao motorista.")
    if args.get("vehicle") and not preset:
        notes.append("Modelo de carro não reconhecido; usei o veículo do perfil.")
    payload = {"soc_percent": float(soc), "mode": "full_shift" if args.get("full_shift") else "auto"}
    place = resolve_place(args.get("near_place")) or origin  # sem bairro citado: localização do aparelho
    if place:
        payload.update(lat=place["lat"], lng=place["lng"])
    local_now = now.astimezone(LOCAL_TZ).replace(tzinfo=None) if now.tzinfo else now
    try:
        plan = module.build_plan(payload, profile, stations, local_now)
    except (ValueError, TypeError) as exc:
        return {"error": str(exc) or "não foi possível planejar"}
    return _compact(plan, notes)


def _compact(plan: dict, notes: list[str]) -> dict:
    totals = plan.get("totals") or {}
    return {
        "estimate": True,
        "window": f"{plan['window']['start']}–{plan['window']['end']} ({plan['window']['date']})",
        "vehicle": (plan.get("vehicle") or {}).get("name"),
        "stops": [{
            "station_id": stop.get("station_id"), "connector_id": stop.get("connector_id"),
            "station_name": clean(stop.get("station_name"), 100), "point_code": stop.get("public_code"),
            "start": stop.get("start"), "end": stop.get("end"), "kwh": stop.get("kwh"), "cost_brl": stop.get("cost"),
            "soc_before": stop.get("soc_before"), "soc_after": stop.get("soc_after"), "meal": stop.get("meal"),
            "reason": clean(stop.get("reason"), 300),
        } for stop in (plan.get("stops") or [])[:4]],
        "peaks": [peak.get("label") for peak in (plan.get("peaks") or [])[:4]],
        "totals": {key: totals.get(key) for key in ("net_profit", "gross_earnings", "charging_cost", "energy_kwh",
                                                     "stops", "end_soc_percent", "min_soc_percent")},
        "versus_naive": (plan.get("comparison") or {}).get("message"),
        "alerts": [alert.get("message") for alert in (plan.get("alerts") or [])[:3]],
        "notes": notes + ["Demanda e ganhos são estimativas (sem dados oficiais de aplicativos)."],
    }
