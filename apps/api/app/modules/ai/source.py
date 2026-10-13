"""Fonte de dados somente leitura do assistente, sempre no escopo do usuário autenticado.

Não usa ``lock_point``: leituras do assistente não disparam a conciliação de
expiração (que pode emitir comandos ao equipamento).
"""

import math
import uuid
from datetime import datetime

from sqlalchemy import select

from chargegrid_core.ai.stations import compact_point

from ...http_helpers import point_row, reservation_row, session_row, station_row
from ...models import ChargingSession, Connector, DriverProfile, Reservation, Station
from ...service import RES_ACTIVE, SESSION_ACTIVE, row
from ..driver.routes import _saved as saved_driver_profile
from ..users.routes import me_summary

MAX_STATIONS = 40
MAX_OWNER_SESSIONS = 2000


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


class DbSource:
    def __init__(self, db, user):
        self.db, self.user = db, user

    def list_stations(self, near=None, radius_km=None):
        query = select(Station).where(Station.active.is_(True), Station.owner_id.is_not(None)).order_by(Station.id)
        if near and radius_km:
            dlat = radius_km / 111.0
            dlng = radius_km / max(1.0, 111.0 * math.cos(math.radians(near["lat"])))
            query = query.where(Station.latitude.between(near["lat"] - dlat, near["lat"] + dlat),
                                Station.longitude.between(near["lng"] - dlng, near["lng"] + dlng))
        return [station_row(self.db, obj) for obj in self.db.scalars(query.limit(MAX_STATIONS))]

    def get_station(self, station_id):
        key = _uuid(station_id)
        obj = self.db.get(Station, key) if key else None
        return station_row(self.db, obj) if obj and obj.active else None

    def get_connector(self, connector_id):
        key = _uuid(connector_id)
        connector = self.db.get(Connector, key) if key else None
        if not connector:
            return None
        station = self.db.get(Station, connector.station_id)
        return {**compact_point(point_row(self.db, connector)), "station_id": str(station.id), "station_name": station.name}

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
                 .order_by(ChargingSession.created_at.desc(), ChargingSession.id.desc()).limit(limit))
        return [session_row(self.db, obj) for obj in self.db.scalars(query)]

    def month_summary(self):
        return me_summary(user=self.user, db=self.db)

    def owner_stations(self):
        if not self.user.operator_enabled:
            return []
        query = select(Station).where(Station.owner_id == self.user.id).order_by(Station.id).limit(MAX_STATIONS)
        return [station_row(self.db, obj) for obj in self.db.scalars(query)]

    def owner_sessions(self, since: datetime):
        if not self.user.operator_enabled:
            return []
        # Agregados não precisam do serializador completo (evita N consultas por sessão).
        query = (select(ChargingSession, Connector.station_id).join(Connector).join(Station)
                 .where(Station.owner_id == self.user.id, ChargingSession.created_at >= since)
                 .order_by(ChargingSession.created_at.desc()).limit(MAX_OWNER_SESSIONS))
        return [{**row(obj), "station_id": str(station_id)} for obj, station_id in self.db.execute(query)]

    def driver_profile(self):
        """Perfil salvo do Modo Motorista (validado), usado por ``plan_driver_shift``."""
        return saved_driver_profile(self.db.get(DriverProfile, self.user.id))
