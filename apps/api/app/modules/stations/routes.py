import math
import secrets
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import case, delete, func, select

from chargegrid_core import power as power_rules
from chargegrid_core.chargers import link as charger_link

from ...database import db_session
from ...errors import fail
from ...http_helpers import page, point_row, retired_ids, station_row, station_rows, update
from ...models import (
    ChargingSession,
    Command,
    Connector,
    ConnectorHourlyStats,
    Device,
    DeviceBoot,
    DeviceClaim,
    KioskOrder,
    Payment,
    Reservation,
    Station,
    Telemetry,
    now,
)
from ...schemas import (
    ConnectorInput,
    ConnectorPatch,
    StationInput,
    StationPatch,
)
from ...security import current_user, digest
from ...service import (
    RES_ACTIVE,
    SESSION_ACTIVE,
    device_for,
    kiosk_holds,
    lock_screen_group,
    new_public_code,
    online,
    operator,
    owned,
    reset_blocks_point,
    screen_for,
    screen_group_key,
)
from .discovery import discover, normalize_connector

router = APIRouter()


@router.get("/stations")
def stations(
    lat: float | None = Query(None, ge=-90, le=90),
    lng: float | None = Query(None, ge=-180, le=180),
    radius_km: float = Query(50, gt=0, le=500),
    connector_type: str | None = Query(None, min_length=1, max_length=50),
    available_only: bool = False,
    max_price_per_kwh: Decimal | None = Query(None, ge=0, le=10000),
    sort: Literal["default", "price", "distance"] = "default",
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(current_user),
    db=Depends(db_session),
):
    if (lat is None) != (lng is None):
        fail("coordinates_required", "Informe lat e lng juntos", 422)
    if sort == "distance" and lat is None:
        fail("coordinates_required", "Informe lat e lng para ordenar por proximidade", 422)
    if connector_type is not None and not connector_type.strip():
        fail("validation_error", "Informe um conector válido", 422)
    query = select(Station).where(Station.active.is_(True), Station.removed_at.is_(None)).order_by(Station.id)
    if lat is not None:
        distance = 6371 * func.acos(
            func.least(
                1,
                func.greatest(
                    -1,
                    math.sin(math.radians(lat)) * func.sin(func.radians(Station.latitude))
                    + math.cos(math.radians(lat))
                    * func.cos(func.radians(Station.latitude))
                    * func.cos(func.radians(Station.longitude - lng)),
                ),
            )
        )
        query = query.where(distance <= radius_km)
    if not connector_type and not available_only and max_price_per_kwh is None:
        if sort in ("default", "distance"):
            if sort == "distance":
                query = query.order_by(None).order_by(distance, Station.id)
            def render(items):
                return [discover([item], lat=lat, lng=lng)[0] for item in station_rows(db, items, user)]
            return page(db, query, limit, offset, many=render)
    # Narrow by static point attributes before materializing authoritative states.
    # Availability itself also includes reservations, watchdog and reconciliation.
    point_query = select(Connector.id).where(Connector.station_id == Station.id, Connector.active.is_(True))
    if connector_type:
        key = func.regexp_replace(func.lower(Connector.connector_type), "[^a-z0-9]", "", "g")
        normalized = case((key.in_(("tipo2", "typeii")), "type2"),
                          (key.in_(("ccs", "ccstype2")), "ccs2"), else_=key)
        point_query = point_query.where(normalized == normalize_connector(connector_type))
    # A tarifa vigente inclui velocidade, horários e demanda: o preço base SQL não
    # pode excluir um posto cujo dono configurou uma máxima mais barata.
    if connector_type or available_only or max_price_per_kwh is not None:
        query = query.where(point_query.exists())
    # Availability includes device reconciliation and active operations. Use the
    # authoritative serializer before pagination, rather than a weaker SQL guess.
    records = discover(
        station_rows(db, db.scalars(query).all(), user),
        connector_type=connector_type, available_only=available_only,
        max_price_per_kwh=max_price_per_kwh, sort=sort, lat=lat, lng=lng,
    )
    return {"items": records[offset:offset + limit], "total": len(records), "limit": limit, "offset": offset}


@router.get("/stations/{station_id}")
def station(station_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    obj = db.get(Station, station_id)
    if not obj or obj.removed_at is not None:
        fail("not_found", "Posto não encontrado", 404)
    return station_row(db, obj, user)


@router.post("/stations", status_code=201)
def create_station(data: StationInput, user=Depends(current_user), db=Depends(db_session)):
    operator(user)
    obj = Station(owner_id=user.id, **data.model_dump())
    db.add(obj)
    db.flush()
    return station_row(db, obj, user)


@router.patch("/stations/{station_id}")
def patch_station(station_id: UUID, data: StationPatch, user=Depends(current_user), db=Depends(db_session)):
    obj = owned(db, user, station_id)
    # A station edit locks every connector. Take its screen groups in stable order first,
    # so reset retirement cannot wait on a child while this edit waits on the screen.
    ids = db.scalars(select(Connector.id).where(Connector.station_id == obj.id)).all()
    for root in sorted({screen_group_key(db, point_id) for point_id in ids}):
        lock_screen_group(db, root)
    points = db.scalars(
        select(Connector).where(Connector.station_id == obj.id).order_by(Connector.id).with_for_update()
    ).all()
    if data.active is False and any(
        db.scalar(
            select(ChargingSession.id).where(
                ChargingSession.connector_id == p.id, ChargingSession.status.in_(SESSION_ACTIVE)
            )
        )
        or db.scalar(
            select(Reservation.id).where(Reservation.connector_id == p.id, Reservation.status.in_(RES_ACTIVE))
        )
        for p in points
    ):
        fail("point_busy", "Encerre reservas/recargas antes de desativar")
    if "max_power_kw" in data.model_fields_set:
        # Without live rebalancing the cap is a next-start setting (running charges keep their
        # power); with rebalance_enabled, the next device syncs redivide it (modules/power).
        retired = retired_ids(db, [point.id for point in points])
        ratings = [point.power_kw for point in points if point.active and point.id not in retired]
        try:
            data.max_power_kw = power_rules.validate_station_max(data.max_power_kw, ratings)
        except ValueError as exc:
            fail("invalid_power_limit", str(exc), 422)
    update(obj, data)
    db.flush()
    db.refresh(obj)
    return station_row(db, obj, user)


CENTRAL_ONLINE_MESSAGE = ("Restaure a central (Dados da estação → Restaurar) antes de remover a estação: "
                          "ela volta ao QR de fábrica e pode ser usada em outro posto.")


@router.delete("/stations/{station_id}", status_code=204)
def remove_station(station_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    """Remover estação: o dono fecha o posto inteiro.

    Some de todas as listas (mapa e busca do motorista, "Suas Estações", painel, IA); sessões,
    recibos, pagamentos e relatórios continuam (os conectores ficam como histórico, ``removed_at``).
    Recusa com recarga, reserva ou pedido do totem em andamento (``station_busy``) e com central
    ligada (``central_online``: restaurar antes, para ela voltar ao QR de fábrica). Centrais
    desligadas são revogadas junto, com os carregadores comandados por elas."""
    owned(db, user, station_id)
    # Mesma ordem de travas do PATCH da estação: grupos de tela (ordem estável) -> estação ->
    # conectores -> dispositivos.
    ids = db.scalars(select(Connector.id).where(Connector.station_id == station_id)).all()
    for root in sorted({screen_group_key(db, point_id) for point_id in ids}):
        lock_screen_group(db, root)
    station = db.scalar(select(Station).where(Station.id == station_id).with_for_update()
                        .execution_options(populate_existing=True))
    if station is None or station.owner_id != user.id or station.removed_at is not None:
        fail("not_found", "Posto não encontrado", 404)
    points = db.scalars(
        select(Connector).where(Connector.station_id == station.id, Connector.removed_at.is_(None))
        .order_by(Connector.id).with_for_update().execution_options(populate_existing=True)
    ).all()
    point_ids = [point.id for point in points]
    if point_ids and (db.scalar(
        select(ChargingSession.id).where(
            ChargingSession.connector_id.in_(point_ids), ChargingSession.status.in_(SESSION_ACTIVE)).limit(1)
    ) or db.scalar(
        select(Reservation.id).where(
            Reservation.connector_id.in_(point_ids), Reservation.status.in_(RES_ACTIVE)).limit(1)
    ) or kiosk_holds(db, point_ids)):
        fail("station_busy", "Há recarga, reserva ou pedido do totem em andamento. Encerre antes de remover.")
    devices = db.scalars(
        select(Device).where(Device.connector_id.in_(point_ids or [None]), Device.revoked.is_(False))
        .order_by(Device.id).with_for_update().execution_options(populate_existing=True)
    ).all()
    screens = [device for device in devices if device.parent_device_id is None]
    if any(online(screen) for screen in screens):
        fail("central_online", CENTRAL_ONLINE_MESSAGE, 409)
    # Carregadores comandados por essas centrais (mesmo que estejam em outro posto) saem junto.
    children = db.scalars(
        select(Device).where(Device.parent_device_id.in_([screen.id for screen in screens] or [None]),
                             Device.revoked.is_(False))
        .order_by(Device.id).with_for_update().execution_options(populate_existing=True)
    ).all() if screens else []
    for device in {device.id: device for device in [*devices, *children]}.values():
        device.revoked = True
        device.reconciled = False
    stamp = now()
    for point in points:
        point.active = False
        point.charger_address = None  # liberado (connector_charger_address_unless_removed)
        point.removed_at = stamp
    station.active = False
    station.removed_at = stamp
    db.flush()
    return Response(status_code=204)


@router.post("/stations/{station_id}/connectors", status_code=201)
def create_point(station_id: UUID, data: ConnectorInput, user=Depends(current_user), db=Depends(db_session)):
    owned(db, user, station_id)
    fail("claim_required", "Escaneie o QR de propriedade do equipamento para adicionar um ponto", 409)


@router.post("/connectors/{connector_id}/chargers", status_code=201)
def add_charger(connector_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    """Adicionar carregador: o próximo carregador GoodWe da estação, comandado pela mesma tela.

    Nasce inativo (o dono revisa e publica), com o próximo endereço livre do posto e os dados
    do ponto da tela (tipo, potência, preço, duração). A tela passa a sincronizar por ele
    (``chargers`` na resposta do sync dela; firmware com ``multi_charger_v1``)."""
    point = db.get(Connector, connector_id)
    if not point or point.removed_at is not None:
        fail("not_found", "Ponto não encontrado", 404)
    station = owned(db, user, point.station_id)
    lock_screen_group(db, point.id)
    if reset_blocks_point(db, point.id):
        fail("reset_pending", "Aguarde a restauração da central antes de adicionar carregadores", 409)
    # Trava a estação: dois "Adicionar carregador" seguidos não disputam o mesmo endereço.
    db.execute(select(Station.id).where(Station.id == station.id).with_for_update())
    screen = screen_for(db, device_for(db, point))
    if screen is None:
        fail("screen_required", "Este ponto não tem central vinculada. Vincule a central pelo QR antes de "
             "adicionar carregadores.", 409)
    base = db.get(Connector, screen.connector_id)
    used = db.scalars(select(Connector.charger_address).where(Connector.station_id == base.station_id)).all()
    try:
        address = charger_link.next_free_address(used)
    except ValueError as exc:
        fail("charger_address_full", str(exc), 409)
    charger = Connector(
        station_id=base.station_id, public_code=new_public_code(db), connector_type=base.connector_type,
        power_kw=base.power_kw, price_per_kwh=base.price_per_kwh, max_duration_minutes=base.max_duration_minutes,
        active=False, charger_address=address,
    )
    db.add(charger)
    db.flush()
    # Sem chave utilizável: só a tela sincroniza por ele (sync endereçado).
    db.add(Device(connector_id=charger.id, key_hash=digest(secrets.token_urlsafe(32)), parent_device_id=screen.id))
    db.flush()
    db.refresh(charger)
    return point_row(db, charger, user)


# Linhas que guardam histórico de um ponto: com qualquer uma, o carregador removido fica
# (``removed_at``) para recibos e relatórios; sem nenhuma, as linhas dele são apagadas.
_POINT_HISTORY = (
    (ChargingSession, ChargingSession.connector_id),
    (Reservation, Reservation.connector_id),
    (Payment, Payment.connector_id),
    (KioskOrder, KioskOrder.connector_id),
    (ConnectorHourlyStats, ConnectorHourlyStats.connector_id),
    # QR de propriedade: o papel da API não tem DELETE em device_claims (migração d85af641bc01).
    (DeviceClaim, DeviceClaim.connector_id),
)


@router.delete("/connectors/{connector_id}", status_code=204)
def remove_charger(connector_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    """Remover carregador: só um carregador adicional da estação (nunca o ponto da própria central).

    Sem histórico, apaga o conector e os dispositivos dele. Com histórico, o conector fica para as
    chaves estrangeiras e recibos (``removed_at``, inativo, dispositivo revogado) e some das listas,
    do sync da central (``chargers``) e do mapa; o endereço GoodWe fica livre para reuso."""
    point = db.get(Connector, connector_id)
    if not point or point.removed_at is not None:
        fail("not_found", "Ponto não encontrado", 404)
    station = owned(db, user, point.station_id)
    lock_screen_group(db, point.id)
    db.execute(select(Station.id).where(Station.id == station.id).with_for_update())
    point = db.scalar(select(Connector).where(Connector.id == connector_id).with_for_update()
                      .execution_options(populate_existing=True))
    if point is None or point.removed_at is not None:
        fail("not_found", "Ponto não encontrado", 404)
    devices = db.scalars(select(Device).where(Device.connector_id == point.id).with_for_update()).all()
    if not any(device.parent_device_id is not None for device in devices):
        fail("screen_charger", "Este é o carregador da própria central; ele não pode ser removido.", 409)
    if db.scalar(
        select(ChargingSession.id).where(
            ChargingSession.connector_id == point.id, ChargingSession.status.in_(SESSION_ACTIVE))
    ) or db.scalar(
        select(Reservation.id).where(Reservation.connector_id == point.id, Reservation.status.in_(RES_ACTIVE))
    ) or kiosk_holds(db, [point.id]):
        fail("point_busy", "Encerre reservas/recargas antes de remover o carregador")
    device_ids = [device.id for device in devices]
    history = any(db.scalar(select(column).where(column == point.id).limit(1)) for _, column in _POINT_HISTORY) \
        or (device_ids and db.scalar(select(Telemetry.id).where(Telemetry.device_id.in_(device_ids)).limit(1)))
    if history:
        for device in devices:
            device.revoked = True
            device.reconciled = False
        point.active = False
        point.charger_address = None  # endereço livre para o próximo "Adicionar carregador"
        point.removed_at = now()
    else:
        if device_ids:
            for model in (Command, DeviceBoot):
                db.execute(delete(model).where(model.device_id.in_(device_ids)))
            db.execute(delete(Device).where(Device.id.in_(device_ids)))
        db.delete(point)
    db.flush()
    return Response(status_code=204)


@router.patch("/connectors/{connector_id}")
def patch_point(connector_id: UUID, data: ConnectorPatch, user=Depends(current_user), db=Depends(db_session)):
    lock_screen_group(db, connector_id)
    obj = db.scalar(select(Connector).where(Connector.id == connector_id).with_for_update())
    if not obj or obj.removed_at is not None:
        fail("not_found", "Ponto não encontrado", 404)
    owned(db, user, obj.station_id)
    if data.active is True and reset_blocks_point(db, obj.id):
        fail("point_retired", "Ponto em restauração de fábrica; vincule a central novamente pelo QR", 409)
    if "charger_address" in data.model_fields_set and data.charger_address is None:
        # Todo conector é um carregador GoodWe: o endereço pode mudar, nunca ficar vazio.
        fail("invalid_charger_address", charger_link.EMPTY_ADDRESS_MESSAGE, 422)
    if "charger_address" in data.model_fields_set and data.charger_address == obj.charger_address:
        data.model_fields_set.discard("charger_address")  # mesmo carregador: nada muda (nem com recarga)
    limit_only = data.model_fields_set <= {"power_limit_kw"}
    # A power limit only affects the next start (a running charge keeps the power it
    # started with), so it may change while the point is busy; other edits may not.
    if not limit_only and (db.scalar(
        select(ChargingSession.id).where(
            ChargingSession.connector_id == obj.id, ChargingSession.status.in_(SESSION_ACTIVE)
        )
    ) or db.scalar(
        select(Reservation.id).where(Reservation.connector_id == obj.id, Reservation.status.in_(RES_ACTIVE))
    )):
        fail("point_busy", "Encerre reservas/recargas antes de alterar o ponto")
    rating = data.power_kw if data.power_kw is not None else obj.power_kw
    if "power_limit_kw" in data.model_fields_set:
        try:
            data.power_limit_kw = power_rules.validate_port_limit(rating, data.power_limit_kw)
        except ValueError as exc:
            fail("invalid_power_limit", str(exc), 422)
    elif data.power_kw is not None and obj.power_limit_kw is not None and obj.power_limit_kw >= data.power_kw:
        # A new rating at or below the old limit makes that limit meaningless: clear it.
        obj.power_limit_kw = None
    if data.public_code is not None and db.scalar(
        select(Connector.id).where(Connector.public_code == data.public_code, Connector.id != obj.id)
    ):
        # Was a generic IntegrityError 409 ("Operação conflita com registro existente").
        fail("public_code_taken", "Já existe um ponto com este código público. Escolha outro.", 409)
    if "charger_address" in data.model_fields_set:
        # Endereço único por posto: dois pontos no mesmo carregador disputariam o mesmo relé.
        taken = db.scalar(select(Connector).where(
            Connector.station_id == obj.station_id, Connector.charger_address == data.charger_address,
            Connector.id != obj.id))
        if taken:
            fail("charger_address_taken",
                 f"O carregador {data.charger_address} já está ligado ao ponto {taken.public_code} deste posto. "
                 "Escolha outro endereço.", 409)
    update(obj, data)
    db.flush()
    db.refresh(obj)
    return point_row(db, obj, user)


@router.get("/operator/stations")
def operator_stations(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(current_user),
    db=Depends(db_session),
):
    operator(user)
    return page(
        db,
        select(Station).where(Station.owner_id == user.id, Station.removed_at.is_(None)).order_by(Station.id),
        limit,
        offset,
        many=lambda items: station_rows(db, items, user),
    )
