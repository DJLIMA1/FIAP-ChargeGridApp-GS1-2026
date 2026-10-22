"""Fonte de dados somente leitura do assistente, sempre no escopo do usuário autenticado.

Não usa ``lock_point``: leituras do assistente não disparam a conciliação de
expiração (que pode emitir comandos ao equipamento).

Ferramentas do dono reusam os MESMOS serviços do dashboard (``owner/service``,
``economics``, ``forecast``) com ``scope_for`` (operador + posto do próprio dono).
Erros de negócio (``fail()`` → HTTPException 403/404/413/422/429) viram
``ToolDataError``: o modelo recebe a mensagem curta e a conversa continua.
"""

import math
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, select

from chargegrid_core import economics
from chargegrid_core.ai import ToolDataError
from chargegrid_core.ai.stations import compact_point

from ...http_helpers import reservation_row, session_row, session_rows, station_rows
from ...models import (
    ChargingSession,
    Connector,
    Coupon,
    DriverProfile,
    Reservation,
    SimulatedWallet,
    Station,
    now,
)
from ...service import RES_ACTIVE, SESSION_ACTIVE, owned, row
from ..auth.routes import limit
from ..driver.routes import _saved as saved_driver_profile
from ..economics import service as economics_service
from ..forecast import service as forecast_service
from ..kiosk_totem.account import wallet_view
from ..owner import routes as owner_routes
from ..owner import service as owner_service
from ..receipts import service as receipt_service
from ..users.routes import me_summary, my_vehicle

MAX_STATIONS = 40
MAX_OWNER_SESSIONS = 2000
FINISHED = ("completed", "interrupted")
# Mesmos limites por usuário das rotas de previsão (CPU de backtest).
BEST_TIMES_LIMIT = (60, 60)
FORECAST_LIMIT = (30, 60)


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _guarded(function):
    """Erros de negócio da API viram ``ToolDataError`` (sem detalhes internos)."""
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            message = detail.get("message") if exc.status_code in (409, 413, 422, 429) else None
            raise ToolDataError(message or ("posto não encontrado entre os seus postos" if exc.status_code in (403, 404)
                                            else "dado indisponível no momento")) from exc
    wrapper.__name__ = function.__name__
    wrapper.__doc__ = function.__doc__
    return wrapper


def vehicle_for(db, user):
    """Carro cadastrado do usuário, lido do mesmo contrato de ``GET /v1/me/vehicle``.

    Função isolada: se o cadastro passar a ter vários carros (com um principal), só ela muda."""
    profile = my_vehicle(user=user, db=db)
    return {"vehicle": profile.get("vehicle"), "saved": bool(profile.get("saved"))}


class DbSource:
    def __init__(self, db, user):
        self.db, self.user = db, user

    # ---------------------------------------------------------------- público
    def list_stations(self, near=None, radius_km=None):
        query = select(Station).where(Station.active.is_(True), Station.owner_id.is_not(None)).order_by(Station.id)
        if near and radius_km:
            dlat = radius_km / 111.0
            dlng = radius_km / max(1.0, 111.0 * math.cos(math.radians(near["lat"])))
            query = query.where(Station.latitude.between(near["lat"] - dlat, near["lat"] + dlat),
                                Station.longitude.between(near["lng"] - dlng, near["lng"] + dlng))
            # Os MAX_STATIONS mais próximos (aproximação plana), não os primeiros por id.
            scale = math.cos(math.radians(near["lat"]))
            closeness = (func.power(Station.latitude - near["lat"], 2)
                         + func.power((Station.longitude - near["lng"]) * scale, 2))
            query = query.order_by(None).order_by(closeness, Station.id)
        # Lote: número fixo de consultas para todos os postos (antes, uma rodada por posto).
        return station_rows(self.db, self.db.scalars(query.limit(MAX_STATIONS)).all())

    def _public(self, ids):
        keys = [key for key in (_uuid(value) for value in ids) if key]
        if not keys:
            return []
        stations = self.db.scalars(select(Station).where(Station.id.in_(keys), Station.active.is_(True),
                                                         Station.owner_id.is_not(None))).all()
        return station_rows(self.db, stations)

    def get_station(self, station_id):
        rows = self._public([station_id])
        return rows[0] if rows else None

    def get_stations(self, ids):
        return self._public(list(ids)[:5])

    def get_connector(self, connector_id):
        key = _uuid(connector_id)
        connector = self.db.get(Connector, key) if key else None
        if not connector or not connector.active or connector.removed_at is not None:
            return None
        # Mesmo recorte da listagem pública; o preço é o final de agora (como na tela do posto).
        station = self.get_station(connector.station_id)
        point = next((p for p in (station or {}).get("connectors") or [] if p.get("id") == str(connector.id)), None)
        if station is None or point is None:
            return None
        return {**compact_point(point), "station_id": station["id"], "station_name": station["name"]}

    # -------------------------------------------------------------- motorista
    def current_reservation(self):
        obj = self.db.scalar(select(Reservation).where(Reservation.user_id == self.user.id,
                                                       Reservation.status.in_(RES_ACTIVE)))
        return reservation_row(self.db, obj) if obj else None

    def current_session(self):
        obj = self.db.scalar(select(ChargingSession).where(ChargingSession.user_id == self.user.id,
                                                           ChargingSession.status.in_(SESSION_ACTIVE)))
        return session_row(self.db, obj) if obj else None

    def recent_sessions(self, limit):
        query = (select(ChargingSession).where(ChargingSession.user_id == self.user.id)
                 .order_by(ChargingSession.created_at.desc(), ChargingSession.id.desc()).limit(min(int(limit), 100)))
        return session_rows(self.db, self.db.scalars(query).all())  # lote: sem N+1 por sessão

    def month_summary(self):
        return me_summary(user=self.user, db=self.db)

    def driver_profile(self):
        """Perfil salvo do Modo Motorista (validado), usado por ``plan_driver_shift``."""
        return saved_driver_profile(self.db.get(DriverProfile, self.user.id))

    def vehicle(self):
        return vehicle_for(self.db, self.user)

    def wallet(self):
        # SELECT puro: ``account.wallet()`` cria a linha (INSERT); o assistente só lê.
        obj = self.db.scalar(select(SimulatedWallet).where(SimulatedWallet.user_id == self.user.id))
        return wallet_view(obj) if obj else {"balance": "0.00", "simulated": True, "transactions": []}

    def session_receipt(self, session_id=None):
        """Recibo (mesmo de ``GET /charging-sessions/{id}/receipt``) de uma recarga DO PRÓPRIO usuário."""
        if session_id:
            key = _uuid(session_id)
            obj = self.db.get(ChargingSession, key) if key else None
            if obj is None or obj.user_id != self.user.id:
                return None
        else:
            obj = self.db.scalar(select(ChargingSession).where(ChargingSession.user_id == self.user.id,
                                                               ChargingSession.status.in_(FINISHED))
                                 .order_by(ChargingSession.ended_at.desc().nullslast(), ChargingSession.id.desc())
                                 .limit(1))
            if obj is None:
                return None
        return receipt_service.build(self.db, obj)

    @_guarded
    def station_best_times(self, station_id):
        key = _uuid(station_id)
        station = self.db.get(Station, key) if key else None
        if not station or not station.active or station.owner_id is None:
            return None
        limit(self.db, f"best-times:{self.user.id}", maximum=BEST_TIMES_LIMIT[0], seconds=BEST_TIMES_LIMIT[1])
        return forecast_service.best_times(self.db, station, 12)

    # ------------------------------------------------------------------- dono
    def _scope(self, station_id):
        return owner_routes.scope_for(self.db, self.user, _uuid(station_id) if station_id else None)

    def owner_stations(self):
        if not self.user.operator_enabled:
            return []
        query = select(Station).where(Station.owner_id == self.user.id).order_by(Station.id).limit(MAX_STATIONS)
        return station_rows(self.db, self.db.scalars(query).all())

    def owner_sessions(self, since: datetime):
        if not self.user.operator_enabled:
            return []
        # Agregados não precisam do serializador completo (evita N consultas por sessão).
        query = (select(ChargingSession, Connector.station_id).join(Connector).join(Station)
                 .where(Station.owner_id == self.user.id, ChargingSession.created_at >= since)
                 .order_by(ChargingSession.created_at.desc()).limit(MAX_OWNER_SESSIONS))
        return [{**row(obj), "station_id": str(station_id)} for obj, station_id in self.db.execute(query)]

    def owner_station_names(self):
        if not self.user.operator_enabled:
            return []
        rows = self.db.execute(select(Station.id, Station.name).where(Station.owner_id == self.user.id)
                               .order_by(Station.name, Station.id).limit(MAX_STATIONS)).all()
        return [{"id": str(station_id), "name": name} for station_id, name in rows]

    @_guarded
    def owner_overview(self, start, end, station_id=None):
        return owner_service.overview(self.db, self._scope(station_id), owner_routes.window_for(start, end))

    @_guarded
    def owner_ranking(self, start, end, station_id=None):
        return owner_service.ranking(self.db, self._scope(station_id), owner_routes.window_for(start, end), now())

    @_guarded
    def owner_timeseries(self, start, end, granularity="day", station_id=None):
        window = owner_routes.window_for(start, end, granularity)
        return owner_service.timeseries(self.db, self._scope(station_id), window, granularity)

    @_guarded
    def owner_heatmap(self, start, end, station_id=None):
        return owner_service.heatmap(self.db, self._scope(station_id), owner_routes.window_for(start, end))

    @_guarded
    def owner_alerts(self, station_id=None):
        return owner_service.alerts(self.db, self._scope(station_id))

    @_guarded
    def owner_live(self, station_id=None):
        return owner_service.live(self.db, self._scope(station_id))

    @_guarded
    def owner_forecast(self, station_id):
        station = owned(self.db, self.user, _uuid(station_id))
        limit(self.db, f"owner-forecast:{self.user.id}", maximum=FORECAST_LIMIT[0], seconds=FORECAST_LIMIT[1])
        return forecast_service.owner_forecast(self.db, station, 36)

    @_guarded
    def owner_margin(self, start, end, station_id=None):
        report = economics_service.margin_report(self.db, self._scope(station_id), owner_routes.window_for(start, end))
        return economics.serialize(report)

    def owner_coupons(self):
        if not self.user.operator_enabled:
            return []
        coupons = self.db.scalars(select(Coupon).where(Coupon.operator_id == self.user.id)
                                  .order_by(Coupon.valid_until.desc()).limit(50)).all()
        return [row(coupon) for coupon in coupons]

    def owner_session(self, session_id=None):
        """Recibo de uma recarga num posto DO PRÓPRIO dono (sem identidade do motorista)."""
        if not self.user.operator_enabled:
            return None
        query = (select(ChargingSession).join(Connector, Connector.id == ChargingSession.connector_id)
                 .join(Station, Station.id == Connector.station_id).where(Station.owner_id == self.user.id))
        if session_id:
            key = _uuid(session_id)
            if key is None:
                return None
            query = query.where(ChargingSession.id == key)
        obj = self.db.scalar(query.order_by(ChargingSession.created_at.desc(), ChargingSession.id.desc()).limit(1))
        return receipt_service.build(self.db, obj) if obj else None
