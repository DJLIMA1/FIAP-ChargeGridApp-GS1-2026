"""Ações sugeridas (botões) derivadas de forma determinística dos dados consultados.

A IA nunca executa ações com efeito; o app mostra estes botões e segue o fluxo
normal com confirmação. Só usamos ids que vieram das ferramentas nesta rodada,
então texto malicioso não consegue inventar destinos.
"""

from __future__ import annotations

from .text import normalized

ACTION_TYPES = ("open_station", "reserve", "open_reservation", "open_charging", "open_history",
                "open_operator", "search_stations", "open_driver")
MAX_ACTIONS = 3


def _station_actions(stations: list[dict], reply: str, *, reserve: bool) -> list[dict]:
    text = normalized(reply)
    mentioned = [s for s in stations if s.get("name") and normalized(s["name"]) in text]
    chosen = mentioned or stations[:2]
    actions = []
    for station in chosen[:2]:
        actions.append({"type": "open_station", "station_id": station["station_id"], "label": f"Ver {station['name']}"[:60]})
        if reserve:
            point = next((p for p in station.get("points") or [] if p.get("available_now")), None)
            if point:
                actions.append({"type": "reserve", "station_id": station["station_id"],
                                "connector_id": point["connector_id"], "label": f"Reservar {point['code']}"[:60]})
    return actions


def derive_actions(records: list[tuple[str, dict, dict]], reply: str, user_text: str = "") -> list[dict]:
    reserve = "reserv" in normalized(user_text)
    actions: list[dict] = []
    for name, _args, data in records:
        if not isinstance(data, dict) or data.get("error"):
            continue
        if name == "search_stations":
            actions += _station_actions(data.get("stations") or [], reply, reserve=reserve)
        elif name == "get_station_details" and data.get("station_id"):
            actions += _station_actions([data], reply, reserve=True)
        elif name == "estimate_charge" and data.get("station_id"):
            actions.append({"type": "open_station", "station_id": data["station_id"],
                            "label": f"Ver {data.get('station_name') or 'posto'}"[:60]})
        elif name == "get_my_reservation":
            actions.append({"type": "open_reservation", "label": "Abrir minha reserva"} if data.get("reservation")
                           else {"type": "search_stations", "label": "Encontrar um ponto"})
        elif name == "get_current_charging" and data.get("session"):
            actions.append({"type": "open_charging", "session_id": data["session"]["session_id"],
                            "label": "Abrir minha recarga"})
        elif name == "get_my_charging_history":
            actions.append({"type": "open_history", "label": "Ver meu histórico"})
        elif name == "get_owner_indicators":
            actions.append({"type": "open_operator", "label": "Abrir meus postos"})
        elif name == "plan_driver_shift":
            actions.append({"type": "open_driver", "label": "Abrir modo motorista"})
    unique, seen = [], set()
    for action in actions:
        key = (action["type"], action.get("station_id"), action.get("connector_id"), action.get("session_id"))
        if key not in seen:
            seen.add(key)
            unique.append(action)
    return unique[:MAX_ACTIONS]
