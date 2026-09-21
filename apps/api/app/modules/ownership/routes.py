from fastapi import APIRouter, Depends
from sqlalchemy import select

from ...database import db_session
from ...errors import fail
from ...models import Connector, DeviceClaim, Profile, Station, now
from ...schemas import ClaimInput
from ...security import current_user, digest
from ...service import active_res, active_session
from ..auth.routes import limit

router = APIRouter()


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
        if target is None or target.owner_id != user.id:
            fail("not_found", "Posto não encontrado", 404)
        point.station_id = target.id
    else:
        station.owner_id = user.id
    claim.claimed_by = user.id
    claim.claimed_at = now()
    user.operator_enabled = True
    db.flush()
    return claim_result(point)


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
