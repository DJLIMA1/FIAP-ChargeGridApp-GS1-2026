from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from sqlalchemy import func, select

from chargegrid_core import power as power_rules
from chargegrid_core import pricing

from ... import overstay
from ...errors import fail
from ...http_helpers import allocation, retired_ids
from ...models import ChargingSession, Connector, Coupon, Profile, Reservation, Station, now
from ...presence_code import valid_code
from ...service import (
    SESSION_ACTIVE,
    SOC_STEP,
    active_res,
    availability,
    device_for,
    ensure_user_free,
    fail_unavailable,
    free,
    idempotent,
    issue,
    lock_point,
    online,
    remember,
    stop_if_battery_full,
)
from ..devices.service import battery_parameters
from ..economics.service import snapshot_session
from ..payments.funding import attach_payment, claim_for_start, funded_input, payment_price_terms
from ..payments.funding import locked_terms as payment_terms
from ..power.service import start_power
from ..pricing.service import locked_terms

# Optional start keys added after the first release: omitted from the idempotency hash when absent.
_BATTERY_KEYS = ("soc_percent", "battery_kwh", "soc_source", "max_power_kw", "payment_id", "overstay_terms_version")


def _point_for_code(db, user, data):
    if data.public_code:
        point = db.scalar(select(Connector).where(Connector.public_code == data.public_code))
        if not point:
            fail("not_found", "Ponto não encontrado", 404)
        return point
    if data.reservation_id:
        reservation = db.get(Reservation, data.reservation_id)
        if not reservation or reservation.user_id != user.id:
            fail("invalid_reservation", "Reserva inválida")
        return db.get(Connector, reservation.connector_id)
    points = db.execute(
        select(Connector, Station).join(Station).where(
            Connector.active.is_(True), Station.active.is_(True), Station.owner_id.is_not(None)
        )
    ).all()
    checked_at = now()
    matching = [point for point, station in points if valid_code(station, data.presence_code, checked_at)]
    if not matching:
        fail("invalid_presence_code", "Código do posto inválido ou expirado", 422)
    # Availability cannot disambiguate locations: that could start a different
    # station from the one whose physical display the user is reading.
    if len({point.station_id for point in matching}) > 1:
        fail("ambiguous_presence_code", "Há mais de um posto com este código. Escolha o ponto na lista antes de iniciar.", 422)
    if len(matching) == 1:
        return matching[0]
    available = [point for point in matching if free(db, point)]
    if len(available) == 1:
        return available[0]
    fail("ambiguous_presence_code", "Há mais de um ponto com este código. Escolha o ponto na lista antes de iniciar.", 422)


def find_coupon(db, connector, code):
    """Cupom digitado válido para este ponto (``None`` sem cupom); 422 quando inválido."""
    if not code:
        return None
    typed = code.strip().upper()
    # Case-insensitive: legacy rows may keep mixed case; an exact match wins.
    coupon = db.scalar(
        select(Coupon)
        .where(func.upper(Coupon.code) == typed, Coupon.active.is_(True), Coupon.valid_until > now())
        .order_by((Coupon.code == code.strip()).desc(), Coupon.id)
        .limit(1)
    )
    station = db.get(Station, connector.station_id)
    if (
        not coupon
        or coupon.operator_id != station.owner_id
        or (coupon.station_id and coupon.station_id != station.id)
    ):
        fail("invalid_coupon", "Cupom inválido", 422)
    return coupon


def _start_body(data):
    # Idempotency hash: omit the optional battery keys when absent so a retry
    # hashed before they existed still matches the same body.
    body = data.model_dump()
    for name in _BATTERY_KEYS:
        if body.get(name) is None:
            body.pop(name, None)
    return body


def _battery_fields(data):
    soc = data.soc_percent.quantize(SOC_STEP, rounding=ROUND_HALF_UP) if data.soc_percent is not None else None
    source = data.soc_source or ("simulated" if soc is not None else None)
    return {
        "soc_percent": soc,
        "start_soc_percent": soc,
        "battery_kwh": data.battery_kwh.quantize(SOC_STEP, rounding=ROUND_HALF_UP)
        if data.battery_kwh is not None else None,
        "soc_source": source,
    }


def session_power_limit(db, connector, requested=None):
    """Power cap applied at start: the point's effective power (rating, vendor limit and
    station share) intersected with the driver's limit. A later vendor change does not
    affect this session; it applies to the next start."""
    station = db.get(Station, connector.station_id)
    siblings = db.scalars(select(Connector).where(Connector.station_id == connector.station_id)).all()
    effective = allocation(station, siblings, retired_ids(db, [point.id for point in siblings]))
    applied = power_rules.applied_limit(effective["connectors"][connector.id]["effective_kw"], requested)
    return applied.quantize(Decimal("0.001"), rounding=ROUND_DOWN) if applied > 0 else None


def start(db, user, data, key):
    # Serialize this user's requests before looking up a rotating code. A retry
    # must recover the accepted session even after expiry or availability changes.
    db.execute(select(Profile).where(Profile.id == user.id).with_for_update()).scalar_one()
    old, body_hash = idempotent(db, user, "start", key, _start_body(data), ChargingSession)
    if old:
        lock_point(db, user, old.connector_id)
        db.refresh(old)
        return old
    point = _point_for_code(db, user, data)
    connector = lock_point(db, user, point.id)
    if not valid_code(db.get(Station, connector.station_id), data.presence_code):
        fail("invalid_presence_code", "Código do posto inválido ou expirado", 422)
    ensure_user_free(db, user, data.reservation_id)
    device = device_for(db, connector)
    reservation = active_res(db, connector.id)
    if data.reservation_id:
        if (
            not reservation
            or reservation.id != data.reservation_id
            or reservation.user_id != user.id
            or reservation.status != "confirmed"
        ):
            fail("invalid_reservation", "Reserva inválida")
        if (
            not connector.active
            or not db.get(Station, connector.station_id).active
            or not online(device)
            or not device.reconciled
            or device.physical_state != "reserved"
        ):
            fail("point_unavailable", "Ponto sem confirmação recente")
    else:
        # O pedido do totem pago por este pagamento não bloqueia o próprio START.
        state = availability(db, connector, device=device, allow_kiosk_payment=data.payment_id)
        if not state["available"]:
            fail_unavailable(state)
    payment = claim_for_start(db, user, connector, data.payment_id)
    if payment:
        data = funded_input(data, payment)
    if data.max_duration_minutes > connector.max_duration_minutes:
        fail("duration_limit", "Duração acima do limite do ponto", 422)
    if payment:
        # Pré-pago: valem os termos travados no orçamento pago (preço, desconto e a explicação do
        # recibo, com o cupom), não os do momento; o cupom já foi conferido ao orçar.
        base, multiplier, discount = payment_terms(payment)
        terms, coupon = payment_price_terms(payment, connector), None
    else:
        coupon = find_coupon(db, connector, data.coupon_code)
        discount = coupon.discount_percent if coupon else 0
        # Tarifa: base do horário × demanda, travadas ao reservar (termos da reserva) ou agora.
        base, multiplier, terms = locked_terms(db, connector, reservation)
    if reservation:
        reservation.status = "consumed"
    session = ChargingSession(
        user_id=user.id,
        connector_id=connector.id,
        reservation_id=reservation.id if reservation else None,
        max_duration_minutes=data.max_duration_minutes,
        max_cost=data.max_cost,
        price_per_kwh=pricing.dynamic_price(base, multiplier),
        base_price_per_kwh=base,
        demand_multiplier=multiplier,
        discount_percent=discount,
        power_limit_kw=session_power_limit(db, connector, data.max_power_kw),
        requested_power_kw=data.max_power_kw.quantize(Decimal("0.001"), rounding=ROUND_DOWN)
        if data.max_power_kw is not None else None,
        **_battery_fields(data),
        overstay_terms=overstay.terms_for_start(db, connector, data, payment),
    )
    db.add(session)
    db.flush()
    # Recibo e resultado do dono: explicação do preço, custo do kWh e comissão travados agora.
    snapshot_session(db, session, connector, terms, coupon)
    # Rebalanceamento ao vivo: potência inicial pela decisão do posto (409 sem capacidade).
    live_power = start_power(db, connector, device, session)
    limits = {
        "session_id": str(session.id),
        "max_duration_minutes": session.max_duration_minutes,
        "max_cost": str(session.max_cost) if session.max_cost else None,
        "price_per_kwh": str(session.price_per_kwh),
        "discount_percent": discount,
        # Older firmware ignores it; newer firmware/simulator cap the simulated power.
        "max_power_kw": float(session.power_limit_kw) if session.power_limit_kw is not None else None,
        **battery_parameters(session),
        **live_power,
        **overstay.start_parameters(session),
    }
    issue(db, connector, device, "START", session=session, parameters=limits)
    if payment:
        attach_payment(payment, session)
    remember(db, user, "start", key, body_hash, session)
    return session


def stop(db, user, session_id, key):
    session = db.get(ChargingSession, session_id)
    if not session or session.user_id != user.id:
        fail("not_found", "Sessão não encontrada", 404)
    connector = lock_point(db, user, session.connector_id)
    db.refresh(session)
    old, body_hash = idempotent(db, user, "stop:" + str(session_id), key, {}, ChargingSession)
    if old:
        return old
    if session.status in SESSION_ACTIVE and session.status != "stopping":
        session.status = "stopping"
        issue(db, connector, device_for(db, connector), "STOP", session=session)
    remember(db, user, "stop:" + str(session_id), key, body_hash, session)
    return session


def report_soc(db, user, session_id, soc_percent):
    """Phone (presentation mode) reports the car SoC; >= 100 stops as ``battery_full``."""
    session = db.get(ChargingSession, session_id)
    if not session or session.user_id != user.id:
        fail("not_found", "Sessão não encontrada", 404)
    connector = lock_point(db, user, session.connector_id)
    db.refresh(session)
    if session.status not in ("starting", "charging"):
        fail("session_not_active", "A recarga não está em andamento", 409)
    session.soc_percent = soc_percent.quantize(SOC_STEP, rounding=ROUND_HALF_UP)
    session.soc_source = "phone"
    if session.start_soc_percent is None:
        session.start_soc_percent = session.soc_percent
    stop_if_battery_full(db, connector, device_for(db, connector), session)
    db.flush()
    return session
