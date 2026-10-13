"""Modo Motorista: perfil do veículo/turno, plano de recarga e "próxima parada agora".

Toda a lógica de planejamento vem de ``chargegrid_core.driver`` (a mesma usada pelo
modo demo do app). Aqui só reunimos postos reais, perfil salvo e sinais ao vivo.
"""
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from chargegrid_core.driver import (
    build_next_stop,
    build_plan,
    default_profile,
    merge_profile,
    presets,
    validate_profile,
)

from ...database import db_session
from ...errors import fail
from ...http_helpers import station_rows
from ...models import DriverProfile, Station, now
from ...security import current_user
from ..auth.routes import limit
from .schemas import DriverProfileInput, NextStopInput, PlanInput
from .weather import weather_signal

router = APIRouter()

LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
MAX_STATIONS = 40
LIVE_HORIZON_HOURS = 16
# O planejador é CPU (centenas de ms) e consulta o clima: limite por usuário contra abuso/custo.
PLAN_LIMIT = (30, 60)


def local_now() -> datetime:
    """Horário local de São Paulo, sem fuso (o planejador trabalha em hora local)."""
    return datetime.now(LOCAL_TIMEZONE).replace(tzinfo=None)


def _validated(profile: dict) -> dict:
    try:
        return validate_profile(profile)
    except ValueError as error:
        fail("invalid_driver_profile", str(error), 422)


def _saved(obj: DriverProfile | None) -> dict | None:
    if obj is None:
        return None
    try:
        return validate_profile({"vehicle": obj.vehicle, "preferences": obj.preferences})
    except ValueError:
        # Perfil antigo incompatível: segue com o padrão em vez de travar o motorista.
        return None


def _dump(model) -> dict | None:
    return None if model is None else model.model_dump(exclude_none=True)


def _profile_response(obj: DriverProfile | None, profile: dict) -> dict:
    return {
        **profile,
        "saved": obj is not None,
        "updated_at": obj.updated_at.isoformat() if obj is not None and obj.updated_at else None,
        "presets": presets(),
    }


@router.get("/driver/profile")
def get_profile(user=Depends(current_user), db=Depends(db_session)):
    obj = db.get(DriverProfile, user.id)
    return _profile_response(obj, _saved(obj) or validate_profile(default_profile()))


@router.put("/driver/profile")
def put_profile(data: DriverProfileInput, user=Depends(current_user), db=Depends(db_session)):
    profile = _validated(merge_profile(None, {"vehicle": _dump(data.vehicle), "preferences": _dump(data.preferences)}))
    db.execute(
        insert(DriverProfile)
        .values(user_id=user.id, vehicle=profile["vehicle"], preferences=profile["preferences"], updated_at=now())
        .on_conflict_do_update(
            index_elements=[DriverProfile.user_id],
            set_={"vehicle": profile["vehicle"], "preferences": profile["preferences"], "updated_at": now()},
        )
    )
    db.flush()
    obj = db.get(DriverProfile, user.id)
    db.refresh(obj)
    return _profile_response(obj, profile)


def _stations(db, lat, lng, radius_km):
    query = select(Station).where(Station.active.is_(True))
    if lat is not None:
        distance = 6371 * func.acos(func.least(1, func.greatest(
            -1,
            math.sin(math.radians(lat)) * func.sin(func.radians(Station.latitude))
            + math.cos(math.radians(lat)) * func.cos(func.radians(Station.latitude))
            * func.cos(func.radians(Station.longitude - lng)),
        )))
        query = query.where(distance <= radius_km).order_by(distance, Station.id)
    else:
        query = query.order_by(Station.id)
    # One batch serialization for up to MAX_STATIONS stations (no per-point queries).
    return station_rows(db, db.scalars(query.limit(MAX_STATIONS)).all())


def _signals(data: NextStopInput, current: datetime):
    """Sinais ao vivo opcionais + notas para os alertas. Nunca falha: cai para a heurística."""
    if not data.live_signals:
        return (), [{"source": "open-meteo", "status": "desativado"}], []
    if data.lat is None:
        return (), [{"source": "open-meteo", "status": "sem_localizacao",
                     "detail": "Informe a localização para considerar o clima."}], []
    weather = weather_signal(data.lat, data.lng)
    if weather is None:
        return (), [{"source": "open-meteo", "status": "indisponivel",
                     "detail": "Clima indisponível agora; usando apenas a curva estimada."}], []
    notes = []
    end = current.replace(minute=0, second=0, microsecond=0)
    rainy = weather.rainy_hours(current, end + timedelta(hours=LIVE_HORIZON_HOURS))
    if rainy:
        notes.append({"level": "info", "code": "rain",
                      "message": f"Chuva prevista a partir das {rainy[0].hour}h (Open-Meteo): a procura por "
                                 "corridas tende a subir — o plano já considera isso."})
    return (weather,), [{"source": "open-meteo", "status": "ok", "detail": "Chuva e temperatura por hora."}], notes


def _prepare(data: NextStopInput, user, db):
    if (data.lat is None) != (data.lng is None):
        fail("coordinates_required", "Informe lat e lng juntos", 422)
    limit(db, f"driver-plan:{user.id}", maximum=PLAN_LIMIT[0], seconds=PLAN_LIMIT[1])
    saved = _saved(db.get(DriverProfile, user.id))
    profile = _validated(merge_profile(saved, {"vehicle": _dump(data.vehicle),
                                               "preferences": _dump(data.preferences)}))
    payload = {"soc_percent": data.soc_percent, "lat": data.lat, "lng": data.lng,
               "context": data.context.model_dump()}
    return profile, payload, _stations(db, data.lat, data.lng, data.radius_km)


@router.post("/driver/plan")
def plan(data: PlanInput, user=Depends(current_user), db=Depends(db_session)):
    profile, payload, stations = _prepare(data, user, db)
    current = local_now()
    signals, info, notes = _signals(data, current)
    try:
        result = build_plan({**payload, "mode": data.mode}, profile, stations, current, signals, notes)
    except ValueError as error:
        fail("invalid_driver_plan", str(error), 422)
    result["demand"]["signals"] = info
    result["generated_at"] = current.isoformat()
    return result


@router.post("/driver/next-stop")
def next_stop(data: NextStopInput, user=Depends(current_user), db=Depends(db_session)):
    profile, payload, stations = _prepare(data, user, db)
    current = local_now()
    signals, info, notes = _signals(data, current)
    try:
        result = build_next_stop(payload, profile, stations, current, signals)
    except ValueError as error:
        fail("invalid_driver_plan", str(error), 422)
    result["alerts"] = notes + result["alerts"]
    result["demand"]["signals"] = info
    return result
