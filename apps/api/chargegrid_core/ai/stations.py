"""Filtro, ordenação e formato compacto de postos para o assistente.

Recebe registros no mesmo formato da API REST (``GET /v1/stations``): posto com
``connectors`` e estado público de cada ponto. Não acessa rede nem banco.
"""

from __future__ import annotations

import math

from .text import clean, normalized

CONNECTOR_LABELS = {"type2": "Tipo 2", "ccs2": "CCS2", "chademo": "CHAdeMO", "gbt": "GB/T", "type1": "Tipo 1"}
AMENITIES = ("restaurante", "cafe", "banheiro", "shopping", "conveniencia", "wifi", "estacionamento")
_AMENITY_SYNONYMS = {
    "restaurante": ("restaurante", "restaurant", "lanchonete", "comida", "food", "almoco", "jantar"),
    "cafe": ("cafe", "cafeteria", "coffee", "padaria"),
    "banheiro": ("banheiro", "sanitario", "toilet", "restroom", "wc"),
    "shopping": ("shopping", "mall"),
    "conveniencia": ("conveniencia", "mercado", "loja", "convenience", "store"),
    "wifi": ("wifi", "wi-fi", "internet"),
    "estacionamento": ("estacionamento", "parking"),
}


def normalize_connector(value: object) -> str:
    key = "".join(c for c in normalized(value) if c.isalnum())
    aliases = {"tipo2": "type2", "typeii": "type2", "mennekes": "type2", "ccs": "ccs2", "ccstype2": "ccs2",
               "combo2": "ccs2", "ccscombo2": "ccs2", "gbt": "gbt", "tipo1": "type1", "j1772": "type1"}
    return aliases.get(key, key)


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    first, second = math.radians(float(lat1)), math.radians(float(lat2))
    cosine = (math.sin(first) * math.sin(second)
              + math.cos(first) * math.cos(second) * math.cos(math.radians(float(lng2) - float(lng1))))
    return 6371 * math.acos(max(-1.0, min(1.0, cosine)))


def _float(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def point_available(point: dict) -> bool:
    return (point.get("active") is not False and not point.get("retired")
            and point.get("online") is not False and point.get("available") is True
            and point.get("availability_status") in (None, "available"))


def station_amenities(station: dict) -> list[str]:
    """Comodidades normalizadas, quando o posto as informa (lista de textos ou objetos)."""
    found = []
    for item in station.get("amenities") or ():
        raw = item if isinstance(item, str) else " ".join(
            str(item.get(key) or "") for key in ("kind", "type", "category", "name")) if isinstance(item, dict) else ""
        text = normalized(raw)
        for amenity, synonyms in _AMENITY_SYNONYMS.items():
            if amenity not in found and any(word in text for word in synonyms):
                found.append(amenity)
    return found


def amenity_from_text(text: str) -> list[str]:
    query = f" {normalized(text)} "
    return [amenity for amenity, synonyms in _AMENITY_SYNONYMS.items()
            if any(f" {word}" in query for word in synonyms)]


def point_price(point: dict) -> float | None:
    """Preço por kWh cobrado agora: ``dynamic_price_per_kwh`` (horário × demanda) ou a tarifa do ponto."""
    final = _float(point.get("dynamic_price_per_kwh"))
    return final if final is not None else _float(point.get("price_per_kwh"))


def compact_point(point: dict) -> dict:
    status = point.get("availability_status") or ("available" if point.get("available") else "unknown")
    if point.get("active") is False or point.get("retired"):
        status = "disabled"
    elif point.get("online") is False and status == "available":
        status = "offline"
    return {
        "connector_id": str(point.get("id")),
        "code": clean(point.get("public_code"), 50),
        "connector_type": clean(point.get("connector_type"), 50),
        "power_kw": _float(point.get("power_kw")),
        # Preço final que o motorista paga agora (o mesmo da tela do posto). O acréscimo por
        # demanda é dado interno do dono: nunca sai daqui como multiplicador ou rótulo.
        "price_per_kwh": point_price(point),
        "max_duration_minutes": point.get("max_duration_minutes"),
        "status": status,
        "available_now": point_available(point),
    }


def compact_station(station: dict, *, points: list[dict] | None = None, origin: dict | None = None) -> dict:
    chosen = (station.get("connectors") or []) if points is None else points
    result = {
        "station_id": str(station.get("id")),
        "name": clean(station.get("name"), 100),
        "address": clean(station.get("address"), 160),
        "points": [compact_point(point) for point in chosen[:6]],
        "available_points": sum(point_available(point) for point in chosen),
    }
    amenities = station_amenities(station)
    if amenities:
        result["amenities"] = amenities
    if origin and station.get("latitude") is not None and station.get("longitude") is not None:
        result["distance_km"] = round(distance_km(origin["lat"], origin["lng"], station["latitude"], station["longitude"]), 1)
    return result


def _matching_points(station: dict, filters: dict) -> list[dict]:
    wanted = normalize_connector(filters["connector_type"]) if filters.get("connector_type") else None
    minimum = filters.get("min_power_kw")
    maximum = filters.get("max_price_per_kwh")
    return [point for point in station.get("connectors") or []
            if point.get("active") is not False and not point.get("retired")
            and (wanted is None or normalize_connector(point.get("connector_type")) == wanted)
            and (minimum is None or (_float(point.get("power_kw"), 0) >= minimum))
            and (maximum is None or ((point_price(point) if point_price(point) is not None else math.inf) <= maximum))
            and (not filters.get("available_only") or point_available(point))]


def filter_stations(stations: list[dict], filters: dict, *, origin: dict | None = None,
                    limit: int = 5) -> tuple[list[dict], dict]:
    """Aplica filtros estruturados; retorna (postos compactos, notas sobre filtros)."""
    notes = {}
    center = filters.get("near") or origin
    radius = filters.get("radius_km")
    text = normalized(filters.get("text")) if filters.get("text") else ""
    wanted_amenities = list(filters.get("amenities") or ())
    amenities_known = any(station.get("amenities") for station in stations)
    if wanted_amenities and not amenities_known:
        notes["amenities"] = "Os postos ainda não informam comodidades; esse filtro não foi aplicado."
        wanted_amenities = []
    results = []
    for station in stations:
        if station.get("active") is False:
            continue
        if text and text not in normalized(f"{station.get('name')} {station.get('address')}"):
            continue
        if wanted_amenities and not set(wanted_amenities) <= set(station_amenities(station)):
            continue
        points = _matching_points(station, filters)
        if not points:
            continue
        compact = compact_station(station, points=points, origin=center)
        if center and radius and compact.get("distance_km", 0) > radius:
            continue
        compact["_best_price"] = min((point_price(p) if point_price(p) is not None else math.inf for p in points),
                                      default=math.inf)
        compact["_best_power"] = max((_float(p.get("power_kw"), 0) for p in points), default=0)
        results.append(compact)
    sort = filters.get("sort") or ("distance" if center else "default")
    if sort == "distance" and not center:
        sort = "default"
        notes["sort"] = "Sem localização de referência; resultados sem ordenação por distância."
    keys = {
        "price": lambda s: (s["_best_price"], s.get("distance_km") or 0, s["station_id"]),
        "distance": lambda s: (s.get("distance_km") or 0, s["station_id"]),
        "power": lambda s: (-s["_best_power"], s["_best_price"], s["station_id"]),
        "default": lambda s: (-s["available_points"], s.get("distance_km") or 0, s["station_id"]),
    }
    results.sort(key=keys.get(sort, keys["default"]))
    for item in results:
        item.pop("_best_price", None)
        item.pop("_best_power", None)
    notes["total"] = len(results)
    return results[:limit], notes
