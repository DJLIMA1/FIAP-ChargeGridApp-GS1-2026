"""In-memory demonstration account. This module never contacts an API or device.

Use ``DemoApi(clock=callable, start_at=aware_datetime)`` for deterministic tests.
The clock returns monotonic seconds; operations advance from elapsed time, not
from the number of requests. Login starts a fresh scenario, logout discards it.
All credentials and identifiers below are deliberately fictitious and public.
"""

import json
import math
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

from chargegrid_core import power as power_rules
from chargegrid_core import pricing

from .api_client import ApiError
from .owner_api import OwnerApiMixin
from .services.discovery import discover
from .session import Session

DEMO_EMAIL = 'demo@chargegrid.example'
DEMO_PASSWORD = 'demo1234'
DEMO_PRESENCE_CODE = '#F12345'
DEMO_CLAIM_TOKEN = 'DEMO-CLAIM-' + '0' * 32
DEMO_LOCATIONS = (
    {'name': 'Villa Lobos', 'address': 'Av. Prof Fonseca Rodrigues, 4777, Pinheiros, São Paulo - SP',
     'latitude': -23.5467, 'longitude': -46.7224},
    {'name': 'Marginal Pinheiros', 'address': 'Av. das Nações Unidas, 4777, Pinheiros, São Paulo - SP',
     'latitude': -23.5613, 'longitude': -46.6996},
    {'name': 'Villa Olímpia', 'address': 'Rua Olimpíadas, 205, Vila Olímpia, São Paulo - SP',
     'latitude': -23.5955, 'longitude': -46.6857},
)
# (conector, potência kW, preço R$/kWh, online) por posto; a conta demo é dona só da Marginal Pinheiros.
_DEMO_POINTS = (
    (('CCS2', '60.000', '1.8900', True), ('CCS2', '60.000', '1.8900', False),
     ('Tipo 2', '22.000', '1.8900', True), ('Tipo 2', '22.000', '1.8900', True)),
    (('CCS2', '60.000', '1.8900', True), ('Tipo 2', '22.000', '1.8900', True), ('Tipo 2', '22.000', '1.8900', False)),
    (('CCS2', '50.000', '2.0900', True), ('Tipo 2', '22.000', '2.0900', True)),
)
_DEMO_OWNED = (1,)

_USER = 'demo-user'
_RES_ACTIVE = {'pending_device', 'confirmed', 'cancelling'}
_SESSION_ACTIVE = {'starting', 'charging', 'stopping'}
_TERMINAL = {'completed', 'failed', 'interrupted'}
_REPORT_TZ = timezone(timedelta(hours=-3))
_PUBLIC_POINT = ('id', 'public_code', 'connector_type', 'power_kw', 'price_per_kwh', 'max_duration_minutes')


_DEMO_ADDRESSES = (
    ('Avenida Paulista', '1000', 'Bela Vista', '01310-100', -23.5648865, -46.651918),
    ('Rua Augusta', '1500', 'Consolação', '01304-001', -23.5565983, -46.6587),
    ('Avenida Brigadeiro Faria Lima', '3477', 'Itaim Bibi', '04538-133', -23.5868, -46.6812),
    ('Avenida Rebouças', '3970', 'Pinheiros', '05402-600', -23.5726463, -46.6966),
    *((loc['address'].split(', ')[0], loc['address'].split(', ')[1], loc['address'].split(', ')[2], None,
       loc['latitude'], loc['longitude']) for loc in DEMO_LOCATIONS),
)


def demo_address_suggestions(query):
    """Autocomplete da conta demo: endereços fixos de São Paulo, sem consultar serviços externos."""
    import unicodedata

    def plain(value):
        return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))
    words = [w for w in plain(query).replace(',', ' ').split() if not w.isdigit()]
    items = []
    if len(query.strip()) >= 3 and words:
        for street, number, district, postcode, lat, lng in _DEMO_ADDRESSES:
            haystack = plain(f'{street} {district}')
            if all(any(token.startswith(w) or w in token for token in haystack.split()) for w in words):
                item = {'street': street, 'number': number, 'district': district, 'city': 'São Paulo', 'state': 'SP',
                        'postcode': postcode, 'latitude': lat, 'longitude': lng}
                item['label'] = f'{street}, {number}, {district}, São Paulo - SP'
                items.append(item)
    return {'items': items[:6], 'available': True, 'attribution': 'Endereços de demonstração (sem consulta externa)'}


def _fail(message, code='validation_error', status=422):
    raise ApiError(message, status, code)


def _number(value, label, minimum, maximum, *, integer=False, positive=False):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        _fail(f'Informe {label} válido.')
    if (not number.is_finite() or not Decimal(str(minimum)) <= number <= Decimal(str(maximum))
            or (positive and number <= 0) or (integer and number != number.to_integral_value())):
        _fail(f'Confira {label} e os limites permitidos.')
    return int(number) if integer else number


def _text(value, label, maximum, *, required=True):
    if not isinstance(value, str) or len(value.strip()) > maximum or (required and not value.strip()):
        _fail(f'Confira {label}.')
    return value.strip()


def _date(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, ValueError, TypeError):
        _fail('Informe uma data válida com fuso horário.', 'invalid_time')
    if parsed.tzinfo is None:
        _fail('Informe fuso horário.', 'invalid_time')
    return parsed


def _local(moment):
    """Horário local do posto (Brasília, sem tzdata), como ``LOCAL_TIMEZONE`` da API."""
    return moment.astimezone(_REPORT_TZ).replace(tzinfo=None)


def _decimal(value, places):
    return format(Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP), 'f')


def _amenities(value):
    from chargegrid_core.driver import AMENITY_KINDS
    if not isinstance(value, list) or len(value) > 12:
        _fail('Informe até 12 comodidades.')
    result = []
    for item in value:
        if not isinstance(item, dict) or item.get('kind') not in AMENITY_KINDS or set(item) - {'kind', 'name', 'distance_m'}:
            _fail('Comodidade inválida.')
        distance = item.get('distance_m')
        if distance is not None:
            distance = int(_number(distance, 'a distância', 0, 5000, integer=True))
        result.append({'kind': item['kind'], 'name': _text(item.get('name') or '', 'o nome', 80, required=False),
                       'distance_m': distance})
    return result


def _fields(body, allowed):
    if set(body) - set(allowed):
        _fail('Este formulário contém campos não reconhecidos na demonstração.')


class DemoApi(OwnerApiMixin):
    is_demo = True

    @property
    def ai_enabled(self):
        """Chat with real AI only in the local preview when the AI key is in the environment."""
        from .services import demo_ai_bridge
        return demo_ai_bridge.chat_available()

    def __init__(self, clock=None, start_at=None):
        self.session = Session()
        self._clock = clock or time.monotonic
        self._start_at = start_at
        if start_at is not None and start_at.tzinfo is None:
            raise ValueError('start_at requires a timezone')
        self.operation_keys = {}
        self.charging_operation_sessions = {}
        self.last_session_id = None
        self.last_reservation_id = None
        self._reset_state()

    def _reset_state(self):
        self._origin = float(self._clock())
        self._wall = self._start_at or datetime.now(timezone.utc)
        self._elapsed = 0.0
        self._counter = 0
        self._stations, self._points, self._devices = {}, {}, {}
        self._reservations, self._sessions, self._coupons = {}, {}, {}
        self._session_events = {}
        self._reservation_runtime, self._session_runtime, self._resets = {}, {}, {}
        self._claims = {DEMO_CLAIM_TOKEN: None}
        self._pricing = {}  # dados base da tarifa dinâmica por posto (como stations.pricing)
        self._idempotency = {}
        self.operation_keys.clear()
        self.charging_operation_sessions.clear()
        self.last_session_id = self.last_reservation_id = None
        self._profile = {'id': _USER, 'name': 'João Pedro Sousa', 'account_type': 'vendor',
                         'operator_enabled': True, 'phone': '(11) 91234-5678', 'vehicle_description': 'Veículo simulado',
                         'created_at': self._iso()}
        for index, location in enumerate(DEMO_LOCATIONS):
            station = self._make_station(dict(location), active=True)
            if index not in _DEMO_OWNED:
                station['owner_id'] = 'demo-network'
            for kind, power, price, online in _DEMO_POINTS[index]:
                self._make_point(station['id'], connector_type=kind, power_kw=power, price_per_kwh=price, online=online)
            if index == 0:
                station['amenities'] = [{'kind': 'cafe', 'name': 'Café do Parque', 'distance_m': 60},
                                        {'kind': 'banheiro', 'name': '', 'distance_m': None}]
        # Modo Motorista: perfil salvo e rede parceira fictícia (criada no primeiro uso).
        self._driver_profile = self._driver_updated_at = None
        self._driver_network = False
        stations = list(self._stations.values())
        self._coupons['demo-coupon-welcome'] = {
            'id': 'demo-coupon-welcome', 'operator_id': _USER, 'station_id': None,
            'code': 'DEMO10', 'description': '10% de desconto na recarga simulada',
            'discount_percent': 10, 'valid_until': self._iso(30 * 86400), 'active': True,
        }
        for index in range(2):
            primary = next(p for p in self._points.values() if p['station_id'] == stations[index]['id'] and p['active'])
            sid = self._id('session')
            ended = -(index + 1) * 3600
            self._sessions[sid] = {
                'id': sid, 'user_id': _USER, 'connector_id': primary['id'], 'reservation_id': None,
                'status': 'completed', 'created_at': self._iso(ended - 1201),
                'started_at': self._iso(ended - 1200), 'ended_at': self._iso(ended),
                'max_duration_minutes': 20, 'max_cost': None, 'price_per_kwh': '1.8900',
                'discount_percent': 0, 'energy_wh': '2400.000', 'soc_percent': '24.00',
                'start_soc_percent': None, 'battery_kwh': None, 'soc_source': None,
                'source': 'simulated', 'last_measurement_at': self._iso(ended),
                'cost_estimate': '4.5360', 'end_reason': 'duration_limit', 'power_limit_kw': None,
            }

    def _id(self, kind):
        self._counter += 1
        return f'demo-{kind}-{self._counter}'

    def new_key(self):
        return self._id('operation')

    def new_claim_token(self):
        self._counter += 1
        token = 'DEMO-CLAIM-' + f'{self._counter:032d}'
        self._claims[token] = None
        return token

    def _iso(self, elapsed=None):
        return (self._wall + timedelta(seconds=self._elapsed if elapsed is None else elapsed)).isoformat()

    def _now(self):
        return self._wall + timedelta(seconds=self._elapsed)

    def _tokens(self):
        return {'access_token': 'DEMO-ACCESS-TOKEN-NOT-VALID-ON-ANY-SERVER',
                'refresh_token': 'DEMO-REFRESH-TOKEN-NOT-VALID-ON-ANY-SERVER',
                'expires_in': 86400, 'token_type': 'bearer',
                'user': {'id': _USER, 'email': DEMO_EMAIL}}

    async def login(self, email, password):
        result = await self.request('POST', 'auth/login', {'email': email, 'password': password}, auth=False)
        self.session.update(result)

    async def refresh(self, old_token=None):
        if not self.session.access_token:
            _fail('Entre na conta de demonstração para continuar.', 'unauthorized', 401)
        self.session.update(self._tokens())

    async def close(self):
        self.session.clear()
        self._profile.clear()
        self.operation_keys.clear()
        self.charging_operation_sessions.clear()
        self.last_session_id = self.last_reservation_id = None
        for store in (self._stations, self._points, self._devices, self._reservations, self._sessions,
                      self._session_events, self._coupons, self._reservation_runtime, self._session_runtime, self._resets,
                      self._claims, self._idempotency):
            store.clear()

    def clear_operation(self, path):
        self.operation_keys = {signature: key for signature, key in self.operation_keys.items()
                               if signature[1] != path}
        if path == 'charging-sessions':
            self.last_session_id = None
            self.charging_operation_sessions.clear()
        elif path == 'reservations':
            self.last_reservation_id = None

    def _record_result(self, method, path, result, signature):
        if method == 'POST' and path == 'reservations':
            self.last_reservation_id = result['id']
        elif method == 'GET' and path == 'reservations/current' and result is None:
            self.clear_operation('reservations')
        elif method == 'POST' and path == 'charging-sessions':
            self.last_session_id = result['id']
            self.charging_operation_sessions[signature] = result['id']
            self.clear_operation('reservations')
        elif method == 'GET' and path.startswith('charging-sessions/') and isinstance(result, dict):
            self.last_session_id = result['id']
            if result['status'] in _TERMINAL:
                for request, session_id in tuple(self.charging_operation_sessions.items()):
                    if session_id == result['id']:
                        self.operation_keys.pop(request, None)
                        self.charging_operation_sessions.pop(request, None)
        return deepcopy(result)

    async def request(self, method, path, body=None, *, key=None, params=None, auth=True):
        method, path = method.upper(), path.strip('/')
        if path.startswith('v1/'):
            path = path[3:]
        if body is not None and not isinstance(body, dict):
            _fail('O corpo da demonstração deve ser um objeto.')
        data, params = deepcopy(body or {}), dict(params or {})
        if (method, path) == ('POST', 'auth/login'):
            if str(data.get('email', '')).strip().casefold() != DEMO_EMAIL or data.get('password') != DEMO_PASSWORD:
                _fail('Use as credenciais públicas da conta de demonstração.', 'auth_rejected', 401)
            self._reset_state()
            return self._tokens()
        if not self.session.access_token:
            _fail('Entre na conta de demonstração para continuar.', 'unauthorized', 401)
        if (method, path) == ('POST', 'auth/logout'):
            await self.close()
            return {'message': 'Demonstração encerrada; dados locais descartados.'}
        if (method, path) == ('POST', 'auth/refresh'):
            return self._tokens()
        if (method, path) == ('POST', 'auth/password/update'):
            _text(data.get('password'), 'a senha', 128)
            if len(data['password']) < 8:
                _fail('A senha deve ter pelo menos oito caracteres.')
            return {'message': 'Simulação concluída. As credenciais públicas da demonstração não mudam.'}
        self._advance()
        if path.startswith('ai/'):
            from .services import demo_ai_bridge
            return await demo_ai_bridge.handle(self, method, path, data)
        signature = (method, path, json.dumps(body, sort_keys=True, separators=(',', ':')))
        if key:
            key = self.operation_keys.setdefault(signature, key)
        idempotent = method == 'POST' and (path in ('reservations', 'charging-sessions')
                                            or (path.startswith('charging-sessions/') and path.endswith('/stop')))
        remembered = (method, path, key)
        if idempotent:
            if not isinstance(key, str) or not 0 < len(key) <= 100:
                _fail('Informe uma chave para repetir esta operação com segurança.', 'idempotency_key_required')
            old = self._idempotency.get(remembered)
            if old:
                original, kind, resource_id = old
                if original != signature[2]:
                    _fail('Chave já usada com outro corpo.', 'idempotency_conflict', 409)
                record = (self._reservations if kind == 'reservation' else self._sessions)[resource_id]
                return self._record_result(method, path, self._operation_row(record, kind), signature)
        result = self._dispatch(method, path, data, params)
        if idempotent:
            kind = 'reservation' if path == 'reservations' else 'session'
            self._idempotency[remembered] = (signature[2], kind, result['id'])
        return self._record_result(method, path, result, signature)

    def _advance(self):
        self._elapsed = max(self._elapsed, float(self._clock()) - self._origin)
        for rid, reservation in self._reservations.items():
            runtime = self._reservation_runtime[rid]
            if reservation['status'] == 'cancelling' and self._elapsed >= runtime['cancel_at']:
                reservation['status'] = 'cancelled'
            elif reservation['status'] in ('pending_device', 'confirmed'):
                if self._elapsed >= runtime['expires_at']:
                    reservation['status'] = 'expired'
                elif self._elapsed >= runtime['confirm_at']:
                    reservation.update(status='confirmed', expires_at=self._iso(runtime['expires_at']))
        for sid, session in self._sessions.items():
            if session['status'] not in _SESSION_ACTIVE:
                continue
            runtime = self._session_runtime[sid]
            start = runtime['start_at']
            if runtime.get('never_started'):
                if self._elapsed >= runtime['stop_at']:
                    session.update(status='failed', ended_at=self._iso(runtime['stop_at']),
                                   end_reason=runtime.get('stop_reason', 'requested'))
                    self._event(sid, 'ended', at=session['ended_at'])
                continue
            if self._elapsed < start:
                continue
            session['started_at'] = self._iso(start)
            if session['status'] == 'starting':
                session['status'] = 'charging'
                self._event(sid, 'start_applied', at=session['started_at'])
            effective_price = Decimal(session['price_per_kwh']) * (100 - session['discount_percent']) / 100
            power = runtime['power_kw']
            deadlines = [(float(start + session['max_duration_minutes'] * 60), 'duration_limit')]
            if session['max_cost'] is not None and effective_price > 0:
                deadlines.append((start + float(Decimal(session['max_cost']) * 3600 / (effective_price * power)), 'cost_limit'))
            if runtime.get('stop_at') is not None:
                deadlines.append((runtime['stop_at'], runtime.get('stop_reason', 'requested')))
            full_at = self._battery_full_at(session, start, power)
            if full_at is not None:
                deadlines.append((full_at, 'battery_full'))
            deadline, reason = min(deadlines, key=lambda item: item[0])
            observed = min(self._elapsed, deadline)
            seconds = Decimal(str(max(0, observed - start)))
            energy = (power * 1000 * seconds / 3600).quantize(Decimal('0.001'), rounding=ROUND_DOWN)
            cost = energy / 1000 * effective_price
            if session['max_cost'] is not None:
                cost = min(cost, Decimal(session['max_cost']))
            session.update(energy_wh=_decimal(energy, '0.001'), cost_estimate=_decimal(cost, '0.0001'),
                           soc_percent=self._soc(session, energy), last_measurement_at=self._iso(observed))
            if self._elapsed >= deadline:
                session.update(status='completed', ended_at=self._iso(deadline), end_reason=reason)
                self._event(sid, 'ended', at=session['ended_at'])
        for device_id, reset in self._resets.items():
            if reset['status'] == 'pending' and self._elapsed >= reset['due']:
                reset['status'] = 'applied'
                self._devices[device_id]['revoked'] = True
                self._points[self._devices[device_id]['connector_id']]['retired'] = True

    @staticmethod
    def _soc(session, energy):
        """Same rule as the API: ``simulated`` derives from energy, ``phone`` keeps the app value."""
        if session.get('soc_source') == 'phone':
            return session['soc_percent']
        if session.get('soc_source') == 'simulated' and session.get('start_soc_percent') and session.get('battery_kwh'):
            soc = Decimal(session['start_soc_percent']) + energy / 1000 / Decimal(session['battery_kwh']) * 100
            return _decimal(min(Decimal(100), soc), '0.01')
        if session.get('soc_source') == 'simulated':
            return session['soc_percent']
        # Sessions without battery data keep the historical demo curve.
        return _decimal(min(Decimal(100), Decimal(20) + energy / 600), '0.01')

    @staticmethod
    def _battery_full_at(session, start, power):
        """Elapsed second at which a simulated battery reaches 100 % (None if unknown)."""
        if (session.get('soc_source') != 'simulated' or session.get('start_soc_percent') is None
                or not session.get('battery_kwh') or not power):
            return None
        missing_kwh = (100 - Decimal(session['start_soc_percent'])) / 100 * Decimal(session['battery_kwh'])
        return start + float(missing_kwh / power * 3600)

    def _report_soc(self, session_id, body):
        _fields(body, ('soc_percent',))
        if 'soc_percent' not in body:
            _fail('Informe o nível da bateria.')
        soc = _decimal(_number(body['soc_percent'], 'o nível da bateria', 0, 100), '0.01')
        session = self._get(self._sessions, session_id, 'Sessão não encontrada')
        if session['status'] not in ('starting', 'charging'):
            _fail('A recarga não está em andamento.', 'session_not_active', 409)
        session.update(soc_percent=soc, soc_source='phone')
        if session.get('start_soc_percent') is None:
            session['start_soc_percent'] = soc
        if Decimal(soc) >= 100:
            runtime = self._session_runtime[session['id']]
            runtime.update(stop_at=self._elapsed + 1, never_started=session['status'] == 'starting',
                           stop_reason='battery_full')
            session.update(status='stopping', end_reason='battery_full')
            self._event(session['id'], 'stop_requested')
        return self._operation_row(session, 'session')

    def _event(self, session_id, kind, *, at=None):
        self._session_events.setdefault(session_id, []).append({
            'kind': kind, 'source': 'simulator', 'observed_at': at or self._iso(),
        })

    def _make_station(self, data, *, active=True):
        sid = self._id('station')
        station = {'id': sid, 'owner_id': _USER, 'name': data['name'], 'address': data['address'],
                   'latitude': float(data['latitude']), 'longitude': float(data['longitude']), 'active': active,
                   'amenities': [], 'max_power_kw': None, 'power_limit_notify': False}
        self._stations[sid] = station
        return station

    def _make_point(self, station_id, *, active=True, online=True, connector_type='Tipo 2', power_kw='7.200',
                    price_per_kwh='1.5000'):
        pid = self._id('point')
        point = {'id': pid, 'station_id': station_id, 'public_code': 'DEMO-' + pid.rsplit('-', 1)[-1],
                 'connector_type': connector_type, 'power_kw': power_kw, 'price_per_kwh': price_per_kwh,
                 'max_duration_minutes': 120, 'active': active, 'control_version': 0, 'retired': False,
                 'power_limit_kw': None}
        self._points[pid] = point
        self._make_device(pid, online=online)
        return point

    def _make_device(self, point_id, *, online=True):
        did = self._id('device')
        device = {'id': did, 'connector_id': point_id, 'online': online, 'revoked': False}
        self._devices[did] = device
        return device

    def _get(self, store, identifier, message='Registro de demonstração não encontrado.'):
        result = store.get(identifier)
        if result is None:
            _fail(message, 'not_found', 404)
        return result

    def _device_for(self, point_id):
        return next((d for d in self._devices.values() if d['connector_id'] == point_id and not d['revoked']), None)

    def _current(self, kind, point_id=None):
        records, active = (self._reservations, _RES_ACTIVE) if kind == 'reservation' else (self._sessions, _SESSION_ACTIVE)
        return next((r for r in records.values() if r['status'] in active
                     and (r['connector_id'] == point_id if point_id else r['user_id'] == _USER)), None)

    def _busy(self, point_id):
        return self._current('reservation', point_id) or self._current('session', point_id)

    def _user_free(self, reservation_id=None):
        reservation = self._current('reservation')
        if self._current('session') or (reservation and reservation['id'] != reservation_id):
            _fail('Você já tem uma reserva ou recarga ativa na demonstração.', 'user_busy', 409)

    def _power(self, station):
        """Same allocation as the API (``chargegrid_core.power``)."""
        points = [p for p in self._points.values() if p['station_id'] == station['id']]
        return power_rules.allocate([{'id': p['id'], 'power_kw': p['power_kw'], 'power_limit_kw': p.get('power_limit_kw'),
                                      'participates': p['active'] and not p['retired']} for p in points],
                                    station.get('max_power_kw'))

    def _energy_total(self, point_id):
        return sum((Decimal(s['energy_wh']) for s in self._sessions.values() if s['connector_id'] == point_id),
                   Decimal(0)) / 1000

    def _point_row(self, point, power=None):
        station = self._stations[point['station_id']]
        power = power if power is not None else self._power(station)
        row = self._availability_row(point)
        allocated = power['connectors'].get(point['id'])
        if allocated:
            row.update(effective_power_kw=_decimal(allocated['effective_kw'], '0.001'),
                       power_limited=allocated['power_limited'], power_limited_by=allocated['limited_by'])
        if station['owner_id'] == _USER:
            row['energy_kwh_total'] = _decimal(self._energy_total(point['id']), '0.001')
        return row

    def _availability_row(self, point):
        device = self._device_for(point['id'])
        online = bool(device and device['online'])
        reservation, session = self._current('reservation', point['id']), self._current('session', point['id'])
        state = 'charging' if session and session['status'] == 'charging' else 'reserved' if reservation else 'idle'
        if not point['active'] or not self._stations[point['station_id']]['active'] or point['retired']:
            status = 'disabled'
        elif not online:
            status = 'offline'
        elif session:
            status = 'charging' if session['status'] == 'charging' else 'reconciling'
        elif reservation:
            status = 'reserved' if reservation['status'] == 'confirmed' else 'reconciling'
        else:
            status = 'available'
        return {**point, 'online': online, 'physical_state': state, 'available': status == 'available',
                'availability_status': status,
                'reserved_until': reservation['expires_at'] if reservation and reservation['status'] == 'confirmed' else None}

    def _station_row(self, station):
        power = self._power(station)
        status = self._demand(station)
        connectors = [self._point_row(p, power) for p in self._points.values() if p['station_id'] == station['id']]
        for point in connectors:
            # Como a API: base do horário do dono × demanda.
            current, price = pricing.connector_price(status, point['id'], point['price_per_kwh'])
            point['current_base_price_per_kwh'], point['dynamic_price_per_kwh'] = str(current), str(price)
        return {**station, 'allocated_power_kw': _decimal(power['allocated_kw'], '0.001'),
                'requested_power_kw': _decimal(power['requested_kw'], '0.001'), 'power_shared': power['shared'],
                'demand': {key: status[key] for key in ('multiplier', 'level', 'level_label', 'increase_percent',
                                                        'reason', 'reason_label')},
                'connectors': connectors}

    def _demand(self, station):
        """Mesmo cálculo da API (chargegrid_core.pricing) sobre o estado simulado do posto."""
        points = [p for p in self._points.values() if p['station_id'] == station['id'] and p['active']
                  and not p['retired'] and (self._device_for(p['id']) or {}).get('online')]
        ids = {p['id'] for p in points}
        current = self._now()
        sessions = [s for s in self._sessions.values() if s['connector_id'] in ids]
        in_use = sum(1 for p in points if self._current('session', p['id']))
        reserved = sum(1 for p in points if self._current('reservation', p['id']) and not self._current('session', p['id']))
        intervals = [(_date(s['started_at'] or s['created_at']), _date(s['ended_at']) if s['ended_at'] else None)
                     for s in sessions]
        starts = sum(1 for s in sessions if _date(s['created_at']) >= current - timedelta(hours=1))
        return pricing.demand_status(self._pricing.get(station['id']), {
            'connectors': len(points), 'in_use': in_use, 'reserved': reserved,
            'busy_15m': pricing.busy_fraction(intervals, current, len(points)),
            'starts_60m': starts, 'baseline_60m': 0, 'local_now': _local(current)})

    def _scheduled_base(self, point, moment):
        """Tarifa base do ponto em ``moment`` (tarifação por horário do dono), como a API."""
        rules = pricing.stored_rules(self._pricing.get(point['station_id']))
        return pricing.base_now(pricing.active_interval(rules, _local(moment)), point['id'], point['price_per_kwh'])

    def _pricing_payload(self, station):
        status = self._demand(station)
        points = [p for p in self._points.values() if p['station_id'] == station['id']]
        connectors = []
        for p in points:
            current, price = pricing.connector_price(status, p['id'], p['price_per_kwh'])
            connectors.append({'id': p['id'], 'public_code': p['public_code'], 'active': p['active'],
                               'connector_type': p['connector_type'], 'retired': p['retired'],
                               'base_price_per_kwh': p['price_per_kwh'], 'current_base_price_per_kwh': str(current),
                               'current_price_per_kwh': str(price)})
        return {'rules': pricing.stored_rules(self._pricing.get(station['id'])), 'status': status,
                'connectors': connectors}

    def _operation_row(self, record, kind):
        if record is None:
            return None
        point = self._points[record['connector_id']]
        station = self._stations[point['station_id']]
        result = {**record, 'station_id': station['id'], 'station_name': station['name'],
                  'station_address': station['address'], 'connector': {key: point[key] for key in _PUBLIC_POINT}}
        if kind == 'reservation':
            # Como a API: o ponto da reserva mostra o preço travado ao reservar (base do horário × demanda).
            locked = pricing.dynamic_price(self._scheduled_base(point, _date(record['created_at'])),
                                           record.get('demand_multiplier') or '1.00')
            if locked != Decimal(str(point['price_per_kwh'])):
                result['connector'].update(price_per_kwh=str(locked), base_price_per_kwh=point['price_per_kwh'])
        if kind == 'session':
            device = self._device_for(point['id'])
            result['online'] = bool(device and device['online'])
        return result

    def _page(self, records, params):
        limit = _number(params.get('limit', 50), 'limite', 1, 100, integer=True)
        offset = _number(params.get('offset', 0), 'posição', 0, 1000000, integer=True)
        return {'items': records[offset:offset + limit], 'total': len(records), 'limit': limit, 'offset': offset}

    def _owned(self, station_id):
        station = self._get(self._stations, station_id, 'Posto demonstrativo não encontrado.')
        if station['owner_id'] != _USER:
            _fail('Posto demonstrativo não encontrado.', 'not_found', 404)
        return station

    def _dispatch(self, method, path, body, params):
        parts = path.split('/')
        if (method, path) == ('GET', 'geo/address-suggestions'):
            return demo_address_suggestions((params or {}).get('q') or '')
        if len(parts) == 3 and parts[0] == 'stations' and parts[2] == 'best-times' and method == 'GET':
            from .services import forecast_demo
            return forecast_demo.best_times(self, parts[1], min(24, max(3, int((params or {}).get('hours') or 12))))
        if len(parts) == 3 and parts[0] == 'stations' and parts[2] == 'pricing' and method in ('GET', 'PUT'):
            station = self._owned(parts[1])
            if method == 'PUT':
                ids = [p['id'] for p in self._points.values() if p['station_id'] == station['id']]
                try:
                    self._pricing[station['id']] = pricing.clean_rules(pricing.merge_rules(
                        pricing.stored_rules(self._pricing.get(station['id'])), body, ids))
                except ValueError as error:
                    _fail(str(error), 'invalid_pricing')
            return self._pricing_payload(station)
        if path == 'me':
            if method == 'PATCH':
                _fields(body, ('name', 'phone', 'vehicle_description'))
                changes = {k: None if v is None and k != 'name' else _text(v, k, {'name': 100, 'phone': 30, 'vehicle_description': 200}[k], required=k == 'name')
                           for k, v in body.items()}
                self._profile.update(changes)
            if method in ('GET', 'PATCH'):
                return self._profile
        if (method, path) == ('GET', 'me/summary'):
            month = self._now().astimezone(_REPORT_TZ).strftime('%Y-%m')
            records = [s for s in self._sessions.values() if s['user_id'] == _USER and s['status'] in ('completed', 'interrupted')
                       and Decimal(s['energy_wh']) > 0 and s['ended_at']
                       and _date(s['ended_at']).astimezone(_REPORT_TZ).strftime('%Y-%m') == month]
            return {'month': month, 'currency': 'BRL', 'sessions_count': len(records),
                    'energy_wh': _decimal(sum(Decimal(s['energy_wh']) for s in records), '0.001'),
                    'estimated_cost': _decimal(sum(Decimal(s['cost_estimate']) for s in records), '0.0001')}
        if (method, path) == ('GET', 'operator/summary'):
            records = [s for s in self._sessions.values() if self._stations[self._points[s['connector_id']]['station_id']]['owner_id'] == _USER]
            return {'stations': sum(s['owner_id'] == _USER for s in self._stations.values()), 'total_sessions': len(records),
                    'total_energy_wh': _decimal(sum(Decimal(s['energy_wh']) for s in records), '0.001'),
                    'total_estimated_cost': _decimal(sum(Decimal(s['cost_estimate']) for s in records), '0.0001')}
        if path in ('stations', 'operator/stations') and method == 'GET':
            if path == 'stations':
                # A busca pública (lista, busca inteligente e chat IA) já enxerga a rede
                # parceira fictícia, não só depois do primeiro plano do Modo Motorista.
                from .services.driver_demo import ensure_network
                ensure_network(self)
            stations = [s for s in self._stations.values() if s['owner_id'] == _USER] if path.startswith('operator/') else [s for s in self._stations.values() if s['active']]
            if (params.get('lat') is None) != (params.get('lng') is None):
                _fail('Informe latitude e longitude juntas.', 'coordinates_required')
            lat = lng = None
            radius = float(_number(params.get('radius_km', 50), 'raio', 0, 500, positive=True))
            if params.get('lat') is not None:
                lat = float(_number(params['lat'], 'latitude', -90, 90))
                lng = float(_number(params['lng'], 'longitude', -180, 180))
                radius = float(_number(params.get('radius_km', 50), 'raio', 0, 500, positive=True))
                def distance(station):
                    first, second = math.radians(lat), math.radians(station['latitude'])
                    cosine = math.sin(first) * math.sin(second) + math.cos(first) * math.cos(second) * math.cos(math.radians(station['longitude'] - lng))
                    return 6371 * math.acos(max(-1, min(1, cosine)))
                stations = [s for s in stations if distance(s) <= radius]
            records = [self._station_row(s) for s in stations]
            if path == 'stations':
                order = params.get('sort', 'default')
                if order not in ('default', 'price', 'distance'):
                    _fail('Escolha uma ordenação válida.')
                if order == 'distance' and lat is None:
                    _fail('Informe lat e lng para ordenar por proximidade.', 'coordinates_required')
                connector = params.get('connector_type')
                if connector is not None:
                    connector = _text(connector, 'conector', 50)
                maximum = params.get('max_price_per_kwh')
                if maximum is not None:
                    maximum = _number(maximum, 'tarifa máxima', 0, 10000)
                available = params.get('available_only', False)
                if isinstance(available, str):
                    if available.lower() not in ('true', 'false', '1', '0', 'yes', 'no', 'on', 'off'):
                        _fail('Informe disponibilidade válida.')
                    available = available.lower() in ('true', '1', 'yes', 'on')
                if not isinstance(available, bool) and available not in (0, 1):
                    _fail('Informe disponibilidade válida.')
                records = discover(records, connector_type=connector, available_only=available,
                                   max_price_per_kwh=maximum, sort=order, lat=lat, lng=lng)
            return self._page(records, params)
        if method == 'POST' and path == 'stations':
            changes = self._station_fields(body, creating=True)
            return self._station_row(self._make_station(changes))
        if parts[0] == 'stations' and len(parts) == 2 and method in ('GET', 'PATCH'):
            station = self._get(self._stations, parts[1])
            if method == 'PATCH':
                self._owned(station['id'])
                changes = self._station_fields(body)
                if changes.get('active') is False and any(self._busy(p['id']) for p in self._points.values() if p['station_id'] == station['id']):
                    _fail('Encerre reservas e recargas antes de desativar.', 'point_busy', 409)
                if 'max_power_kw' in changes:
                    ratings = [p['power_kw'] for p in self._points.values()
                               if p['station_id'] == station['id'] and p['active'] and not p['retired']]
                    try:
                        cap = power_rules.validate_station_max(changes['max_power_kw'], ratings)
                    except ValueError as exc:
                        _fail(str(exc), 'invalid_power_limit')
                    changes['max_power_kw'] = None if cap is None else _decimal(cap, '0.001')
                station.update(changes)
            return self._station_row(station)
        if parts[0] == 'stations' and len(parts) == 3 and parts[2] == 'connectors' and method == 'POST':
            self._owned(parts[1])
            _fail('Use Adicionar equipamento simulado para criar um ponto.', 'claim_required', 409)
        if parts[0] == 'connectors' and len(parts) == 2 and method == 'PATCH':
            return self._patch_point(parts[1], body)
        if (method, path) == ('POST', 'ownership/claim'):
            return self._claim(body)
        if parts[0] == 'connectors' and len(parts) == 3 and parts[2] == 'device' and method in ('GET', 'POST'):
            return self._connector_device(method, parts[1])
        if parts[0] == 'devices' and len(parts) == 3:
            return self._device_action(method, parts[1], parts[2])
        if path == 'coupons' or (parts[0] == 'coupons' and len(parts) == 2):
            return self._coupon_route(method, parts, body, params)
        if (method, path) == ('POST', 'reservations'):
            return self._reserve(body)
        if (method, path) == ('GET', 'reservations/current'):
            return self._operation_row(self._current('reservation'), 'reservation')
        if parts[0] == 'reservations' and len(parts) == 3 and parts[2] == 'cancel' and method == 'POST':
            reservation = self._get(self._reservations, parts[1])
            if reservation['status'] in ('pending_device', 'confirmed'):
                reservation['status'] = 'cancelling'
                self._reservation_runtime[reservation['id']]['cancel_at'] = self._elapsed + 1
            return self._operation_row(reservation, 'reservation')
        if (method, path) == ('POST', 'charging-sessions'):
            return self._start(body)
        if parts[0] == 'charging-sessions' and len(parts) == 3 and parts[2] == 'events' and method == 'GET':
            self._get(self._sessions, parts[1])
            return self._session_events.get(parts[1], [])
        if parts[0] == 'charging-sessions' and len(parts) == 2 and method == 'GET':
            record = self._current('session') if parts[1] == 'current' else self._get(self._sessions, parts[1])
            return self._operation_row(record, 'session')
        if parts[0] == 'charging-sessions' and len(parts) == 3 and parts[2] == 'soc' and method == 'POST':
            return self._report_soc(parts[1], body)
        if parts[0] == 'charging-sessions' and len(parts) == 3 and parts[2] == 'stop' and method == 'POST':
            session = self._get(self._sessions, parts[1])
            if session['status'] in ('starting', 'charging'):
                runtime = self._session_runtime[session['id']]
                runtime.update(stop_at=self._elapsed + 1, never_started=session['status'] == 'starting')
                session['status'] = 'stopping'
                self._event(session['id'], 'stop_requested')
            return self._operation_row(session, 'session')
        if method == 'GET' and (path in ('me/charging-sessions', 'operator/charging-sessions') or
                                (len(parts) == 3 and parts[0] == 'stations' and parts[2] == 'charging-sessions')):
            records = list(self._sessions.values())
            if path == 'me/charging-sessions':
                records = [s for s in records if s['user_id'] == _USER]
            else:
                if parts[0] == 'stations':
                    self._owned(parts[1])
                records = [s for s in records if self._stations[self._points[s['connector_id']]['station_id']]['owner_id'] == _USER
                           and (parts[0] != 'stations' or self._points[s['connector_id']]['station_id'] == parts[1])]
            records.sort(key=lambda s: (s['created_at'], s['id']), reverse=True)
            return self._page([self._operation_row(s, 'session') for s in records], params)
        if parts[0] == 'owner' or path == 'ai/owner-insights':
            from .demo_owner import owner_for
            return owner_for(self).route(method, path, params, body)
        if parts[0] == 'driver':
            from .services.driver_demo import driver_route
            return driver_route(self, method, path, body, params)
        _fail('Esta operação não está disponível na demonstração. Nenhum servidor real foi consultado.', 'demo_route_not_supported', 404)

    def _station_fields(self, body, creating=False):
        allowed = ('name', 'address', 'latitude', 'longitude') + (
            () if creating else ('active', 'amenities', 'max_power_kw', 'power_limit_notify'))
        _fields(body, allowed)
        if creating and not set(allowed).issubset(body):
            _fail('Informe nome, endereço e coordenadas do posto.')
        result = {}
        for key, value in body.items():
            if key in ('name', 'address'):
                result[key] = _text(value, key, 100 if key == 'name' else 300)
            elif key in ('latitude', 'longitude'):
                bound = 90 if key == 'latitude' else 180
                result[key] = float(_number(value, key, -bound, bound))
            elif key == 'amenities':
                result[key] = _amenities(value)
            elif key == 'max_power_kw':
                result[key] = value  # validated against the active points in _patch_station
            elif key == 'power_limit_notify':
                if not isinstance(value, bool):
                    _fail('Informe se o aviso de limite de potência está ligado.')
                result[key] = value
            elif isinstance(value, bool):
                result[key] = value
            else:
                _fail('Informe se o posto está ativo.')
        return result

    def _patch_point(self, identifier, body):
        point = self._get(self._points, identifier)
        self._owned(point['station_id'])
        # Like the API: a power limit applies to the next start, so it may change while busy.
        if set(body) - {'power_limit_kw'} and self._busy(identifier):
            _fail('Encerre reservas e recargas antes de editar o ponto.', 'point_busy', 409)
        if body.get('active') is True and (point['retired'] or any(r['status'] == 'pending' for did, r in self._resets.items() if self._devices[did]['connector_id'] == identifier)):
            _fail('Este equipamento está sendo restaurado. Adicione outro equipamento simulado.', 'point_retired', 409)
        _fields(body, ('public_code', 'connector_type', 'power_kw', 'price_per_kwh', 'max_duration_minutes', 'active',
                       'power_limit_kw'))
        changes = {}
        for name, value in body.items():
            if name in ('public_code', 'connector_type'):
                changes[name] = _text(value, name, 50)
            elif name == 'power_kw':
                changes[name] = _decimal(_number(value, 'potência', 0, 1000, positive=True), '0.001')
                if Decimal(changes[name]) <= 0:
                    _fail('A potência deve ser de pelo menos 0,001 kW.')
            elif name == 'power_limit_kw':
                continue  # validated below, against the (possibly new) rating
            elif name == 'price_per_kwh':
                changes[name] = _decimal(_number(value, 'tarifa', 0, 10000), '0.0001')
            elif name == 'max_duration_minutes':
                changes[name] = _number(value, 'duração', 1, 1440, integer=True)
            elif isinstance(value, bool):
                changes[name] = value
            else:
                _fail('Informe se o ponto está ativo.')
        if 'public_code' in changes and any(p['id'] != identifier and p['public_code'] == changes['public_code'] for p in self._points.values()):
            _fail('Código público já usado na demonstração.', 'conflict', 409)
        rating = changes.get('power_kw', point['power_kw'])
        if 'power_limit_kw' in body:
            try:
                limit = power_rules.validate_port_limit(rating, body['power_limit_kw'])
            except ValueError as exc:
                _fail(str(exc), 'invalid_power_limit')
            changes['power_limit_kw'] = None if limit is None else _decimal(limit, '0.001')
        elif 'power_kw' in changes and point.get('power_limit_kw') and Decimal(point['power_limit_kw']) >= Decimal(rating):
            changes['power_limit_kw'] = None
        point.update(changes)
        return self._point_row(point)

    def _claim(self, body):
        _fields(body, ('token', 'station_id'))
        token = body.get('token')
        if not isinstance(token, str) or token not in self._claims:
            _fail('Use somente o equipamento simulado deste formulário.', 'invalid_claim', 404)
        target = self._owned(body['station_id']) if body.get('station_id') else None
        existing = self._claims[token]
        if existing:
            point = self._points[existing]
            if target and target['id'] != point['station_id']:
                _fail('Este código simulado já foi vinculado a outro posto.', 'already_claimed', 409)
        else:
            if target is None:
                target = self._make_station({'name': 'Novo posto demonstrativo', 'address': 'Configure o endereço simulado',
                                            'latitude': -23.5505, 'longitude': -46.6333}, active=False)
            point = self._make_point(target['id'], active=False)
            self._claims[token] = point['id']
        return {'station_id': point['station_id'], 'connector_id': point['id'], 'already_claimed': bool(existing),
                'message': 'Equipamento simulado vinculado. Revise os dados antes de publicar.'}

    def _device_row(self, device):
        point = self._point_row(self._points[device['connector_id']])
        return {'device_id': device['id'], 'connector_id': device['connector_id'], 'firmware_version': 'demo-0.3.6',
                'last_seen': self._iso() if device['online'] and not device['revoked'] else None,
                'online': device['online'] and not device['revoked'], 'physical_state': point['physical_state'],
                'connected': point['physical_state'] == 'charging', 'reconciled': point['availability_status'] != 'reconciling',
                'retired': device['revoked']}

    def _connector_device(self, method, point_id):
        point = self._get(self._points, point_id)
        self._owned(point['station_id'])
        device = self._device_for(point_id)
        if method == 'GET':
            if device is None and point['retired']:
                device = next((d for d in self._devices.values() if d['connector_id'] == point_id
                               and self._resets.get(d['id'], {}).get('status') == 'applied'), None)
            if not device:
                _fail('Ponto simulado sem dispositivo ativo.', 'not_found', 404)
            return self._device_row(device)
        if self._busy(point_id):
            _fail('Encerre a operação antes de provisionar.', 'point_busy', 409)
        if point['retired']:
            _fail('Adicione um equipamento simulado novo.', 'point_retired', 409)
        if device:
            _fail('O ponto já tem um dispositivo simulado.', 'device_exists', 409)
        device = self._make_device(point_id)
        return {'device_id': device['id'], 'device_key': self._id('FAKE-DEVICE-KEY-NOT-REAL')}

    def _device_action(self, method, device_id, action):
        device = self._get(self._devices, device_id)
        point = self._points[device['connector_id']]
        self._owned(point['station_id'])
        reset = self._resets.get(device_id)
        if method == 'GET' and action == 'factory-reset':
            return {k: reset[k] for k in ('status', 'command_id')} if reset else {'status': 'not_requested'}
        if method != 'POST' or action not in ('factory-reset', 'rotate-key', 'revoke'):
            _fail('Operação de dispositivo não disponível na demonstração.', 'demo_route_not_supported', 404)
        if self._busy(point['id']):
            _fail('Encerre reservas e recargas antes da manutenção simulada.', 'point_busy', 409)
        if reset and reset['status'] == 'pending':
            if action == 'factory-reset':
                return {k: reset[k] for k in ('status', 'command_id')}
            _fail('Aguarde a restauração simulada.', 'reset_pending', 409)
        if device['revoked']:
            _fail('Dispositivo simulado revogado.', 'device_revoked', 409)
        if action == 'revoke':
            device['revoked'] = True
            return {'revoked': True}
        if action == 'rotate-key':
            return {'device_id': device_id, 'device_key': self._id('FAKE-DEVICE-KEY-NOT-REAL')}
        if not device['online']:
            _fail('O dispositivo simulado precisa estar online.', 'device_not_idle', 409)
        point['active'] = False
        reset = {'status': 'pending', 'command_id': self._id('reset'), 'due': self._elapsed + 2}
        self._resets[device_id] = reset
        return {k: reset[k] for k in ('status', 'command_id')}

    def _coupon_route(self, method, parts, body, params):
        if len(parts) == 1 and method == 'GET':
            mine = str(params.get('mine', False)).lower() == 'true'
            station = self._get(self._stations, params['station_id']) if params.get('station_id') else None
            records = [c for c in self._coupons.values() if (c['operator_id'] == _USER if mine else c['active'] and _date(c['valid_until']) > self._now())
                       and (not station or (c['operator_id'] == station['owner_id'] and c['station_id'] in (None, station['id'])))]
            return self._page(records, params)
        creating = len(parts) == 1 and method == 'POST'
        if not creating and not (len(parts) == 2 and method == 'PATCH'):
            _fail('Operação de cupom não disponível na demonstração.', 'demo_route_not_supported', 404)
        allowed = ('code', 'description', 'discount_percent', 'station_id', 'valid_until') if creating else ('description', 'discount_percent', 'valid_until', 'active')
        _fields(body, allowed)
        coupon = {'active': True, 'station_id': None, 'operator_id': _USER} if creating else self._get(self._coupons, parts[1])
        changes = {}
        if creating:
            # Codes are typed by drivers; match the API's case-insensitive contract.
            changes['code'] = _text(body.get('code'), 'código do cupom', 50).upper()
            if any(c['code'].upper() == changes['code'] for c in self._coupons.values()):
                _fail('Já existe um cupom simulado com este código.', 'conflict', 409)
        for name in ('description', 'discount_percent', 'valid_until'):
            if name not in body and not creating:
                continue
            if name == 'description':
                changes[name] = _text(body.get(name), 'descrição', 200, required=False)
            elif name == 'discount_percent':
                changes[name] = _number(body.get(name), 'desconto', 0, 100, integer=True)
            else:
                value = _date(body.get(name))
                if value <= self._now():
                    _fail('Escolha uma validade futura para o cupom.', 'invalid_time')
                changes[name] = value.isoformat()
        if body.get('station_id'):
            changes['station_id'] = self._owned(body['station_id'])['id']
        if 'active' in body:
            if not isinstance(body['active'], bool):
                _fail('Informe se o cupom está ativo.')
            changes['active'] = body['active']
            if body['active'] and not coupon['active'] and _date(changes.get('valid_until', coupon['valid_until'])) <= self._now():
                _fail('Atualize a validade antes de reativar o cupom.', 'invalid_time')
        if creating:
            coupon['id'] = self._id('coupon')
            self._coupons[coupon['id']] = coupon
        coupon.update(changes)
        return coupon

    def _reserve(self, body):
        _fields(body, ('connector_id',))
        point = self._get(self._points, body.get('connector_id'))
        self._user_free()
        if not self._point_row(point)['available']:
            _fail('Ponto simulado indisponível.', 'point_unavailable', 409)
        rid = self._id('reservation')
        reservation = {'id': rid, 'user_id': _USER, 'connector_id': point['id'], 'status': 'pending_device',
                       'created_at': self._iso(), 'confirmation_deadline': self._iso(self._elapsed + 30), 'expires_at': None,
                       'demand_multiplier': self._demand(self._stations[point['station_id']])['multiplier']}
        self._reservations[rid] = reservation
        self._reservation_runtime[rid] = {'confirm_at': self._elapsed + 1, 'expires_at': self._elapsed + 1 + 15 * 60}  # 15 min, como a API
        return self._operation_row(reservation, 'reservation')

    def _start(self, body):
        _fields(body, ('public_code', 'presence_code', 'reservation_id', 'coupon_code', 'max_duration_minutes', 'max_cost',
                       'soc_percent', 'battery_kwh', 'soc_source', 'max_power_kw'))
        driver_kw = (_number(body['max_power_kw'], 'a potência máxima', 0, 1000, positive=True)
                     if body.get('max_power_kw') is not None else None)
        start_soc = (_decimal(_number(body['soc_percent'], 'o nível da bateria', 0, 100), '0.01')
                     if body.get('soc_percent') is not None else None)
        battery = (_decimal(_number(body['battery_kwh'], 'a capacidade da bateria', 5, 250), '0.01')
                   if body.get('battery_kwh') is not None else None)
        if body.get('soc_source') not in (None, 'simulated', 'phone'):
            _fail('Confira a origem do nível da bateria.')
        soc_source = body.get('soc_source') or ('simulated' if start_soc is not None else None)
        if str(body.get('presence_code', '')).strip().upper() != DEMO_PRESENCE_CODE:
            _fail('Na demonstração, use o código #F12345.', 'invalid_presence_code')
        reservation_id = body.get('reservation_id')
        reservation = self._get(self._reservations, reservation_id) if reservation_id else None
        if reservation:
            point = self._points[reservation['connector_id']]
            if reservation['status'] != 'confirmed' or (body.get('public_code') and body['public_code'] != point['public_code']):
                _fail('Confira a reserva e o ponto simulados.', 'invalid_reservation', 409)
        elif body.get('public_code'):
            point = next((p for p in self._points.values() if p['public_code'] == body['public_code']), None)
            if point is None:
                _fail('Ponto demonstrativo não encontrado.', 'not_found', 404)
        else:
            matches = [p for p in self._points.values() if p['active'] and self._stations[p['station_id']]['active'] and not p['retired']]
            available = [p for p in matches if self._point_row(p)['available']]
            if len({p['station_id'] for p in matches}) > 1 or len(available) != 1:
                _fail('Escolha um ponto na lista para usar este código de demonstração.', 'ambiguous_presence_code')
            point = available[0]
        self._user_free(reservation_id)
        if not reservation and not self._point_row(point)['available']:
            _fail('Ponto simulado indisponível.', 'point_unavailable', 409)
        if reservation and (not point['active'] or not self._stations[point['station_id']]['active'] or not self._point_row(point)['online']):
            _fail('O ponto reservado não está disponível.', 'point_unavailable', 409)
        duration = _number(body.get('max_duration_minutes', 30), 'duração', 1, point['max_duration_minutes'], integer=True)
        maximum = None
        if body.get('max_cost') is not None:
            maximum = _decimal(_number(body['max_cost'], 'valor máximo', 0, 100000, positive=True), '0.0001')
            if Decimal(maximum) <= 0:
                _fail('O valor máximo deve ser maior que zero.')
        discount = 0
        if body.get('coupon_code'):
            typed = str(body['coupon_code']).strip().upper()
            coupon = next((c for c in self._coupons.values() if c['code'].upper() == typed), None)
            if (not coupon or not coupon['active'] or _date(coupon['valid_until']) <= self._now()
                    or coupon['operator_id'] != self._stations[point['station_id']]['owner_id']
                    or coupon['station_id'] not in (None, point['station_id'])):
                _fail('Cupom inválido para este ponto simulado.', 'invalid_coupon')
            discount = coupon['discount_percent']
        multiplier = ((reservation or {}).get('demand_multiplier')
                      or self._demand(self._stations[point['station_id']])['multiplier'])
        # Base do horário: a do momento da reserva ou a de agora (como a API).
        base = str(self._scheduled_base(point, _date(reservation['created_at']) if reservation else self._now()))
        sid = self._id('session')
        session = {'id': sid, 'user_id': _USER, 'connector_id': point['id'], 'reservation_id': reservation_id,
                   'status': 'starting', 'created_at': self._iso(), 'started_at': None, 'ended_at': None,
                   'max_duration_minutes': duration, 'max_cost': maximum,
                   'price_per_kwh': str(pricing.dynamic_price(base, multiplier)),
                   'base_price_per_kwh': base, 'demand_multiplier': multiplier,
                   'discount_percent': discount, 'energy_wh': '0.000', 'soc_percent': start_soc,
                   'start_soc_percent': start_soc, 'battery_kwh': battery, 'soc_source': soc_source, 'source': 'simulated',
                   'last_measurement_at': None, 'cost_estimate': '0.0000', 'end_reason': None}
        # Same as the API: effective point power (rating, port limit, station share) ∩ driver limit.
        effective = self._power(self._stations[point['station_id']])['connectors'][point['id']]['effective_kw']
        applied = power_rules.applied_limit(effective, driver_kw).quantize(Decimal('0.001'), rounding=ROUND_DOWN)
        session['power_limit_kw'] = _decimal(applied, '0.001') if applied > 0 else None
        self._sessions[sid] = session
        self._event(sid, 'start_requested')
        self._session_runtime[sid] = {'start_at': self._elapsed + 1,
                                      'power_kw': applied if applied > 0 else Decimal(point['power_kw'])}
        if reservation:
            reservation['status'] = 'consumed'
        return self._operation_row(session, 'session')

    async def download(self, path, params=None):
        """Exportações do dashboard geradas localmente (CSV/JSON fictícios)."""
        from .demo_owner import owner_for
        return owner_for(self).download(path, params)
