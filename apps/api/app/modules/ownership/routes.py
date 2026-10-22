from fastapi import APIRouter, Depends
from sqlalchemy import select

from chargegrid_core.chargers import link as charger_link

from ...database import db_session
from ...errors import fail
from ...http_helpers import retired_ids
from ...models import Connector, Device, DeviceClaim, Profile, Station, now
from ...schemas import ClaimInput
from ...security import current_user, digest
from ...service import active_res, active_session
from ..auth.routes import limit

router = APIRouter()

FACTORY_NAME = "Novo ponto ChargeGrid"
PRESENTATION_NAME = "Lab-ChargeGrid FIAP"
PRESENTATION_ADDRESS = "Av. Lins de Vasconcelos, 1222"
PRESENTATION_LATITUDE, PRESENTATION_LONGITUDE = -23.5739, -46.6233


def claim_point(db, user_id, data):
    # Match operation lock order: profile -> connector -> dependent records.
    # Re-read locked rows after waiting so competing claims cannot use stale owners.
    user = db.scalar(
        select(Profile)
        .where(Profile.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not user or not (user.account_type == "vendor" or user.operator_enabled):
        fail("vendor_required", "Somente uma conta de vendedor pode vincular um ponto", 403)
    connector_id = db.scalar(
        select(DeviceClaim.connector_id).where(DeviceClaim.token_hash == digest(data.token))
    )
    if not connector_id:
        fail("invalid_claim", "QR de propriedade inválido", 404)
    point = db.scalar(
        select(Connector)
        .where(Connector.id == connector_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    claim = db.scalar(
        select(DeviceClaim)
        .where(DeviceClaim.connector_id == connector_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    station = db.get(Station, point.station_id, populate_existing=True)
    if claim.claimed_by is not None:
        if claim.claimed_by != user.id or station.owner_id != user.id:
            fail("already_owned", "Este ponto já pertence a outro vendedor", 409)
        if data.station_id is not None and data.station_id != point.station_id:
            fail("already_claimed", "Este QR já foi usado; não permite transferir o ponto", 409)
        return claim_result(point, already=True)
    # A factory claim must never overwrite ownership of an existing station.
    if station.owner_id is not None:
        fail("already_owned", "Este ponto já possui proprietário", 409)
    if station.active or active_res(db, point.id) or active_session(db, point.id):
        fail("point_busy", "Ponto não está disponível para vinculação", 409)
    if data.station_id is not None:
        target = db.get(Station, data.station_id, populate_existing=True)
        if target is None or target.owner_id != user.id or target.removed_at is not None:
            fail("not_found", "Posto não encontrado", 404)
        # Central restaurada e vinculada de novo: os pontos que ela deixou no posto viram histórico
        # e liberam o endereço; o ponto novo herda os ajustes do antigo (senão ganharia o próximo
        # endereço e procuraria um GoodWe que não existe).
        template = retire_leftovers(db, target.id, point.id)
        if template is not None:
            for field in ("connector_type", "power_kw", "price_per_kwh", "max_duration_minutes", "power_limit_kw"):
                setattr(point, field, getattr(template, field))
        # Cada conector é um carregador GoodWe: ao entrar no posto, o ponto recebe o próximo
        # endereço livre dele (o 1 do posto de fábrica colidiria com o primeiro ponto).
        used = db.scalars(
            select(Connector.charger_address)
            .where(Connector.station_id == target.id, Connector.id != point.id,
                   Connector.charger_address.is_not(None))
            .with_for_update()
        ).all()
        try:
            point.charger_address = charger_link.next_free_address(used)
        except ValueError as exc:
            fail("charger_address_full", str(exc), 409)
        point.station_id = target.id
    else:
        station.owner_id = user.id
        if user.presentation_mode and station.name == FACTORY_NAME:
            # Modo apresentação: a central nova já entra como o laboratório da FIAP.
            station.name, station.address = PRESENTATION_NAME, PRESENTATION_ADDRESS
            station.latitude, station.longitude = PRESENTATION_LATITUDE, PRESENTATION_LONGITUDE
    claim.claimed_by = user.id
    claim.claimed_at = now()
    user.operator_enabled = True
    db.flush()
    return claim_result(point)


def retire_leftovers(db, station_id, keep_id):
    """Points of a restored central still in ``station_id``: inactive, with hardware but every
    device revoked. They become history (``removed_at``) and free their GoodWe address. Returns
    the one with the lowest address (the central's own point first), whose settings are reused."""
    live = select(Device.connector_id).where(Device.revoked.is_(False))
    attached = select(Device.connector_id)
    leftovers = db.scalars(
        select(Connector)
        .where(Connector.station_id == station_id, Connector.id != keep_id, Connector.removed_at.is_(None),
               Connector.active.is_(False), Connector.id.in_(attached), Connector.id.not_in(live))
        .order_by(Connector.charger_address.nulls_last())
        .with_for_update()
    ).all()
    if not leftovers:
        return None
    screens = retired_ids(db, [leftover.id for leftover in leftovers])
    template = next((leftover for leftover in leftovers if leftover.id in screens), leftovers[0])
    stamp = now()
    for leftover in leftovers:
        leftover.removed_at = stamp
        leftover.charger_address = None
    db.flush()  # frees the addresses before the new point takes one (unique per station)
    return template


def claim_result(point, already=False):
    return {
        "station_id": str(point.station_id),
        "connector_id": str(point.id),
        "already_claimed": already,
        "message": "Este ponto já é seu"
        if already
        else "Ponto vinculado à sua conta. Revise os dados antes de publicar.",
    }


@router.post("/ownership/claim")
def claim(data: ClaimInput, user=Depends(current_user), db=Depends(db_session)):
    limit(db, "ownership:" + str(user.id), maximum=15)
    return claim_point(db, user.id, data)
