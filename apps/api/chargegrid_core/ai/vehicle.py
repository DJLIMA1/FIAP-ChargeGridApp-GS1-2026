"""Carro do usuário para o assistente: specs do cadastro (``/me/vehicle``) e limite de potência.

Reusa ``chargegrid_core.driver.vehicles`` (mesmos presets do cadastro e do app) e
``chargegrid_core.power.car_limit`` (limite AC/DC aplicado ao iniciar a recarga).
"""

from __future__ import annotations

from .text import clean

_FALLBACK = {"name": "BYD Dolphin", "usable_battery_kwh": 44.9, "consumption_kwh_per_100km": 14.0,
             "max_ac_kw": 6.6, "max_dc_kw": 60.0, "connectors": ["type2", "ccs2"]}


def car_specs(vehicle: dict | None, *, registered: bool) -> dict:
    """Specs compactas do carro; sem cadastro, o carro padrão do app (BYD Dolphin) marcado como tal."""
    data = dict(_FALLBACK)
    try:
        from ..driver.vehicles import vehicle_from_dict

        profile = vehicle_from_dict(vehicle if isinstance(vehicle, dict) and vehicle else None)
        data = {"name": profile.name, "usable_battery_kwh": float(profile.usable_battery_kwh),
                "consumption_kwh_per_100km": float(profile.consumption_kwh_per_100km),
                "max_ac_kw": float(profile.max_ac_kw), "max_dc_kw": float(profile.max_dc_kw),
                "connectors": list(profile.connectors)}
    except (ImportError, ValueError, TypeError):
        registered = False
    usable, consumption = data["usable_battery_kwh"], data["consumption_kwh_per_100km"]
    return {
        "name": clean(data["name"], 60), "usable_battery_kwh": round(usable, 1),
        "consumption_kwh_per_100km": round(consumption, 1),
        "range_km": round(usable / consumption * 100) if consumption else None,
        "max_ac_kw": data["max_ac_kw"], "max_dc_kw": data["max_dc_kw"], "connectors": data["connectors"][:6],
        "registered": bool(registered),
    }


def car_power_limit(specs: dict | None, connector_type) -> float | None:
    """Potência máxima que o carro aceita neste tipo de conector (DC ou AC), ou ``None``."""
    if not specs:
        return None
    try:
        from ..power import car_limit
    except ImportError:
        return None
    value = car_limit(connector_type, max_ac_kw=specs.get("max_ac_kw"), max_dc_kw=specs.get("max_dc_kw"))
    return float(value) if value is not None else None


def accepts(specs: dict | None, connector_type) -> bool:
    """O carro tem esse conector? Sem cadastro (ou sem lista), não filtra."""
    if not specs or not specs.get("connectors"):
        return True
    try:
        from ..driver.vehicles import normalize_connector
    except ImportError:
        return True
    return normalize_connector(connector_type) in {normalize_connector(c) for c in specs["connectors"]}
