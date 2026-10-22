"""Ferramentas do motorista com o carro e a conta do usuário (mixin do ``Toolbox``).

Toda conta vem do núcleo: ``estimates.estimate_charge`` (energia/tempo/custo),
``charge_plan.autonomy_energy`` (alvo em km) e ``power.car_limit`` (limite AC/DC do
carro). O modelo só escolhe o alvo; bateria, SoC e tarifa vêm do cadastro e dos postos.

Demanda: o motorista vê só o preço final por kWh. Nenhuma saída daqui traz
multiplicador, acréscimo ou "ajuste por demanda" (dado interno do dono).
"""

from __future__ import annotations

import inspect
from datetime import datetime

from .. import analytics
from ..charge_plan import autonomy_energy
from ..formatting import brl, duration, kwh
from .context import stations_by_id
from .estimates import EstimateError, estimate_charge
from .periods import DATE_SCHEMA, PERIOD_SCHEMA, resolve_period
from .places import resolve_place
from .stations import compact_station, filter_stations, normalize_connector
from .text import clean, normalized
from .vehicle import accepts, car_power_limit

LOSSES_NOTE = ("Energia que entra na bateria; o medidor do carregador costuma registrar cerca de 10% a mais "
               "(perdas na recarga), então o valor cobrado pode ficar um pouco acima.")
NEARBY_RADIUS_KM = 15.0
_ID = {"type": "string", "minLength": 1, "maxLength": 64}
_TARGET = {
    "energy_kwh": {"type": "number", "minimum": 0.1, "maximum": 300},
    "battery_kwh": {"type": "number", "minimum": 5, "maximum": 300,
                    "description": "Só se o usuário citar outro carro; o padrão é o carro cadastrado."},
    "from_percent": {"type": "number", "minimum": 0, "maximum": 100,
                     "description": "Bateria inicial %. Omita para usar o nível estimado pelo app."},
    "to_percent": {"type": "number", "minimum": 1, "maximum": 100, "description": "Bateria final % (padrão 80)."},
    "km": {"type": "number", "minimum": 1, "maximum": 2000, "description": "Autonomia desejada em km."},
    "budget_brl": {"type": "number", "minimum": 1, "maximum": 5000},
    "minutes": {"type": "number", "minimum": 1, "maximum": 1440},
}

DRIVER_SPECS = {
    "estimate_charge": {
        "description": ("Estima energia, tempo e custo de uma recarga com o CARRO CADASTRADO do usuário (bateria e "
                        "limite AC/DC já conhecidos) e o preço final do ponto. Alvos: faixa de bateria "
                        "(from_percent/to_percent), km de autonomia, energy_kwh, budget_brl ou minutes. Sem "
                        "connector_id/station_id, compara o posto que o usuário mais usa com o mais barato perto. "
                        "Nunca peça a capacidade da bateria se o carro está no cartão DADOS DA CONTA."),
        "parameters": {"type": "object", "properties": {
            "connector_id": _ID, "station_id": _ID,
            "power_kw": {"type": "number", "minimum": 0.5, "maximum": 1000},
            "price_per_kwh": {"type": "number", "minimum": 0, "maximum": 100}, **_TARGET}},
        "roles": ("driver", "legacy"),
    },
    "compare_charge_options": {
        "description": ("Compara custo e tempo do MESMO alvo de recarga (faixa de bateria, km ou kWh) em até 5 postos "
                        "perto do usuário (ou de near_place) e nos que ele mais usa, com o carro cadastrado."),
        "parameters": {"type": "object", "properties": {
            **{k: v for k, v in _TARGET.items() if k not in ("budget_brl", "minutes")},
            "near_place": {"type": "string", "maxLength": 80},
            "connector_type": {"type": "string", "maxLength": 20},
            "sort": {"type": "string", "enum": ["price", "time"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 5}}},
        "roles": ("driver",),
    },
    "get_station_best_times": {
        "description": ("Melhor horário para carregar mais barato ou com menos movimento num posto nas próximas 12 h "
                        "(preço final previsto por hora). Use station_id do cartão ou de uma busca."),
        "parameters": {"type": "object", "properties": {"station_id": _ID}, "required": ["station_id"]},
        "roles": ("driver",), "requires": ("station_best_times",),
    },
    "explain_my_session": {
        "description": ("Explica uma recarga do próprio usuário como no recibo: preço travado por kWh, desconto/cupom, "
                        "taxa de permanência, pagamento e total. Sem session_id usa a última concluída "
                        "(which=current para a recarga em andamento)."),
        "parameters": {"type": "object", "properties": {
            "session_id": _ID, "which": {"type": "string", "enum": ["last", "current"]}}},
        "roles": ("driver",), "requires": ("session_receipt",),
    },
    "get_my_wallet": {
        "description": "Saldo e últimas movimentações da carteira simulada do usuário (sem dinheiro real).",
        "parameters": {"type": "object", "properties": {}},
        "roles": ("driver",), "requires": ("wallet",),
    },
}

HISTORY_PERIOD_PROPS = {"period": PERIOD_SCHEMA, "from_date": DATE_SCHEMA, "to_date": DATE_SCHEMA}


async def _call(function, *args, **kwargs):
    result = function(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _money(value):
    number = _float(value)
    return round(number, 2) if number is not None else None


def _local(value, fmt="%d/%m %H:%M"):
    moment = analytics.parse_time(value) if not isinstance(value, datetime) else value
    return moment.astimezone(analytics.REPORT_TZ).strftime(fmt) if moment else None


def _hhmm(value):
    return _local(value, "%H:%M")


def summary_line(item: dict) -> str:
    """Frase pronta em pt-BR (o modelo pode citar sem refazer contas)."""
    where = item.get("station_name")
    code = f" ({item['point_code']}, {str(item['power_used_kw']).replace('.', ',')} kW)" \
        if item.get("point_code") and item.get("power_used_kw") else ""
    price = f" a {brl(item['price_per_kwh'])}/kWh" if item.get("price_per_kwh") is not None else ""
    text = f"{kwh(item['energy_kwh'])} ≈ {brl(item['cost_brl'])} em ~{duration(item['minutes'])}"
    return text + (f" no {where}{code}" if where else "") + price


def driver_receipt_view(receipt: dict) -> dict:
    """Recibo do motorista sem nenhum dado de demanda (só o preço travado e os totais)."""
    price, charges = receipt.get("price") or {}, receipt.get("charges") or {}
    times, energy = receipt.get("times") or {}, receipt.get("energy") or {}
    point, payment = receipt.get("point") or {}, receipt.get("payment") or {}
    overstay = receipt.get("overstay") or {}
    coupon = price.get("coupon") or {}
    view = {
        "session_id": str(receipt.get("session_id") or ""),
        "final": bool(receipt.get("final")),
        "station_name": clean((receipt.get("station") or {}).get("name"), 100),
        "point_code": clean(point.get("public_code"), 50), "connector_type": point.get("connector_type"),
        "status": times.get("status_label"), "end_reason": times.get("end_reason_label"),
        "started_at": _local(times.get("started_at") or times.get("created_at")),
        "ended_at": _local(times.get("ended_at")), "duration_minutes": _float(times.get("duration_minutes")),
        "energy_kwh": _float(energy.get("kwh")), "battery_start_percent": _float(energy.get("soc_start")),
        "battery_end_percent": _float(energy.get("soc_end")),
        "locked_price_per_kwh": _float(price.get("price_per_kwh")),
        "price_locked_on": "na reserva" if price.get("locked_by") == "reservation" else "no início da recarga",
        "speed": price.get("power_tier_label"),
        "charges_brl": {key: _money(charges.get(key)) for key in (
            "energy_gross", "discount", "energy_total", "overstay", "total", "paid_total") if charges.get(key) is not None},
        "charges_note": clean(charges.get("note"), 200) or None,
        "measurement": (receipt.get("labels") or {}).get("measurement_label"),
    }
    if coupon.get("discount_percent"):
        view["coupon"] = {"code": clean(coupon.get("code"), 50) or None, "discount_percent": coupon["discount_percent"]}
    if overstay.get("status") == "available":
        view["overstay"] = {key: overstay.get(key) for key in ("status", "billable_minutes", "fee_due", "max_fee")
                            if overstay.get(key) is not None}
    if payment.get("status") == "available":
        view["payment"] = {"method": payment.get("method"), "status": payment.get("status_label"),
                           "environment": payment.get("environment")}
    return view


class DriverTools:
    """Handlers ``_<nome>`` do motorista; usa ``self.source/context/origin/now`` do ``Toolbox``."""

    # ------------------------------------------------------------ carro e alvo
    def _car(self) -> dict | None:
        return (self.context or {}).get("car")

    def _soc_now(self) -> dict | None:
        return (self.context or {}).get("battery_now")

    def _target(self, args: dict) -> tuple[dict, list[str]]:
        """Argumentos de ``estimate_charge`` + premissas, preenchendo bateria e SoC do cartão."""
        car, notes = self._car(), []
        target = {k: args[k] for k in ("energy_kwh", "budget_brl", "minutes") if args.get(k) is not None}
        if target:
            return target, notes
        battery = args.get("battery_kwh")
        if battery is None and car:
            battery = car["usable_battery_kwh"]
            notes.append(f"Bateria útil do {car['name']}" + (" cadastrado" if car.get("registered") else
                         " (carro padrão; cadastre o seu no Perfil)") + f": {kwh(battery)}.")
        start = args.get("from_percent")
        if start is None and self._soc_now():
            soc = self._soc_now()
            start = soc["percent"]
            notes.append(f"Bateria inicial: {soc['percent']:.0f}% ({soc['label']}).")
        if args.get("km") is not None:
            if not car:
                raise EstimateError("informe o consumo do carro para estimar por km")
            result = autonomy_energy(args["km"], car["consumption_kwh_per_100km"], start or 0, battery)
            notes.append(f"{int(args['km'])} km com consumo de {car['consumption_kwh_per_100km']} kWh/100 km.")
            if result["capped"]:
                notes.append(f"A bateria só comporta cerca de {result['km']} km agora.")
            if result["energy_kwh"] <= 0:
                raise EstimateError("a bateria já está cheia")
            return {"energy_kwh": float(result["energy_kwh"])}, notes
        end = args.get("to_percent")
        if start is not None and end is None:
            end = 80.0
            notes.append("Bateria final não informada: considerei 80%.")
        if start is None and end is not None:
            raise EstimateError("informe a bateria inicial (from_percent)")
        if start is not None and end is not None and battery:
            if start >= end:
                raise EstimateError("a bateria final deve ser maior que a inicial")
            return {"battery_kwh": float(battery), "from_percent": float(start), "to_percent": float(end)}, notes
        raise EstimateError("informe faixa de bateria, km, energia, orçamento ou tempo")

    def _at_point(self, point: dict, target: dict, notes: list[str]) -> dict:
        """Estimativa num ponto compacto (``power_kw``, ``price_per_kwh``, ``connector_type``)."""
        power = _float(point.get("power_kw")) or 0
        limit = car_power_limit(self._car(), point.get("connector_type"))
        used = min(power, limit) if limit else power
        extra = list(notes)
        if limit and limit < power:
            extra.append(f"O carro aceita até {str(limit).replace('.', ',')} kW neste conector "
                         f"(o ponto tem {str(power).replace('.', ',')} kW).")
        price = point.get("price_per_kwh")
        result = estimate_charge(used, float(price) if price is not None else -1,
                                 max_minutes=point.get("max_duration_minutes"), **target)
        item = {"station_id": point.get("station_id"), "station_name": point.get("station_name"),
                "point_code": point.get("code"), "connector_type": point.get("connector_type"),
                "power_kw": power, "power_used_kw": round(used, 1), "price_per_kwh": price, **result,
                "assumptions": extra + result["assumptions"] + [LOSSES_NOTE]}
        item["resumo"] = summary_line(item)
        return item

    def _best_at_station(self, station: dict, target: dict, notes: list[str], *, connector_type=None,
                         sort="price") -> dict | None:
        """Estima em cada ponto compatível do posto e escolhe: primeiro os que entregam o alvo inteiro
        dentro do tempo máximo, depois o mais barato (``price``) ou o mais rápido (``time``)."""
        wanted = normalize_connector(connector_type) if connector_type else None
        points = [p for p in station.get("points") or [] if p.get("status") != "disabled"
                  and p.get("price_per_kwh") is not None and accepts(self._car(), p.get("connector_type"))
                  and (wanted is None or normalize_connector(p.get("connector_type")) == wanted)]
        ready = [p for p in points if p.get("available_now")] or points
        estimates = []
        for point in ready:
            try:
                estimates.append(self._at_point({**point, "station_id": station["station_id"],
                                                 "station_name": station["name"]}, target, notes))
            except EstimateError:
                continue
        if not estimates:
            return None
        full = [e for e in estimates if not any(a.startswith("Limitado ao tempo") for a in e["assumptions"])]
        pool = full or estimates
        if sort == "time":
            return min(pool, key=lambda e: (e["minutes"], e["cost_brl"]))
        return min(pool, key=lambda e: (e["cost_brl"], e["minutes"]))

    async def _candidate_stations(self, near_place=None, connector_type=None) -> tuple[list[dict], str]:
        place = resolve_place(near_place) if near_place else None
        near = {"lat": place["lat"], "lng": place["lng"]} if place else self.origin
        stations = await _call(self.source.list_stations, near=near,
                               radius_km=NEARBY_RADIUS_KM if near else None) or []
        filters = {"sort": "price", **({"connector_type": connector_type} if connector_type else {})}
        if near:
            filters.update(near=near, radius_km=NEARBY_RADIUS_KM)
        found, _ = filter_stations(stations, filters, origin=near, limit=5)
        label = (f"mais barato perto de {clean(near_place, 40)}" if place else
                 "mais barato perto de você" if near else "mais barato da rede (sem sua localização)")
        return found, label

    async def _frequent(self) -> list[dict]:
        frequent = (self.context or {}).get("frequent_stations") or []
        rows = await stations_by_id(self.source, [f["station_id"] for f in frequent])
        return [compact_station(rows[f["station_id"]], origin=self.origin) for f in frequent if f["station_id"] in rows]

    async def _options(self, args: dict, *, near_place=None, connector_type=None, sort="price", limit=2) -> dict:
        target, notes = self._target(args)
        specs = self._car()
        options, seen = [], set()
        for station in (await self._frequent())[:1 if limit <= 2 else 3]:
            best = self._best_at_station(station, target, notes, connector_type=connector_type, sort=sort)
            if best and station["station_id"] not in seen:
                self._remember(station)
                seen.add(station["station_id"])
                options.append({**best, "why": "posto que você mais usa"})
        nearby, label = await self._candidate_stations(near_place, connector_type)
        for station in nearby:
            if len(options) >= max(limit, 2) or station["station_id"] in seen:
                continue
            best = self._best_at_station(station, target, notes, connector_type=connector_type, sort=sort)
            if best:
                self._remember(station)
                seen.add(station["station_id"])
                options.append({**best, "why": label,
                                **({"distance_km": station["distance_km"]} if "distance_km" in station else {})})
        if not options:
            return {"error": "nenhum posto compatível com o seu carro encontrado; informe um lugar ou outro conector"}
        key = (lambda o: o["minutes"]) if sort == "time" else (lambda o: o["cost_brl"])
        if sort == "time" or len(options) > 2:
            options.sort(key=key)
        for option in options:
            option["assumptions"] = [a for a in option["assumptions"] if a not in notes and a != LOSSES_NOTE]
        return {"car": (specs or {}).get("name"), "assumptions": notes + [LOSSES_NOTE], "options": options[:limit],
                "resumo": " | ".join(f"{o['why']}: {o['resumo']}" for o in options[:limit])}

    # ------------------------------------------------------------- ferramentas
    async def _estimate_charge(self, connector_id: str | None = None, station_id: str | None = None,
                               power_kw=None, price_per_kwh=None, **args) -> dict:
        if connector_id:
            point = self._points.get(connector_id)
            if point is None and hasattr(self.source, "get_connector"):
                point = await _call(self.source.get_connector, connector_id)
            if not point:
                return {"error": "ponto não encontrado; busque o posto antes ou informe potência e tarifa"}
            target, notes = self._target(args)
            return self._at_point(point, target, notes)
        if station_id:
            station = await _call(self.source.get_station, station_id)
            if not station:
                return {"error": "posto não encontrado"}
            compact = compact_station(station, origin=self.origin)
            self._remember(compact)
            target, notes = self._target(args)
            best = self._best_at_station(compact, target, notes)
            return best or {"error": "o posto não tem ponto compatível com o seu carro"}
        if power_kw is not None and price_per_kwh is not None:
            target, notes = self._target(args)
            result = estimate_charge(float(power_kw), float(price_per_kwh), **target)
            item = {"power_kw": power_kw, "power_used_kw": power_kw, "price_per_kwh": price_per_kwh, **result,
                    "assumptions": notes + result["assumptions"] + [LOSSES_NOTE]}
            item["resumo"] = summary_line(item)
            return item
        return await self._options(args, limit=2)

    async def _compare_charge_options(self, near_place=None, connector_type=None, sort="price", limit=3,
                                      **args) -> dict:
        return await self._options(args, near_place=near_place, connector_type=connector_type, sort=sort,
                                   limit=limit)

    async def _get_station_best_times(self, station_id: str) -> dict:
        data = await _call(self.source.station_best_times, station_id)
        if not data:
            return {"error": "posto não encontrado"}
        best = data.get("best") or {}
        reason = clean(best.get("reason"), 80)
        if "demanda" in normalized(reason) or "pico" in normalized(reason):
            reason = "Preço menor previsto"
        known = self._points and next((p["station_name"] for p in self._points.values()
                                      if p.get("station_id") == station_id), None)
        frequent = next((f["name"] for f in (self.context or {}).get("frequent_stations") or []
                         if f["station_id"] == station_id), None)
        return {
            "station_id": station_id, "station_name": known or frequent,
            "best_window": (f"{_local(best.get('start'), '%d/%m')} {_hhmm(best.get('start'))}–{_hhmm(best.get('end'))}"
                            if best else None),
            "best_price_per_kwh": _float(best.get("price_from")), "saving_vs_now_percent": best.get("saving_vs_now_percent"),
            "why": reason or None, "movement": best.get("level_label"),
            "price_now_per_kwh": _float((data.get("now") or {}).get("price_per_kwh")),
            "next_hours": [{"hour": _hhmm(h.get("start")), "price_per_kwh": _float(h.get("expected_price_per_kwh")),
                            "movement": h.get("level_label")} for h in (data.get("hours") or [])[:12]],
            "note": "Estimativa; o preço é travado quando você reserva ou inicia a recarga.",
        }

    async def _explain_my_session(self, session_id: str | None = None, which: str = "last") -> dict:
        if not session_id and which == "current":
            current = await _call(self.source.current_session)
            if not current:
                return {"session": None, "note": "nenhuma recarga em andamento"}
            session_id = str(current.get("id"))
        receipt = await _call(self.source.session_receipt, session_id)
        if not receipt:
            return {"error": "recarga não encontrada" if session_id else "você ainda não tem recargas concluídas"}
        return driver_receipt_view(receipt)

    async def _get_my_wallet(self) -> dict:
        wallet = await _call(self.source.wallet) or {}
        items = list(wallet.get("transactions") or [])[-5:][::-1]
        return {"balance_brl": _money(wallet.get("balance")), "simulated": True,
                "recent": [{"title": clean(t.get("title"), 60), "kind": "entrada" if t.get("kind") == "credit" else "saída",
                            "amount_brl": _money(t.get("amount")), "date": _local(t.get("created_at"), "%d/%m")}
                           for t in items if isinstance(t, dict)],
                "note": "Carteira simulada: nenhum dinheiro real."}

    async def period_history(self, period: str | None, from_date=None, to_date=None) -> dict:
        window = resolve_period(period, self.now, from_date=from_date, to_date=to_date, default="month")
        records = await _call(self.source.recent_sessions, 100) or []
        chosen = []
        for record in records:
            moment = analytics.parse_time(record.get("ended_at") or record.get("started_at") or record.get("created_at"))
            if moment and window["start"] <= moment < window["end"] and record.get("status") in ("completed", "interrupted"):
                chosen.append(record)
        energy = sum((_float(r.get("energy_wh")) or 0) for r in chosen) / 1000
        cost = sum((_float(r.get("cost_estimate")) or 0) for r in chosen)
        stations: dict[str, dict] = {}
        overstay = 0.0
        for record in chosen:
            key = clean(record.get("station_name"), 80) or "posto"
            entry = stations.setdefault(key, {"station_name": key, "sessions": 0, "cost_brl": 0.0, "energy_kwh": 0.0})
            entry["sessions"] += 1
            entry["cost_brl"] = round(entry["cost_brl"] + (_float(record.get("cost_estimate")) or 0), 2)
            entry["energy_kwh"] = round(entry["energy_kwh"] + (_float(record.get("energy_wh")) or 0) / 1000, 2)
            overstay += _float(((record.get("overstay") or {}).get("fee_due"))) or 0
        return {"period": window["label"], "sessions": len(chosen), "energy_kwh": round(energy, 2),
                "cost_brl": round(cost, 2), "avg_price_per_kwh": round(cost / energy, 2) if energy else None,
                "with_coupon": sum(1 for r in chosen if int(_float(r.get("discount_percent")) or 0)),
                "overstay_fees_brl": round(overstay, 2),
                "by_station": sorted(stations.values(), key=lambda s: -s["cost_brl"])[:5],
                "truncated": len(records) >= 100}

