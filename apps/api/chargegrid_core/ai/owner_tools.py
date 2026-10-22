"""Ferramentas do dono de posto (mixin do ``Toolbox``), sobre os MESMOS serviços do dashboard.

A fonte implementa (API: ``owner/service``, ``economics``, ``forecast``; demo: ``demo_owner``)::

    owner_station_names() -> [{id, name}]
    owner_overview(start, end, station_id) / owner_ranking(start, end, station_id)
    owner_timeseries(start, end, granularity, station_id) / owner_heatmap(start, end, station_id)
    owner_alerts(station_id) / owner_live(station_id) / owner_forecast(station_id)
    owner_margin(start, end, station_id) / owner_coupons() / owner_session(session_id | None)

Escopo: a fonte só lê postos cujo dono é o usuário autenticado e levanta
``ToolDataError`` para qualquer outro. Aqui o posto citado (nome ou id) é resolvido
só entre os postos do próprio dono. Nenhuma saída traz identidade de motoristas.
Para o dono, efeitos de demanda aparecem normalmente.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta

from .. import analytics
from .periods import DATE_SCHEMA, PERIOD_SCHEMA, previous_period, resolve_period
from .schema import ToolDataError
from .text import clean, normalized

_STATION = {"type": "string", "minLength": 1, "maxLength": 100,
            "description": "Nome (ou id) de um posto seu; omita para todos os postos."}
_PERIOD = {"period": PERIOD_SCHEMA, "from_date": DATE_SCHEMA, "to_date": DATE_SCHEMA}
_ID = {"type": "string", "minLength": 1, "maxLength": 64}
METRICS = ("revenue", "energy_kwh", "sessions", "occupancy_percent")

OWNER_SPECS = {
    "get_owner_overview": {
        "description": ("KPIs dos seus postos num período (mesmos do painel): receita, energia, recargas, ticket médio, "
                        "ocupação, disponibilidade, reservas/no-show, falhas, com variação vs. período anterior."),
        "parameters": {"type": "object", "properties": {**_PERIOD, "station": _STATION}},
        "requires": ("owner_overview",),
    },
    "get_owner_timeseries": {
        "description": "Evolução de receita, energia e recargas por dia ou por hora (até 31 pontos; dias longos viram semanas).",
        "parameters": {"type": "object", "properties": {
            **_PERIOD, "station": _STATION, "granularity": {"type": "string", "enum": ["day", "hour"]}}},
        "requires": ("owner_timeseries",),
    },
    "get_owner_ranking": {
        "description": ("Ranking de carregadores (group_by=charger) ou postos (group_by=station) por receita, energia, "
                        "recargas ou ocupação: melhores (order=top) ou piores (order=bottom). Serve para comparar postos."),
        "parameters": {"type": "object", "properties": {
            **_PERIOD, "station": _STATION, "group_by": {"type": "string", "enum": ["charger", "station"]},
            "metric": {"type": "string", "enum": list(METRICS)}, "order": {"type": "string", "enum": ["top", "bottom"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10}}},
        "requires": ("owner_ranking",),
    },
    "get_peak_hours": {
        "description": "Horários e dias de maior e menor movimento (recargas iniciadas) nos seus postos.",
        "parameters": {"type": "object", "properties": {**_PERIOD, "station": _STATION}},
        "requires": ("owner_heatmap",),
    },
    "get_owner_alerts": {
        "description": "Alertas atuais: carregadores offline, falhas, comandos sem confirmação e pontos parados.",
        "parameters": {"type": "object", "properties": {"station": _STATION}},
        "requires": ("owner_alerts",),
    },
    "get_owner_live": {
        "description": "Situação agora de cada ponto: online, em recarga (energia, valor), reservado ou livre.",
        "parameters": {"type": "object", "properties": {"station": _STATION}},
        "requires": ("owner_live",),
    },
    "get_tariff_suggestions": {
        "description": ("Previsão de ocupação das próximas 36 h de UM posto (picos e horários vazios) com as sugestões "
                        "de tarifa do ChargeGrid e a demanda atual. Só explica: o dono aplica na tela Tarifas."),
        "parameters": {"type": "object", "properties": {"station": _STATION}},
        "requires": ("owner_forecast",),
    },
    "get_margin_report": {
        "description": ("Resultado financeiro: receita, descontos de cupom, taxa de permanência, comissão, custo da "
                        "energia, margem e efeito do preço dinâmico, total e por posto."),
        "parameters": {"type": "object", "properties": {**_PERIOD, "station": _STATION}},
        "requires": ("owner_margin",),
    },
    "get_coupon_performance": {
        "description": "Seus cupons (ativos/expirados) com recargas, desconto concedido e receita no período.",
        "parameters": {"type": "object", "properties": _PERIOD},
        "requires": ("owner_coupons", "owner_margin"),
    },
    "explain_owner_session": {
        "description": ("Explica uma recarga num posto seu (preço, demanda, cupom, permanência, pagamento, motivo do "
                        "fim). Sem session_id usa a mais recente."),
        "parameters": {"type": "object", "properties": {"session_id": _ID}},
        "requires": ("owner_session",),
    },
}
for _spec in OWNER_SPECS.values():
    _spec["roles"] = ("owner",)


async def _call(function, *args, **kwargs):
    result = function(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


def _num(value, digits=2):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _delta(now, before):
    now, before = _num(now), _num(before)
    if now is None or before is None or before == 0:
        return None
    return round(100 * (now - before) / before, 1)


def _local(value, fmt="%d/%m %H:%M"):
    moment = value if isinstance(value, datetime) else analytics.parse_time(value)
    return moment.astimezone(analytics.REPORT_TZ).strftime(fmt) if moment else None


KPI_KEYS = ("revenue", "energy_kwh", "sessions", "average_ticket", "occupancy_percent", "uptime_percent",
            "reservations", "no_show_percent", "interrupted_sessions", "failed_sessions", "active_sessions",
            "points", "points_online")
WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")


class OwnerTools:
    """Handlers ``_<nome>`` do dono; resolve postos só entre os do próprio usuário."""

    async def _station_id(self, station) -> str | None:
        if not station:
            return None
        names = await _call(self.source.owner_station_names) or []
        wanted = normalized(station)
        exact = next((s for s in names if str(s.get("id")) == str(station).strip()), None)
        match = exact or next((s for s in names if normalized(s.get("name")) == wanted), None) \
            or next((s for s in names if wanted and wanted in normalized(s.get("name"))), None)
        if not match:
            raise ToolDataError("posto não encontrado entre os seus postos")
        return str(match["id"])

    def _period(self, args, default="30d"):
        return resolve_period(args.get("period"), self.now, from_date=args.get("from_date"),
                              to_date=args.get("to_date"), default=default)

    async def _get_owner_overview(self, station=None, **args) -> dict:
        sid = await self._station_id(station)
        period = self._period(args)
        before = previous_period(period)
        now = await _call(self.source.owner_overview, period["start"], period["end"], sid) or {}
        old = await _call(self.source.owner_overview, before["start"], before["end"], sid) or {}
        kpis, old_kpis = now.get("kpis") or {}, old.get("kpis") or {}
        return {
            "period": period["label"], "compared_with": before["label"],
            "kpis": {key: kpis.get(key) for key in KPI_KEYS},
            "change_percent": {key: _delta(kpis.get(key), old_kpis.get(key))
                               for key in ("revenue", "energy_kwh", "sessions", "occupancy_percent")},
            "stations": now.get("stations"),
            "top_chargers": [{"station_name": clean(r.get("station_name"), 80), "point_code": r.get("public_code"),
                              "revenue": r.get("revenue"), "sessions": r.get("sessions")}
                             for r in (now.get("ranking") or [])[:3]],
            "basis": "receita e energia de recargas encerradas no período (como o painel)",
        }

    async def _get_owner_timeseries(self, station=None, granularity="day", **args) -> dict:
        sid = await self._station_id(station)
        period = self._period(args, default="7d" if granularity == "day" else "today")
        if granularity == "hour" and period["end"] - period["start"] > timedelta(days=2):
            granularity = "day"  # por hora só cabe até 2 dias nos 31 pontos da resposta
        data = await _call(self.source.owner_timeseries, period["start"], period["end"], granularity, sid) or {}
        series = data.get("series") or {}
        buckets = data.get("buckets") or []
        rows = [{"start": b, "revenue": float(series.get("revenue", [0] * len(buckets))[i] or 0),
                 "energy_kwh": float(series.get("energy_kwh", [0] * len(buckets))[i] or 0),
                 "sessions": int(series.get("sessions", [0] * len(buckets))[i] or 0)} for i, b in enumerate(buckets)]
        fmt = "%d/%m %Hh" if granularity == "hour" else "%d/%m"
        unit = granularity
        if len(rows) > 31:
            grouped = []
            for index in range(0, len(rows), 7):
                chunk = rows[index:index + 7]
                grouped.append({"start": chunk[0]["start"], "revenue": sum(r["revenue"] for r in chunk),
                                "energy_kwh": sum(r["energy_kwh"] for r in chunk),
                                "sessions": sum(r["sessions"] for r in chunk)})
            rows, unit = grouped, "week"
        return {"period": period["label"], "granularity": unit,
                "points": [{"from": _local(r["start"], fmt), "revenue": round(r["revenue"], 2),
                            "energy_kwh": round(r["energy_kwh"], 2), "sessions": r["sessions"]} for r in rows[-31:]],
                "totals": {"revenue": round(sum(r["revenue"] for r in rows), 2),
                           "energy_kwh": round(sum(r["energy_kwh"] for r in rows), 2),
                           "sessions": sum(r["sessions"] for r in rows)}}

    async def _get_owner_ranking(self, station=None, group_by="charger", metric="revenue", order="top", limit=5,
                                 **args) -> dict:
        sid = await self._station_id(station)
        period = self._period(args)
        rows = await _call(self.source.owner_ranking, period["start"], period["end"], sid) or []
        items = []
        if group_by == "station":
            stations: dict[str, dict] = {}
            for row in rows:
                entry = stations.setdefault(str(row.get("station_id")), {
                    "station_name": clean(row.get("station_name"), 80), "chargers": 0, "revenue": 0.0,
                    "energy_kwh": 0.0, "sessions": 0, "_occupancy": 0.0})
                entry["chargers"] += 1
                entry["revenue"] = round(entry["revenue"] + (_num(row.get("revenue")) or 0), 2)
                entry["energy_kwh"] = round(entry["energy_kwh"] + (_num(row.get("energy_kwh"), 3) or 0), 3)
                entry["sessions"] += int(row.get("sessions") or 0)
                entry["_occupancy"] += _num(row.get("occupancy_percent"), 1) or 0
            for entry in stations.values():
                entry["occupancy_percent"] = round(entry.pop("_occupancy") / entry["chargers"], 1)
                items.append(entry)
        else:
            items = [{"station_name": clean(r.get("station_name"), 80), "point_code": clean(r.get("public_code"), 50),
                      "revenue": _num(r.get("revenue")) or 0.0, "energy_kwh": _num(r.get("energy_kwh"), 3) or 0.0,
                      "sessions": int(r.get("sessions") or 0),
                      "occupancy_percent": _num(r.get("occupancy_percent"), 1) or 0.0} for r in rows]
        items.sort(key=lambda item: (item[metric], item["sessions"]), reverse=order == "top")
        return {"period": period["label"], "group_by": group_by, "metric": metric, "order": order,
                "total_items": len(items), "items": items[:limit]}

    async def _get_peak_hours(self, station=None, **args) -> dict:
        sid = await self._station_id(station)
        period = self._period(args)
        data = await _call(self.source.owner_heatmap, period["start"], period["end"], sid) or {}
        cells = data.get("cells") or []
        by_hour = [sum(row[h] for row in cells) for h in range(24)] if cells else [0] * 24
        by_day = [sum(row) for row in cells] if cells else [0] * 7
        total = sum(by_hour)
        busiest = sorted((h for h in range(24) if by_hour[h]), key=lambda h: (-by_hour[h], h))[:3]
        quiet = sorted(range(8, 22), key=lambda h: (by_hour[h], h))[:3]
        return {"period": period["label"], "sessions": total,
                "peak_hours": [{"hour": f"{h}h", "sessions": by_hour[h]} for h in busiest],
                "quiet_daytime_hours": [{"hour": f"{h}h", "sessions": by_hour[h]} for h in quiet],
                "busiest_weekday": WEEKDAYS[max(range(7), key=lambda d: by_day[d])] if total else None,
                "evening_peak_share_percent": round(100 * sum(by_hour[18:21]) / total, 1) if total else None,
                "basis": "início das recargas, horário de Brasília"}

    async def _get_owner_alerts(self, station=None) -> dict:
        sid = await self._station_id(station)
        data = await _call(self.source.owner_alerts, sid) or {}
        items = data.get("items") or []
        counts: dict[str, int] = {}
        for item in items:
            counts[item.get("kind") or "outro"] = counts.get(item.get("kind") or "outro", 0) + 1
        return {"total": len(items), "by_kind": counts,
                "items": [{"severity": a.get("severity"), "title": clean(a.get("title"), 60),
                           "detail": clean(a.get("detail"), 160), "station_name": clean(a.get("station_name"), 80),
                           "point_code": clean(a.get("public_code"), 50)} for a in items[:12]]}

    async def _get_owner_live(self, station=None) -> dict:
        sid = await self._station_id(station)
        data = await _call(self.source.owner_live, sid) or {}
        points = []
        for item in (data.get("items") or [])[:20]:
            session = item.get("session") or {}
            # ``occupancy`` traz o rótulo do motorista (nome/veículo): só a taxa sai daqui, sem identidade.
            occupancy = item.get("occupancy") or {}
            points.append({
                "station_name": clean(item.get("station_name"), 80), "point_code": clean(item.get("public_code"), 50),
                "online": item.get("online"), "state": item.get("availability_status") or item.get("physical_state"),
                "charging": bool(session) and session.get("status") in ("starting", "charging", "stopping"),
                "energy_kwh": _num((_num(session.get("energy_wh"), 3) or 0) / 1000) if session else None,
                "cost_brl": _num(session.get("cost_estimate")) if session else None,
                "started_at": _local(session.get("started_at")) if session else None,
                "reserved_until": _local(item.get("reserved_until")),
                "overstay": {"status": occupancy.get("status"), "billable_minutes": occupancy.get("billable_minutes"),
                             "fee_due": occupancy.get("fee_due")} if occupancy else None,
            })
        return {"points": points, "charging_now": sum(p["charging"] for p in points),
                "offline": sum(p["online"] is False for p in points), "as_of": _local(data.get("generated_at"))}

    async def _get_tariff_suggestions(self, station=None) -> dict:
        sid = await self._station_id(station)
        if sid is None:
            names = await _call(self.source.owner_station_names) or []
            if len(names) != 1:
                return {"error": "informe qual posto (a previsão é por posto)",
                        "your_stations": [clean(s.get("name"), 80) for s in names[:10]]}
            sid = str(names[0]["id"])
        data = await _call(self.source.owner_forecast, sid) or {}
        station_row = await _call(self.source.get_station, sid) if hasattr(self.source, "get_station") else None
        demand = (station_row or {}).get("demand") or {}
        accuracy = data.get("accuracy") or {}
        return {
            "station_id": sid, "station_name": clean((station_row or {}).get("name"), 80) or None,
            "status": data.get("status"), "method": data.get("method"), "accuracy_status": accuracy.get("status"),
            "includes_synthetic_history": data.get("includes_synthetic"),
            "peaks": [clean(p.get("label"), 80) for p in (data.get("peaks") or [])[:3]],
            "idle": [clean(p.get("label"), 80) for p in (data.get("idle") or [])[:3]],
            "suggestions": [{"kind": s.get("kind"), "title": clean(s.get("title"), 80), "detail": clean(s.get("detail"), 260),
                             "price_preview": [{"point_code": p.get("public_code"), "from": p.get("from"), "to": p.get("to")}
                                               for p in ((s.get("action") or {}).get("preview") or [])[:4]]}
                            for s in (data.get("suggestions") or [])[:3]],
            "demand_now": {key: demand.get(key) for key in ("multiplier", "level_label", "increase_percent", "reason_label")
                           if demand.get(key) is not None},
            "notes": [clean(n, 160) for n in (data.get("notes") or [])[:2]],
            "how_to_apply": "Abra Tarifas do posto para revisar e aplicar; o assistente não altera tarifas.",
        }

    async def _get_margin_report(self, station=None, **args) -> dict:
        sid = await self._station_id(station)
        period = self._period(args)
        report = await _call(self.source.owner_margin, period["start"], period["end"], sid) or {}
        totals = report.get("totals") or {}
        keep = ("sessions", "energy_kwh", "gross", "discount", "revenue", "overstay_revenue", "revenue_total",
                "platform_fee", "provider_fee", "owner_net", "energy_cost", "margin", "margin_percent")
        return {
            "period": period["label"], "totals": {key: totals.get(key) for key in keep if key in totals},
            "dynamic_pricing": report.get("dynamic_pricing"), "coupons": report.get("coupons"),
            "by_station": [{"station_name": clean(s.get("station_name"), 80), "sessions": s.get("sessions"),
                            "revenue_total": s.get("revenue_total"), "margin": s.get("margin"),
                            "overstay_revenue": s.get("overstay_revenue")} for s in (report.get("by_station") or [])[:10]],
            "warnings": [clean(w, 200) for w in (report.get("warnings") or [])[:3]],
        }

    async def _get_coupon_performance(self, **args) -> dict:
        period = self._period(args)
        coupons = await _call(self.source.owner_coupons) or []
        report = await _call(self.source.owner_margin, period["start"], period["end"], None) or {}
        usage: dict[str, dict] = {}
        for row in report.get("items") or []:
            code = row.get("coupon_code")
            if not code:
                continue
            entry = usage.setdefault(code, {"sessions": 0, "discount_brl": 0.0, "revenue_brl": 0.0})
            entry["sessions"] += 1
            entry["discount_brl"] = round(entry["discount_brl"] + (_num(row.get("discount")) or 0), 2)
            entry["revenue_brl"] = round(entry["revenue_brl"] + (_num(row.get("revenue")) or 0), 2)
        items = []
        for coupon in coupons[:20]:
            code = clean(coupon.get("code"), 50)
            expires = analytics.parse_time(coupon.get("valid_until"))
            items.append({"code": code, "description": clean(coupon.get("description"), 80),
                          "discount_percent": coupon.get("discount_percent"),
                          "active": bool(coupon.get("active")) and bool(expires and expires > self.now),
                          "valid_until": _local(expires, "%d/%m/%Y"),
                          **usage.get(coupon.get("code"), {"sessions": 0, "discount_brl": 0.0, "revenue_brl": 0.0})})
        items.sort(key=lambda c: -c["sessions"])
        return {"period": period["label"], "coupons": items,
                "sessions_with_coupon": sum(u["sessions"] for u in usage.values()),
                "total_discount_brl": round(sum(u["discount_brl"] for u in usage.values()), 2)}

    async def _explain_owner_session(self, session_id: str | None = None) -> dict:
        receipt = await _call(self.source.owner_session, session_id)
        if not receipt:
            return {"error": "recarga não encontrada nos seus postos"}
        price, charges, times = receipt.get("price") or {}, receipt.get("charges") or {}, receipt.get("times") or {}
        energy, point, overstay = receipt.get("energy") or {}, receipt.get("point") or {}, receipt.get("overstay") or {}
        payment = receipt.get("payment") or {}
        return {
            "session_id": str(receipt.get("session_id") or ""),
            "station_name": clean((receipt.get("station") or {}).get("name"), 100),
            "point_code": clean(point.get("public_code"), 50), "status": times.get("status_label"),
            "end_reason": times.get("end_reason_label"), "started_at": _local(times.get("started_at")),
            "ended_at": _local(times.get("ended_at")), "duration_minutes": times.get("duration_minutes"),
            "energy_kwh": energy.get("kwh"), "measurement": energy.get("source_label"),
            "price_explanation": [clean(line, 200) for line in (price.get("explanation") or [])[:6]],
            "demand": price.get("demand"), "charges": {key: charges.get(key) for key in (
                "energy_gross", "discount", "energy_total", "overstay", "total", "paid_total") if charges.get(key)},
            "overstay": {key: overstay.get(key) for key in ("status", "billable_minutes", "fee_due", "end_reason")
                         if overstay.get(key) is not None} if overstay.get("status") == "available" else None,
            "payment": {"method": payment.get("method"), "status": payment.get("status_label")}
            if payment.get("status") == "available" else None,
        }
