"""Ferramentas somente leitura do assistente sobre uma fonte de dados injetada.

A ``source`` é implementada pela API (banco, com o usuário autenticado) e pelo
cliente demo (dados em memória). Métodos podem ser síncronos ou ``async``:

* ``list_stations(near: dict | None, radius_km: float | None) -> list[dict]`` (formato REST)
* ``get_station(station_id: str) -> dict | None``
* ``current_reservation() -> dict | None`` / ``current_session() -> dict | None``
* ``recent_sessions(limit: int) -> list[dict]`` / ``month_summary() -> dict | None``
* ``owner_stations() -> list[dict]`` / ``owner_sessions(since: datetime) -> list[dict]``
* opcionais: ``get_connector(id)``, ``driver_profile() -> dict | None`` (perfil salvo do Modo
  Motorista) e ``driver_stations() -> list[dict]`` (postos para o planejador)

O titular é sempre o usuário autenticado da ``source``: nenhuma ferramenta
recebe ``user_id`` do modelo.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta

from . import driver as driver_slot
from .estimates import EstimateError, estimate_charge
from .insights import LOCAL_TZ, owner_indicators, owner_recommendations
from .schema import ToolArgumentError, parse_arguments, validate
from .search import FILTER_SCHEMA, filters_from_tool
from .stations import compact_station, filter_stations
from .text import clean

MAX_RESULT_CHARS = 3500
SESSION_LABELS = {"starting": "aguardando equipamento", "charging": "em recarga", "stopping": "parando",
                  "completed": "concluída", "failed": "falhou", "interrupted": "interrompida"}
RESERVATION_LABELS = {"pending_device": "aguardando confirmação do equipamento", "confirmed": "confirmada",
                      "cancelling": "cancelando", "cancelled": "cancelada", "expired": "expirada",
                      "consumed": "usada"}

_ID = {"type": "string", "minLength": 1, "maxLength": 64}
SPECS = {
    "search_stations": {
        "description": ("Busca postos de recarga com filtros (lugar, conector, potência, tarifa, disponibilidade). "
                        "Retorna até 5 postos com pontos, preços e estado atual."),
        "parameters": {"type": "object", "properties": {
            **FILTER_SCHEMA["properties"], "limit": {"type": "integer", "minimum": 1, "maximum": 5}}},
    },
    "get_station_details": {
        "description": "Detalhes de um posto: pontos, conector, potência, tarifa (R$/kWh), tempo máximo e disponibilidade.",
        "parameters": {"type": "object", "properties": {"station_id": _ID}, "required": ["station_id"]},
    },
    "estimate_charge": {
        "description": ("Estima energia, tempo e custo de uma recarga num ponto (connector_id) ou com potência/tarifa "
                        "informadas. Informe um alvo: energy_kwh, faixa de bateria (battery_kwh + from/to_percent), "
                        "budget_brl ou minutes."),
        "parameters": {"type": "object", "properties": {
            "connector_id": _ID,
            "power_kw": {"type": "number", "minimum": 0.5, "maximum": 1000},
            "price_per_kwh": {"type": "number", "minimum": 0, "maximum": 100},
            "energy_kwh": {"type": "number", "minimum": 0.1, "maximum": 300},
            "battery_kwh": {"type": "number", "minimum": 5, "maximum": 300},
            "from_percent": {"type": "number", "minimum": 0, "maximum": 100},
            "to_percent": {"type": "number", "minimum": 0, "maximum": 100},
            "budget_brl": {"type": "number", "minimum": 1, "maximum": 5000},
            "minutes": {"type": "number", "minimum": 1, "maximum": 1440}}},
    },
    "get_my_reservation": {
        "description": "Reserva ativa do usuário logado (posto, ponto, estado e prazo de chegada).",
        "parameters": {"type": "object", "properties": {}},
    },
    "get_current_charging": {
        "description": "Recarga em andamento do usuário logado (energia, custo estimado, estado).",
        "parameters": {"type": "object", "properties": {}},
    },
    "get_my_charging_history": {
        "description": "Últimas recargas do usuário logado e gasto estimado do mês corrente.",
        "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 10}}},
    },
    "get_owner_indicators": {
        "description": ("Indicadores dos postos do próprio dono: receita e energia estimadas, sessões por hora, "
                        "ocupação, falhas e pontos offline, com recomendações-base."),
        "parameters": {"type": "object", "properties": {"days": {"type": "integer", "minimum": 7, "maximum": 90}}},
        "owner_only": True,
    },
}


async def _call(function, *args, **kwargs):
    result = function(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


def _local(value) -> str | None:
    if not value:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(LOCAL_TZ).strftime("%d/%m %H:%M")
    except (TypeError, ValueError):
        return None


def _money(value) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def compact_session(record: dict) -> dict:
    connector = record.get("connector") or {}
    return {
        "session_id": str(record.get("id")), "status": SESSION_LABELS.get(record.get("status"), record.get("status")),
        "station_name": clean(record.get("station_name"), 100), "point_code": clean(connector.get("public_code"), 50),
        "energy_kwh": round(float(record.get("energy_wh") or 0) / 1000, 2), "cost_brl": _money(record.get("cost_estimate")),
        "price_per_kwh": _money(record.get("price_per_kwh")), "started_at": _local(record.get("started_at") or record.get("created_at")),
        "ended_at": _local(record.get("ended_at")), "end_reason": record.get("end_reason"),
        "battery_percent": _money(record.get("soc_percent")), "data_source": record.get("source") or "simulated",
    }


class Toolbox:
    """Executa as ferramentas validadas e guarda os resultados da rodada."""

    def __init__(self, source, *, owner: bool = False, now: datetime, origin: dict | None = None):
        self.source, self.owner, self.now, self.origin = source, owner, now, origin
        self.records: list[tuple[str, dict, dict]] = []
        self._points: dict[str, dict] = {}
        self._planner = driver_slot.planner()

    def names(self) -> list[str]:
        names = [name for name, spec in SPECS.items() if self.owner or not spec.get("owner_only")]
        if self._planner:
            names.append("plan_driver_shift")
        return names

    def definitions(self) -> list[dict]:
        tools = []
        for name in self.names():
            spec = SPECS.get(name) or {"description": driver_slot.DESCRIPTION, "parameters": driver_slot.SCHEMA}
            tools.append({"type": "function", "function": {
                "name": name, "description": spec["description"], "parameters": spec["parameters"]}})
        return tools

    async def execute(self, name: str, raw_arguments: object) -> dict:
        """Valida e executa; erros viram ``{'error': ...}`` para o modelo corrigir."""
        if name not in self.names():
            data = {"error": f"ferramenta desconhecida ou não permitida: {clean(name, 40)}"}
            self.records.append((name, {}, data))
            return data
        try:
            schema = SPECS[name]["parameters"] if name in SPECS else driver_slot.SCHEMA
            args = validate(parse_arguments(raw_arguments), schema)
            data = await getattr(self, "_" + name)(**args) if name in SPECS else await self._plan_driver_shift(args)
        except (ToolArgumentError, EstimateError) as exc:
            args, data = {}, {"error": str(exc)}
        self.records.append((name, args, data))
        return data

    @staticmethod
    def serialize(data: dict) -> str:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
        return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + "…(truncado)"

    def _remember(self, compact: dict):
        for point in compact.get("points") or []:
            self._points[point["connector_id"]] = {**point, "station_id": compact["station_id"],
                                                   "station_name": compact["name"]}

    async def _search_stations(self, limit: int = 3, **arguments) -> dict:
        found = filters_from_tool(arguments, origin=self.origin)
        filters = found["filters"]
        stations = await _call(self.source.list_stations, near=filters.get("near"), radius_km=filters.get("radius_km"))
        results, notes = filter_stations(stations or [], filters, origin=self.origin, limit=limit)
        for item in results:
            self._remember(item)
        warnings = [*found["unsupported"], *(v for k, v in notes.items() if k != "total")]
        return {"filters": found["explanation"], "total_found": notes["total"], "stations": results,
                **({"notes": warnings} if warnings else {})}

    async def _get_station_details(self, station_id: str) -> dict:
        station = await _call(self.source.get_station, station_id)
        if not station:
            return {"error": "posto não encontrado"}
        compact = compact_station(station, origin=self.origin)
        self._remember(compact)
        return compact

    async def _estimate_charge(self, connector_id: str | None = None, **target) -> dict:
        context = {}
        if connector_id:
            point = self._points.get(connector_id)
            if point is None and hasattr(self.source, "get_connector"):
                point = await _call(self.source.get_connector, connector_id)
            if not point:
                return {"error": "ponto não encontrado; busque o posto antes ou informe potência e tarifa"}
            target.setdefault("power_kw", point.get("power_kw"))
            target.setdefault("price_per_kwh", point.get("price_per_kwh"))
            target.setdefault("max_minutes", point.get("max_duration_minutes"))
            context = {"station_id": point.get("station_id"), "station_name": point.get("station_name"),
                       "point_code": point.get("code")}
        power, price = target.pop("power_kw", None), target.pop("price_per_kwh", None)
        result = estimate_charge(float(power or 0), float(price) if price is not None else -1, **target)
        return {**context, "power_kw": power, "price_per_kwh": price, **result}

    async def _get_my_reservation(self) -> dict:
        record = await _call(self.source.current_reservation)
        if not record:
            return {"reservation": None}
        connector = record.get("connector") or {}
        return {"reservation": {
            "status": RESERVATION_LABELS.get(record.get("status"), record.get("status")),
            "station_name": clean(record.get("station_name"), 100), "point_code": clean(connector.get("public_code"), 50),
            "arrive_until": _local(record.get("expires_at")), "station_id": str(record.get("station_id") or "")}}

    async def _get_current_charging(self) -> dict:
        record = await _call(self.source.current_session)
        return {"session": compact_session(record) if record else None}

    async def _get_my_charging_history(self, limit: int = 5) -> dict:
        records = await _call(self.source.recent_sessions, limit) or []
        summary = await _call(self.source.month_summary) or {}
        sessions = [compact_session(r) for r in records[:limit]]
        costs = [s["cost_brl"] for s in sessions if s["cost_brl"]]
        return {
            "month": summary.get("month"), "month_sessions": summary.get("sessions_count"),
            "month_energy_kwh": round(float(summary.get("energy_wh") or 0) / 1000, 2) if summary else None,
            "month_estimated_cost_brl": _money(summary.get("estimated_cost")),
            "recent_sessions": sessions,
            "average_cost_recent_brl": round(sum(costs) / len(costs), 2) if costs else None,
        }

    async def _get_owner_indicators(self, days: int = 30) -> dict:
        if not self.owner:
            return {"error": "disponível somente para donos de posto"}
        stations = await _call(self.source.owner_stations) or []
        sessions = await _call(self.source.owner_sessions, self.now - timedelta(days=days)) or []
        indicators = owner_indicators(stations, sessions, now=self.now, days=days)
        indicators["sessions_by_hour"] = dict(list(indicators["sessions_by_hour"].items())[:24])
        return {**indicators, "base_recommendations": owner_recommendations(indicators)}

    async def _plan_driver_shift(self, args: dict) -> dict:
        if hasattr(self.source, "driver_stations"):
            stations = await _call(self.source.driver_stations) or []
        else:
            stations = await _call(self.source.list_stations, near=None, radius_km=None) or []
        saved = await _call(self.source.driver_profile) if hasattr(self.source, "driver_profile") else None
        try:
            result = await _call(self._planner, args, stations, self.now, saved)
        except Exception:  # noqa: BLE001 - o planejador não pode derrubar o chat
            return {"error": "planejador do modo motorista indisponível no momento"}
        return result if isinstance(result, dict) else {"result": result}
