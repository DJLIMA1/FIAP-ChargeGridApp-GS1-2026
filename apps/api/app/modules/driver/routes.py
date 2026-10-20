"""Modo Motorista: perfil do veículo/turno, contexto (clima, demanda), plano de recarga e "próxima parada agora".

Toda a lógica de planejamento vem de ``chargegrid_core.driver`` (a mesma usada pelo
modo demo do app). Aqui só reunimos postos reais, perfil salvo e sinais ao vivo.
"""
import math
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from chargegrid_core.driver import (
    build_context,
    build_next_stop,
    build_plan,
    default_profile,
    merge_profile,
    presets,
    rain_note,
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
# O contexto é aberto a cada visita à tela (barato: só clima em cache + curva).
CONTEXT_LIMIT = (60, 60)


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
    return _live_signals(data.lat, data.lng, current, data.live_signals)


def _live_signals(lat, lng, current: datetime, enabled: bool = True):
    if not enabled:
        return (), [{"source": "open-meteo", "status": "desativado"}], []
    if lat is None:
        return (), [{"source": "open-meteo", "status": "sem_localizacao",
                     "detail": "Informe a localização para considerar o clima."}], []
    weather = weather_signal(lat, lng)
    if weather is None:
        return (), [{"source": "open-meteo", "status": "indisponivel",
                     "detail": "Clima indisponível agora; usando apenas a curva estimada."}], []
    note = rain_note(weather, current, LIVE_HORIZON_HOURS)
    return (weather,), [{"source": "open-meteo", "status": "ok", "detail": "Chuva e temperatura por hora."}], \
        [note] if note else []


def _weather_or_status(summary: dict | None, info: list[dict]) -> dict:
    """``demand.weather``: o resumo do clima ou, sem clima, o motivo (mesmo status de ``signals``)."""
    if summary is not None:
        return summary
    status = info[0] if info else {"status": "indisponivel"}
    return {"status": status["status"], "source": "open-meteo", "label": None, "detail": status.get("detail")}


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
    result["demand"]["weather"] = _weather_or_status(result["demand"].get("weather"), info)
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
    result["demand"]["weather"] = _weather_or_status(result["demand"].get("weather"), info)
    return result


@router.get("/driver/context")
def context(
    lat: float | None = Query(default=None, ge=-90, le=90, allow_inf_nan=False),
    lng: float | None = Query(default=None, ge=-180, le=180, allow_inf_nan=False),
    user=Depends(current_user),
    db=Depends(db_session),
):
    """O que o app já considera antes de planejar (turno, demanda agora, picos, clima, ganho/h).

    Só lê o perfil salvo; não grava nada. Sem localização não há clima (a resposta diz isso).
    """
    if (lat is None) != (lng is None):
        fail("coordinates_required", "Informe lat e lng juntos", 422)
    limit(db, f"driver-context:{user.id}", maximum=CONTEXT_LIMIT[0], seconds=CONTEXT_LIMIT[1])
    profile = _saved(db.get(DriverProfile, user.id)) or validate_profile(default_profile())
    current = local_now()
    signals, info, notes = _live_signals(lat, lng, current)
    result = build_context(profile, current, signals)
    result["demand"]["signals"] = info
    result["weather"] = _weather_or_status(result["weather"], info)
    result["alerts"] = notes
    return result
