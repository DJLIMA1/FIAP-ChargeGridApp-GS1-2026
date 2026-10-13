"""Preferências do motorista, comodidades e opções de recarga (postos)."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from .vehicles import VehicleProfile, normalize_connector

AMENITY_KINDS = ('restaurante', 'cafe', 'banheiro', 'shopping', 'conveniencia')
AMENITY_LABELS = {'restaurante': 'restaurante', 'cafe': 'café', 'banheiro': 'banheiro',
                  'shopping': 'shopping', 'conveniencia': 'conveniência'}
MEAL_KINDS = ('almoco', 'jantar', 'lanche')
MEAL_LABELS = {'almoco': 'Almoço', 'jantar': 'Jantar', 'lanche': 'Lanche'}
# Comodidades que permitem fazer a refeição durante a recarga.
MEAL_AMENITIES = {'almoco': ('restaurante', 'shopping'), 'jantar': ('restaurante', 'shopping'),
                  'lanche': ('cafe', 'conveniencia', 'restaurante', 'shopping')}
MAX_WALK_METERS = 400


def parse_hhmm(value) -> int:
    """'20:30' → 1230. Aceita também minutos inteiros."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minute = int(value)
    else:
        text = str(value or '').strip().lower().replace('h', ':')
        hours, _, minutes = text.partition(':')
        if not hours.isdigit() or (minutes and not minutes.isdigit()):
            raise ValueError(f'Horário inválido: {value!r}')
        minute = int(hours) * 60 + int(minutes or 0)
    if not 0 <= minute <= 24 * 60:
        raise ValueError(f'Horário inválido: {value!r}')
    return minute % (24 * 60)


def hhmm(minute: int) -> str:
    minute = int(minute) % (24 * 60)
    return f'{minute // 60:02d}:{minute % 60:02d}'


def _number(data, key, default, low, high):
    value = data.get(key, default)
    if value is None:
        return default
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f'{key} fora da faixa ({low}–{high})')
    return number


@dataclass(frozen=True)
class Meal:
    kind: str
    start_minute: int
    duration_minutes: int = 45
    flex_minutes: int = 30
    flexible: bool = False
    enabled: bool = True

    @property
    def label(self) -> str:
        return MEAL_LABELS.get(self.kind, self.kind.title())

    @property
    def window(self) -> tuple[int, int]:
        """Janela de início permitida em minutos do dia (pode passar de 1440)."""
        flex = max(self.flex_minutes, 120) if self.flexible else self.flex_minutes
        return self.start_minute - flex, self.start_minute + flex

    def to_dict(self) -> dict:
        return {'kind': self.kind, 'start': hhmm(self.start_minute), 'duration_minutes': self.duration_minutes,
                'flex_minutes': self.flex_minutes, 'flexible': self.flexible, 'enabled': self.enabled}

    @staticmethod
    def from_dict(data: dict) -> Meal:
        kind = str(data.get('kind') or 'lanche')
        if kind not in MEAL_KINDS:
            raise ValueError('Refeição deve ser almoco, jantar ou lanche')
        return Meal(kind=kind, start_minute=parse_hhmm(data.get('start', '12:00')),
                    duration_minutes=int(_number(data, 'duration_minutes', 45, 10, 120)),
                    flex_minutes=int(_number(data, 'flex_minutes', 30, 0, 240)),
                    flexible=bool(data.get('flexible', False)), enabled=bool(data.get('enabled', True)))


DEFAULT_MEALS = (Meal('almoco', 12 * 60 + 30, 60, 45), Meal('jantar', 20 * 60, 45, 30))


@dataclass(frozen=True)
class DriverPreferences:
    shift_start: int = 10 * 60
    shift_end: int = 22 * 60
    meals: tuple[Meal, ...] = DEFAULT_MEALS
    km_per_hour: float = 22.0
    earnings_per_hour: float = 38.0
    earnings_per_km: float | None = None
    reserve_percent: float = 15.0
    max_charge_percent: float = 80.0
    home_charging: bool = True
    home_price_per_kwh: float = 0.95
    city: str = 'São Paulo'

    @property
    def shift_minutes(self) -> int:
        span = (self.shift_end - self.shift_start) % (24 * 60)
        return span or 24 * 60

    @property
    def hourly_earnings(self) -> float:
        if self.earnings_per_hour:
            return self.earnings_per_hour
        return (self.earnings_per_km or 1.8) * self.km_per_hour

    @property
    def end_energy_value(self) -> float:
        """R$/kWh que a energia restante "vale" ao fim do turno (custo de repor depois)."""
        return self.home_price_per_kwh if self.home_charging else max(self.home_price_per_kwh, 1.8)

    def to_dict(self) -> dict:
        data = asdict(self)
        data.update(shift_start=hhmm(self.shift_start), shift_end=hhmm(self.shift_end),
                    meals=[meal.to_dict() for meal in self.meals])
        return data

    @staticmethod
    def from_dict(data: dict | None) -> DriverPreferences:
        data = dict(data or {})
        default = DriverPreferences()
        meals = data.get('meals')
        parsed = tuple(Meal.from_dict(m) for m in meals) if isinstance(meals, list) else default.meals
        if len(parsed) > 4:
            raise ValueError('No máximo 4 refeições por turno')
        preferences = DriverPreferences(
            shift_start=parse_hhmm(data.get('shift_start', hhmm(default.shift_start))),
            shift_end=parse_hhmm(data.get('shift_end', hhmm(default.shift_end))),
            meals=parsed,
            km_per_hour=_number(data, 'km_per_hour', default.km_per_hour, 5, 80),
            earnings_per_hour=_number(data, 'earnings_per_hour', default.earnings_per_hour, 0, 500),
            earnings_per_km=(None if data.get('earnings_per_km') is None
                             else _number(data, 'earnings_per_km', None, 0, 50)),
            reserve_percent=_number(data, 'reserve_percent', default.reserve_percent, 5, 50),
            max_charge_percent=_number(data, 'max_charge_percent', default.max_charge_percent, 50, 100),
            home_charging=bool(data.get('home_charging', default.home_charging)),
            home_price_per_kwh=_number(data, 'home_price_per_kwh', default.home_price_per_kwh, 0, 10),
            city=str(data.get('city') or default.city)[:60],
        )
        if preferences.reserve_percent + 10 > preferences.max_charge_percent:
            raise ValueError('A reserva mínima precisa ficar bem abaixo do alvo máximo de carga')
        if preferences.shift_minutes > 16 * 60:
            raise ValueError('O turno pode ter no máximo 16 horas')
        return preferences


@dataclass(frozen=True)
class Amenity:
    kind: str
    name: str = ''
    distance_m: int | None = None

    @property
    def label(self) -> str:
        text = AMENITY_LABELS.get(self.kind, self.kind)
        if self.name:
            text = f'{text} {self.name}'
        if self.distance_m is not None:
            text += f' a {self.distance_m} m'
        return text

    @staticmethod
    def from_dict(data) -> Amenity | None:
        if not isinstance(data, dict) or data.get('kind') not in AMENITY_KINDS:
            return None
        distance = data.get('distance_m')
        try:
            distance = None if distance is None else max(0, int(distance))
        except (TypeError, ValueError):
            distance = None
        return Amenity(str(data['kind']), str(data.get('name') or '')[:80], distance)


@dataclass(frozen=True)
class ChargerOption:
    """Um ponto compatível de um posto, já reduzido ao que o planejador precisa."""

    station_id: str
    station_name: str
    latitude: float
    longitude: float
    connector_type: str
    power_kw: float
    price_per_kwh: float
    connector_id: str | None = None
    public_code: str | None = None
    address: str = ''
    available: bool | None = True
    status: str = 'available'
    queue_minutes: float = 0.0
    max_duration_minutes: int = 240
    amenities: tuple[Amenity, ...] = ()
    # Tarifa por horário: ((início_min, fim_min, R$/kWh), ...); fim < início cruza a meia-noite.
    price_schedule: tuple[tuple[int, int, float], ...] = ()

    def price_at(self, minute_of_day: int) -> float:
        minute = minute_of_day % (24 * 60)
        for start, end, price in self.price_schedule:
            if (start <= minute < end) if start <= end else (minute >= start or minute < end):
                return price
        return self.price_per_kwh

    def meal_amenity(self, meal_kind: str) -> Amenity | None:
        accepted = MEAL_AMENITIES.get(meal_kind, ())
        found = [a for a in self.amenities if a.kind in accepted
                 and (a.distance_m is None or a.distance_m <= MAX_WALK_METERS)]
        return min(found, key=lambda a: (a.distance_m or 0, accepted.index(a.kind))) if found else None


_QUEUE_BY_STATUS = {'charging': 30.0, 'reserved': 20.0, 'reconciling': 15.0, 'occupied': 30.0}


def _float(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _schedule(raw):
    result = []
    for item in raw or ():
        try:
            result.append((parse_hhmm(item['start']), parse_hhmm(item['end']), float(item['price_per_kwh'])))
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(result)


def options_from_stations(records, vehicle: VehicleProfile) -> list[ChargerOption]:
    """Converte postos no formato da API (``GET /v1/stations``) em opções compatíveis.

    Cada posto gera no máximo uma opção: o melhor ponto compatível (disponível,
    mais potente para este carro, mais barato). Pontos offline/desativados ficam de fora.
    """
    options = []
    for station in records or ():
        if station.get('active') is False:
            continue
        lat, lng = _float(station.get('latitude')), _float(station.get('longitude'))
        if lat is None or lng is None:
            continue
        amenities = tuple(a for a in (Amenity.from_dict(x) for x in station.get('amenities') or ()) if a)
        best = None
        for point in station.get('connectors') or ():
            status = point.get('availability_status') or ('available' if point.get('available') else None)
            if (point.get('active') is False or point.get('retired') or point.get('online') is False
                    or status in ('disabled', 'offline', 'fault')):
                continue
            kind = normalize_connector(point.get('connector_type'))
            power, price = _float(point.get('power_kw')), _float(point.get('price_per_kwh'))
            if not vehicle.accepts(kind) or not power or power <= 0 or price is None or price < 0:
                continue
            effective = vehicle.effective_power(power, kind)
            available = True if status == 'available' else (None if status is None else False)
            rank = (available is not True, -effective, price, str(point.get('id')))
            if best is None or rank < best[0]:
                best = (rank, point, kind, effective, price, status, available)
        if best is None:
            continue
        _, point, kind, effective, price, status, available = best
        options.append(ChargerOption(
            station_id=str(station.get('id')), station_name=str(station.get('name') or 'Posto'),
            latitude=lat, longitude=lng, connector_type=kind, power_kw=effective, price_per_kwh=price,
            connector_id=str(point['id']) if point.get('id') is not None else None,
            public_code=point.get('public_code'), address=str(station.get('address') or ''),
            available=available, status=status or 'unknown',
            queue_minutes=0.0 if available else _QUEUE_BY_STATUS.get(status, 10.0),
            max_duration_minutes=int(_float(point.get('max_duration_minutes'), 240) or 240),
            amenities=amenities, price_schedule=_schedule(point.get('price_schedule')),
        ))
    return options


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    first, second = math.radians(lat1), math.radians(lat2)
    cosine = (math.sin(first) * math.sin(second)
              + math.cos(first) * math.cos(second) * math.cos(math.radians(lng2 - lng1)))
    return 6371 * math.acos(max(-1.0, min(1.0, cosine)))


@dataclass
class PlanRequest:
    """Entrada do planejador (agregada para facilitar testes)."""

    vehicle: VehicleProfile
    preferences: DriverPreferences
    soc_percent: float
    options: list[ChargerOption] = field(default_factory=list)
    origin: tuple[float, float] | None = None
