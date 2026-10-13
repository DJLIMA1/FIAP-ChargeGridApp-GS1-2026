"""Indicadores e recomendações determinísticas (base factual para a IA e alternativa sem IA).

Entradas no formato REST: sessões de ``/v1/operator/charging-sessions`` ou
``/v1/me/charging-sessions`` e postos com ``connectors``. ``now`` é recebido
como argumento para manter as funções determinísticas.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..formatting import brl
from .stations import point_available

LOCAL_TZ = timezone(timedelta(hours=-3))  # America/Sao_Paulo (sem horário de verão desde 2019)
PEAK_HOURS = range(18, 21)  # horário de ponta das distribuidoras: 18h-21h
FINISHED = ("completed", "interrupted")
KINDS = ("pricing", "operations", "marketing")
IMPACTS = ("alto", "médio", "baixo")


def _date(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _minutes(session: dict) -> float:
    start, end = _date(session.get("started_at")), _date(session.get("ended_at"))
    if not start or not end or end < start:
        return 0.0
    return (end - start).total_seconds() / 60


def owner_indicators(stations: list[dict], sessions: list[dict], *, now: datetime, days: int = 30) -> dict:
    """Receita/energia estimadas, sessões por hora, ocupação e falhas dos postos do dono."""
    since = now - timedelta(days=days)
    point_station = {}
    per_station = {}
    for station in stations:
        sid = str(station.get("id"))
        points = station.get("connectors") or []
        per_station[sid] = {"station_id": sid, "name": str(station.get("name") or "")[:100],
                            "points": len(points), "offline_points": 0, "fault_points": 0,
                            "available_points": sum(point_available(p) for p in points),
                            "sessions": 0, "energy_kwh": 0.0, "revenue_brl": 0.0, "minutes": 0.0,
                            "price_per_kwh": [_float(p.get("price_per_kwh")) for p in points if p.get("price_per_kwh") is not None]}
        for point in points:
            point_station[str(point.get("id"))] = sid
            status = point.get("availability_status")
            if point.get("online") is False or status == "offline":
                per_station[sid]["offline_points"] += 1
            elif status == "fault":
                per_station[sid]["fault_points"] += 1
    by_hour = [0] * 24
    counts = {"completed": 0, "interrupted": 0, "failed": 0, "active": 0}
    energy = revenue = minutes = 0.0
    total = 0
    for session in sessions:
        created = _date(session.get("started_at") or session.get("created_at"))
        if not created or created < since or created > now + timedelta(minutes=5):
            continue
        total += 1
        status = session.get("status")
        counts[status if status in counts else "active"] += 1
        by_hour[created.astimezone(LOCAL_TZ).hour] += 1
        sid = str(session.get("station_id") or point_station.get(str(session.get("connector_id"))) or "")
        item = per_station.get(sid)
        if item:
            item["sessions"] += 1
        if status in FINISHED:
            kwh, cost, used = _float(session.get("energy_wh")) / 1000, _float(session.get("cost_estimate")), _minutes(session)
            energy, revenue, minutes = energy + kwh, revenue + cost, minutes + used
            if item:
                item["energy_kwh"] += kwh
                item["revenue_brl"] += cost
                item["minutes"] += used
    point_count = sum(item["points"] for item in per_station.values())
    capacity = point_count * days * 24 * 60
    stations_out = []
    for item in per_station.values():
        prices = item.pop("price_per_kwh")
        used = item.pop("minutes")
        capacity_station = item["points"] * days * 24 * 60
        stations_out.append({**item, "energy_kwh": round(item["energy_kwh"], 2), "revenue_brl": round(item["revenue_brl"], 2),
                             "occupancy_percent": round(100 * used / capacity_station, 1) if capacity_station else 0.0,
                             "avg_price_per_kwh": round(sum(prices) / len(prices), 2) if prices else None})
    finished = counts["completed"] + counts["interrupted"]
    busiest = sorted(range(24), key=lambda h: (-by_hour[h], h))
    return {
        "period_days": days, "stations": len(per_station), "points": point_count,
        "offline_points": sum(s["offline_points"] for s in stations_out),
        "fault_points": sum(s["fault_points"] for s in stations_out),
        "sessions": total, "completed": counts["completed"], "interrupted": counts["interrupted"],
        "failed": counts["failed"], "active": counts["active"],
        "failure_rate_percent": round(100 * (counts["failed"] + counts["interrupted"]) / total, 1) if total else 0.0,
        "energy_kwh": round(energy, 2), "revenue_brl": round(revenue, 2),
        "avg_ticket_brl": round(revenue / finished, 2) if finished else 0.0,
        "avg_price_per_kwh": round(revenue / energy, 2) if energy else None,
        "occupancy_percent": round(100 * minutes / capacity, 1) if capacity else 0.0,
        "sessions_by_hour": {str(h): by_hour[h] for h in range(24) if by_hour[h]},
        "peak_hours": [h for h in busiest[:3] if by_hour[h]],
        "peak_window_sessions": sum(by_hour[h] for h in PEAK_HOURS),
        "per_station": sorted(stations_out, key=lambda s: (-s["revenue_brl"], s["station_id"]))[:10],
        "source": "estimativas do ChargeGrid a partir das sessões registradas (energia simulada na bancada)",
    }


def _rec(title, detail, impact, kind):
    return {"title": title, "detail": detail, "impact": impact, "kind": kind}


def owner_recommendations(ind: dict) -> list[dict]:
    """Recomendações por regras explícitas; a IA reescreve/expande a partir destas."""
    recs = []
    if not ind["points"]:
        return [_rec("Vincule seu primeiro ponto", "Escaneie o QR de propriedade do equipamento para publicar o posto.",
                     "alto", "operations")]
    if ind["offline_points"] or ind["fault_points"]:
        recs.append(_rec("Recupere os pontos sem comunicação",
                         f"{ind['offline_points']} ponto(s) offline e {ind['fault_points']} com falha deixam de atender motoristas.",
                         "alto", "operations"))
    if ind["sessions"] and ind["failure_rate_percent"] >= 10:
        recs.append(_rec("Reduza interrupções",
                         f"{ind['failure_rate_percent']:.0f}% das sessões terminaram interrompidas ou com falha. Verifique cabo, rede e firmware.",
                         "alto", "operations"))
    if ind["sessions"] == 0:
        recs.append(_rec("Divulgue o posto", "Nenhuma recarga no período. Crie um cupom de boas-vindas e confira se o endereço está correto.",
                         "alto", "marketing"))
    elif ind["occupancy_percent"] < 15:
        quiet = [h for h in range(8, 22) if str(h) not in ind["sessions_by_hour"]]
        window = f"{quiet[0]}h–{quiet[0] + 3}h" if quiet else "horários de menor movimento"
        recs.append(_rec("Ocupe os horários ociosos",
                         f"Ocupação de {_num(ind['occupancy_percent'])}%. Um cupom de 10% em {window} pode atrair recargas sem reduzir a receita no pico.",
                         "médio", "pricing"))
    if ind["sessions"] and ind["peak_window_sessions"] / ind["sessions"] >= 0.4:
        recs.append(_rec("Valorize o horário de ponta",
                         "Boa parte das recargas acontece entre 18h e 21h. Avalie tarifa diferenciada ou reserva nesse horário.",
                         "médio", "pricing"))
    if ind["sessions"] and ind["avg_ticket_brl"] and ind["avg_ticket_brl"] < 10:
        recs.append(_rec("Aumente o ticket médio",
                         f"Ticket médio de {brl(ind['avg_ticket_brl'])}. Sugira recargas maiores com cupom progressivo ou parceria com comércio próximo.",
                         "baixo", "marketing"))
    if not recs:
        recs.append(_rec("Mantenha a operação", "Indicadores estáveis. Acompanhe semanalmente ocupação e falhas.", "baixo", "operations"))
    return recs[:5]


def owner_summary(ind: dict) -> str:
    if not ind["points"]:
        return "Você ainda não tem pontos publicados."
    return (f"Nos últimos {ind['period_days']} dias: {ind['sessions']} recarga(s), "
            f"{_num(ind['energy_kwh'])} kWh e {brl(ind['revenue_brl'])} estimados em {ind['stations']} posto(s). "
            f"Ocupação média de {_num(ind['occupancy_percent'])}%.")


def _num(value: float, digits: int = 1) -> str:
    return f"{float(value):.{digits}f}".replace(".", ",")


def session_facts(session: dict, history: list[dict]) -> dict:
    """Fatos comparáveis de uma sessão vs histórico do próprio usuário."""
    finished = [s for s in history if s.get("status") in FINISHED and _float(s.get("energy_wh")) > 0
                and s.get("id") != session.get("id")]
    cost, kwh = _float(session.get("cost_estimate")), _float(session.get("energy_wh")) / 1000
    start = _date(session.get("started_at") or session.get("created_at"))
    hour = start.astimezone(LOCAL_TZ).hour if start else None
    avg_cost = sum(_float(s.get("cost_estimate")) for s in finished) / len(finished) if finished else None
    energies = sum(_float(s.get("energy_wh")) for s in finished) / 1000
    avg_price = sum(_float(s.get("cost_estimate")) for s in finished) / energies if energies else None
    price = _float(session.get("price_per_kwh")) or (cost / kwh if kwh else None)
    return {
        "station_name": str(session.get("station_name") or "")[:100],
        "status": session.get("status"), "end_reason": session.get("end_reason"),
        "energy_kwh": round(kwh, 2), "cost_brl": round(cost, 2),
        "price_per_kwh": round(price, 2) if price else None,
        "discount_percent": session.get("discount_percent") or 0,
        "duration_minutes": round(_minutes(session)),
        "start_hour_local": hour, "peak_hour": hour in PEAK_HOURS if hour is not None else None,
        "history_sessions": len(finished),
        "avg_cost_brl": round(avg_cost, 2) if avg_cost is not None else None,
        "avg_price_per_kwh": round(avg_price, 2) if avg_price else None,
        "cost_vs_avg_percent": round(100 * (cost - avg_cost) / avg_cost) if avg_cost else None,
        "source": session.get("source") or "simulated",
    }


def session_tips(facts: dict) -> list[str]:
    tips = []
    if facts.get("peak_hour"):
        tips.append("Você recarregou no horário de ponta (18h–21h). Fora dele costuma haver menos fila; "
                    "se o posto adotar tarifa por horário, também sai mais barato.")
    if facts.get("avg_price_per_kwh") and facts.get("price_per_kwh") and facts["price_per_kwh"] > facts["avg_price_per_kwh"] * 1.1:
        tips.append(f"A tarifa desta recarga ({brl(facts['price_per_kwh'])}/kWh) ficou acima da sua média "
                    f"({brl(facts['avg_price_per_kwh'])}/kWh). Compare postos por menor tarifa antes de sair.")
    if not facts.get("discount_percent"):
        tips.append("Confira os cupons do posto antes de iniciar: um desconto de 10% já reduz o custo estimado.")
    if facts.get("status") == "interrupted":
        tips.append("A recarga foi interrompida. Se não foi você quem parou, verifique o cabo e informe o posto.")
    return tips[:3]


def session_summary(facts: dict) -> str:
    text = f"Recarga de {_num(facts['energy_kwh'], 2)} kWh por {brl(facts['cost_brl'])} (estimativa)"
    if facts.get("station_name"):
        text += f" no {facts['station_name']}"
    text += "."
    if facts.get("cost_vs_avg_percent") is not None:
        delta = facts["cost_vs_avg_percent"]
        text += (" Custo na sua média." if abs(delta) < 5 else
                 f" Custo {abs(delta)}% {'acima' if delta > 0 else 'abaixo'} da sua média de {brl(facts['avg_cost_brl'])}.")
    return text
