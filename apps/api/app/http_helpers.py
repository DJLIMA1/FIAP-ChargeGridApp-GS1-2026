from decimal import Decimal

from sqlalchemy import func, select

from chargegrid_core import power as power_rules
from chargegrid_core import pricing, site_load
from chargegrid_core.chargers import link as charger_link

from . import overstay
from .errors import fail
from .models import ChargingSession, Command, Connector, Device, Reservation, Station
from .modules.payments.funding import payment_channel, payment_row, payments_by_session, totem_payment_ids
from .service import (
    MULTI_CHARGER_CAPABILITY,
    RES_ACTIVE,
    SESSION_ACTIVE,
    availability,
    hardware_state,
    kiosk_holds,
    lock_screen_group,
    online,
    owned,
    resetting_screens,
    row,
)

# Campos do recibo/resultado do dono (migração b6d2f9a4c8e1) fora das respostas existentes:
# o formato de postos, reservas e sessões não muda e o custo do dono não vai ao motorista.
ECONOMICS_FIELDS = ("energy_cost_per_kwh", "platform_fee_percent")
SESSION_RECEIPT_FIELDS = ("price_terms", *ECONOMICS_FIELDS)


def update(obj, data):
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is None and key not in ("phone", "vehicle_description", "max_power_kw", "power_limit_kw"):
            fail("null_not_allowed", "Campo não aceita null", 422)
        setattr(obj, key, value)


def _retired_ids(db, connector_ids):
    if not connector_ids:
        return set()
    return set(db.scalars(
        select(Device.connector_id).select_from(Command).join(Device, Device.id == Command.device_id).where(
            Device.connector_id.in_(connector_ids),
            Command.type == "FACTORY_RESET",
            Command.status == "applied",
        ).distinct()
    ))


retired_ids = _retired_ids


def _point_state(db, connectors):
    """Load every row that availability needs for many points in four queries."""
    ids = [point.id for point in connectors]
    if not ids:
        return {}, {}, {}, set()
    devices = {
        device.connector_id: device
        for device in db.scalars(select(Device).where(Device.connector_id.in_(ids), Device.revoked.is_(False)))
    }
    reservations = {
        item.connector_id: item
        for item in db.scalars(
            select(Reservation).where(Reservation.connector_id.in_(ids), Reservation.status.in_(RES_ACTIVE))
        )
    }
    sessions = {
        item.connector_id: item
        for item in db.scalars(
            select(ChargingSession).where(
                ChargingSession.connector_id.in_(ids), ChargingSession.status.in_(SESSION_ACTIVE)
            )
        )
    }
    return devices, reservations, sessions, _retired_ids(db, ids)


def _screens(db, devices):
    """Telas (estações) dos dispositivos carregados: a própria linha ou a tela-mãe (uma consulta)."""
    parents = {device.parent_device_id for device in devices.values() if device.parent_device_id}
    loaded = {
        device.id: device
        for device in (db.scalars(select(Device).where(Device.id.in_(parents), Device.revoked.is_(False)))
                       if parents else [])
    }
    return {
        connector_id: (device if device.parent_device_id is None else loaded.get(device.parent_device_id))
        for connector_id, device in devices.items()
    }


def screen_block(db, screen, device, codes=None):
    """Dono: a TELA que comanda este carregador (``role`` screen = o ponto da própria tela)."""
    if screen is None:
        return None
    codes = codes if codes is not None else {}
    code = codes.get(screen.connector_id)
    if code is None:
        point = db.get(Connector, screen.connector_id)
        code = point.public_code if point is not None else None
    return {
        "device_id": str(screen.id),
        "connector_id": str(screen.connector_id),
        "public_code": code,
        "online": online(screen),
        "last_seen": screen.last_seen.isoformat() if screen.last_seen else None,
        "firmware_version": screen.firmware_version,
        "role": "screen" if device is screen else "charger",
        "multi_charger": MULTI_CHARGER_CAPABILITY in (screen.capabilities or []),
    }


KW = Decimal("0.001")


def _kw(value):
    return None if value is None else str(Decimal(value).quantize(KW))


def hardware_power_limit(device, maximum):
    """Intersect nominal/site allocation with the latest confirmed charger capacity."""
    maximum = Decimal(maximum)
    charger = device.charger if device and isinstance(device.charger, dict) else {}
    if online(device) and charger.get("link") != "offline" and charger.get("max_power_w"):
        reported = Decimal(str(charger["max_power_w"])) / 1000
        if reported > 0:
            maximum = min(maximum, reported)
    return maximum


def station_budget(station):
    """Static station budget for ``allocation``: with live rebalancing the chargers' cap (the live
    decision applies the contracted limit and the store margin); without it, the whole
    ``site_load.chargers_budget`` = min(cap, contracted − estimated store peak), split at start."""
    if station is None:
        return None
    if station.rebalance_enabled is not False:
        return station.max_power_kw
    return site_load.chargers_budget(station.site_limit_kw, station.store_min_kw, station.store_peak_kw,
                                     station.max_power_kw)


def allocation(station, connectors, retired):
    """Effective power of every point of one station (``chargegrid_core.power``)."""
    return power_rules.allocate(
        [
            {
                "id": point.id,
                "power_kw": point.power_kw,
                "power_limit_kw": point.power_limit_kw,
                "participates": bool(point.active) and point.id not in retired,
            }
            for point in connectors
        ],
        station_budget(station),
    )


def energy_totals(db, connector_ids):
    """kWh delivered per point (all its sessions) in one grouped query."""
    if not connector_ids:
        return {}
    rows = db.execute(
        select(ChargingSession.connector_id, func.coalesce(func.sum(ChargingSession.energy_wh), 0))
        .where(ChargingSession.connector_id.in_(connector_ids))
        .group_by(ChargingSession.connector_id)
    ).all()
    return {connector_id: Decimal(total) / 1000 for connector_id, total in rows}


def _render_point(db, connector, station, devices, reservations, sessions, retired, power=None, energy=None,
                  holds=None, screens=None, codes=None, resetting=None):
    result = row(connector)
    device = devices.get(connector.id)
    screen = (screens if screens is not None else _screens(db, devices)).get(connector.id)
    resetting = resetting if resetting is not None else resetting_screens(db, [screen.id] if screen else [])
    result.update(availability(
        db, connector, device=device, station=station,
        reservation=reservations.get(connector.id), session=sessions.get(connector.id),
        hold=(holds or {}).get(connector.id), screen=screen,
        resetting=screen is not None and screen.id in resetting,
    ))
    _, charger_online, _ = hardware_state(connector, device, screen)
    result.update(
        # "online" = o CARREGADOR responde (tela com contato e GoodWe lido); a estação é screen_online.
        online=charger_online,
        physical_state=device.physical_state if device else "unknown",
        retired=connector.id in retired,
    )
    allocated = (power or {}).get(connector.id)
    if allocated:
        effective = hardware_power_limit(device, allocated["effective_kw"])
        hardware_limited = effective < allocated["effective_kw"]
        result.update(
            effective_power_kw=_kw(effective),
            power_limited=allocated["power_limited"] or hardware_limited,
            power_limited_by="hardware" if hardware_limited else allocated["limited_by"],
        )
    if energy is not None:
        # Owner-only: total energy delivered by this point.
        result["energy_kwh_total"] = _kw(energy.get(connector.id, Decimal(0)))
        # Owner-only: the GoodWe charger of this point (address) and its link state from the last sync.
        result["charger_link"] = charger_link.owner_block(
            connector.charger_address, device.charger if device else None, result["screen_online"])
        if device is not None and device is not screen and result["screen_online"] and not online(device):
            # Carregador adicional que a tela parou de sincronizar: offline (não "aguardando").
            result["charger_link"]["link"] = "offline"
        # Dono: a tela (estação) que comanda este carregador.
        result["screen"] = screen_block(db, screen, device, codes)
    else:
        result.pop("charger_address", None)  # drivers: nothing changes
    return result


def _owner_view(station, viewer):
    return viewer is not None and station is not None and station.owner_id == getattr(viewer, "id", None)


def point_row(db, connector, viewer=None):
    station = db.get(Station, connector.station_id)
    siblings = db.scalars(select(Connector).where(Connector.station_id == connector.station_id,
                                                  Connector.removed_at.is_(None))).all()
    retired = _retired_ids(db, [point.id for point in siblings])
    power = allocation(station, siblings, retired)["connectors"]
    energy = energy_totals(db, [connector.id]) if _owner_view(station, viewer) else None
    devices, reservations, sessions, _ = _point_state(db, [connector])
    return _render_point(db, connector, station, devices, reservations, sessions, retired, power, energy,
                         kiosk_holds(db, [connector.id]), _screens(db, devices),
                         {point.id: point.public_code for point in siblings})


def station_rows(db, stations, viewer=None):
    """Serialize stations with a constant number of queries, not per point (N+1).

    ``viewer``: the owner also gets ``energy_kwh_total`` per point.
    """
    stations = list(stations)
    if not stations:
        return []
    connectors = db.scalars(
        select(Connector).where(Connector.station_id.in_([station.id for station in stations]),
                                Connector.removed_at.is_(None))
    ).all()
    state = _point_state(db, connectors)
    screens = _screens(db, state[0])
    resetting = resetting_screens(db, [screen.id for screen in screens.values() if screen])
    codes = {point.id: point.public_code for point in connectors}
    holds = kiosk_holds(db, [point.id for point in connectors])
    retired = state[3]
    owned_stations = {station.id for station in stations if _owner_view(station, viewer)}
    energy = energy_totals(db, [point.id for point in connectors if point.station_id in owned_stations])
    by_station = {}
    for point in connectors:
        by_station.setdefault(point.station_id, []).append(point)
    from .modules.pricing.service import demand_by_station  # evita import circular

    demand = demand_by_station(db, stations, by_station, state)
    results = []
    for station in stations:
        result = row(station)
        result.pop("presence_secret", None)
        result.pop("pricing", None)  # dados base do dono: GET /stations/{id}/pricing
        for key in ECONOMICS_FIELDS:  # resultado do dono: GET /stations/{id}/economics
            result.pop(key, None)
        status = demand[station.id]
        result["demand"] = {key: status[key] for key in ("multiplier", "level", "level_label", "increase_percent",
                                                          "reason", "reason_label")}
        result["latitude"] = float(station.latitude)
        result["longitude"] = float(station.longitude)
        points = by_station.get(station.id, [])
        power = allocation(station, points, retired)
        result["allocated_power_kw"] = _kw(power["allocated_kw"])
        result["requested_power_kw"] = _kw(power["requested_kw"])
        result["power_shared"] = power["shared"]
        # Condições públicas da taxa de permanência, mostradas antes de aceitar a recarga.
        result["overstay"] = overstay.public_terms(station)
        station_energy = energy if _owner_view(station, viewer) else None
        if station_energy is not None:
            # Totem 0.8.0 (só o dono): método efetivo pelo Modo apresentação da conta e motivo.
            from .modules.kiosk_totem.service import station_status  # evita import circular

            result["kiosk_status"] = station_status(station, viewer)
        result["connectors"] = [
            _render_point(db, point, station, *state, power["connectors"], station_energy, holds, screens, codes, resetting)
            for point in points
        ]
        # Estação = a tela: online enquanto alguma tela do posto tem contato (null = sem tela).
        station_screens = {screens[point.id].id: screens[point.id] for point in points if screens.get(point.id)}
        result["screen_online"] = (any(online(item) for item in station_screens.values())
                                   if station_screens else None)
        if station_energy is not None:
            result["screens"] = [
                {**{key: value for key, value in screen_block(db, item, item, codes).items() if key != "role"},
                 "charger_ids": [point["id"] for point in result["connectors"]
                                 if point.get("screen") and point["screen"]["device_id"] == str(item.id)]}
                for item in station_screens.values()
            ]
        for point in result["connectors"]:
            # Preço que o motorista paga agora (base do horário × demanda); travado ao reservar ou iniciar.
            current, price = pricing.connector_price(status, point["id"], point["price_per_kwh"])
            point["current_base_price_per_kwh"] = str(current)
            point["dynamic_price_per_kwh"] = str(price)
            point.update(pricing.speed_prices(status, point["id"], point["price_per_kwh"]))
        results.append(result)
    return results


def station_row(db, station, viewer=None):
    return station_rows(db, [station], viewer)[0]


def point_context(db, connector):
    station = db.get(Station, connector.station_id)
    public_fields = ("id", "public_code", "connector_type", "power_kw", "price_per_kwh", "max_duration_minutes")
    serialized = row(connector)
    return {
        "station_id": str(station.id),
        "station_name": station.name,
        "station_address": station.address,
        "connector": {key: serialized[key] for key in public_fields},
    }


def reservation_row(db, reservation):
    from .modules.pricing.service import locked_terms  # evita import circular

    result = row(reservation)
    if result:
        result.pop("price_terms", None)  # explicação completa no recibo da recarga
        point = db.get(Connector, reservation.connector_id)
        result.update(point_context(db, point))
        base, multiplier, terms = locked_terms(db, point, reservation)
        result["power_tier"] = terms.get("power_tier", "max")
        locked = pricing.dynamic_price(base, multiplier)
        if locked != Decimal(point.price_per_kwh):
            # O ponto da reserva mostra o preço travado ao reservar (base do horário × multiplicador).
            connector = result["connector"]
            connector["base_price_per_kwh"] = connector["price_per_kwh"]
            connector["price_per_kwh"] = str(locked)
    return result


def session_rows(db, sessions, *, channel=False):
    """History pages: preload points, stations and devices instead of N+1 lookups.

    ``channel``: seller views (``/operator/charging-sessions``, station history) also get
    ``payment.channel`` (``app`` | ``kiosk_qr`` | ``kiosk_totem``), as in ``/owner/sessions``.
    """
    sessions = list(sessions)
    connector_ids = {session.connector_id for session in sessions}
    devices = {}
    # Strong references keep these rows in the (weak) identity map, so the
    # db.get() calls in point_context below are served from memory.
    loaded = []
    if connector_ids:
        connectors = db.scalars(select(Connector).where(Connector.id.in_(connector_ids))).all()
        station_ids = {point.station_id for point in connectors}
        loaded = [*connectors, *db.scalars(select(Station).where(Station.id.in_(station_ids))).all()]
        devices = {
            device.connector_id: device
            for device in db.scalars(
                select(Device).where(Device.connector_id.in_(connector_ids), Device.revoked.is_(False))
            )
        }
    payments = payments_by_session(db, [session.id for session in sessions])
    totem = totem_payment_ids(db, payments.values()) if channel else set()
    results = []
    for session in sessions:
        result = row(session)
        result["power_tier"] = (session.price_terms or {}).get("power_tier", "max")
        for key in SESSION_RECEIPT_FIELDS:  # GET /charging-sessions/{id}/receipt e /owner/margin
            result.pop(key, None)
        connector = db.get(Connector, session.connector_id)
        result.update(point_context(db, connector))
        result["online"] = online(devices.get(connector.id))
        # Pré-pagamento (Stripe, teste) desta recarga, ou null.
        result["payment"] = payment_row(payments[session.id]) if session.id in payments else None
        if channel and result["payment"] is not None:
            result["payment"]["channel"] = payment_channel(payments[session.id], totem)
        # Permanência após a recarga: colunas internas viram o bloco calculado ``overstay``.
        for key in [name for name in result if name.startswith("overstay_")]:
            result.pop(key)
        result.update(overstay.session_fields(session))
        results.append(result)
    del loaded
    return results


def session_row(db, session):
    if session is None:
        return None
    return session_rows(db, [session])[0]


def page(db, query, limit, offset, renderer=row, *, many=None):
    """Paginate; ``many`` renders the whole page at once to avoid N+1 queries."""
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.limit(limit).offset(offset)).all()
    rendered = many(items) if many else [renderer(x) for x in items]
    return {"items": rendered, "total": total, "limit": limit, "offset": offset}


def own_device(db, user, device_id, *, require_idle=True):
    obj = db.get(Device, device_id)
    if not obj:
        fail("not_found", "Dispositivo não encontrado", 404)
    if require_idle:
        lock_screen_group(db, obj.connector_id)
    query = select(Connector).where(Connector.id == obj.connector_id)
    point = db.scalar(query.with_for_update() if require_idle else query)
    owned(db, user, point.station_id)
    if not require_idle:
        return obj
    db.refresh(obj)
    if db.scalar(
        select(ChargingSession.id).where(
            ChargingSession.connector_id == point.id, ChargingSession.status.in_(SESSION_ACTIVE)
        )
    ) or db.scalar(
        select(Reservation.id).where(Reservation.connector_id == point.id, Reservation.status.in_(RES_ACTIVE))
    ):
        fail("point_busy", "Encerre reservas/recargas antes de mudar credencial")
    return obj
