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

from .api_client import ApiError
from .session import Session

DEMO_EMAIL = 'demo@chargegrid.example'
DEMO_PASSWORD = 'demo1234'
DEMO_PRESENCE_CODE = '#F12345'
DEMO_CLAIM_TOKEN = 'DEMO-CLAIM-' + '0' * 32
DEMO_LOCATIONS = (
    {'name': 'Posto Demo Centro', 'address': 'Praça da Sé, São Paulo - SP',
     'latitude': -23.5505, 'longitude': -46.6333},
    {'name': 'Posto Demo Vila Mariana', 'address': 'Rua Vergueiro, Vila Mariana, São Paulo - SP',
     'latitude': -23.5895, 'longitude': -46.6345},
)

_USER = 'demo-user'
_RES_ACTIVE = {'pending_device', 'confirmed', 'cancelling'}
_SESSION_ACTIVE = {'starting', 'charging', 'stopping'}
_TERMINAL = {'completed', 'failed', 'interrupted'}
_REPORT_TZ = timezone(timedelta(hours=-3))
_PUBLIC_POINT = ('id', 'public_code', 'connector_type', 'power_kw', 'price_per_kwh', 'max_duration_minutes')


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


def _decimal(value, places):
    return format(Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP), 'f')


def _fields(body, allowed):
    if set(body) - set(allowed):
        _fail('Este formulário contém campos não reconhecidos na demonstração.')


class DemoApi:
    is_demo = True

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
        self._reservation_runtime, self._session_runtime, self._resets = {}, {}, {}
        self._claims = {DEMO_CLAIM_TOKEN: None}
        self._idempotency = {}
        self.operation_keys.clear()
        self.charging_operation_sessions.clear()
        self.last_session_id = self.last_reservation_id = None
        self._profile = {'id': _USER, 'name': 'Conta demonstração', 'account_type': 'vendor',
                         'operator_enabled': True, 'phone': None, 'vehicle_description': 'Veículo simulado',
                         'created_at': self._iso()}
        for index, location in enumerate(DEMO_LOCATIONS):
            station = self._make_station(dict(location), active=index == 0)
            self._make_point(station['id'], active=index == 0)
            if index == 0:
                self._make_point(station['id'], online=False)
        primary = next(iter(self._points.values()))
        self._coupons['demo-coupon-welcome'] = {
            'id': 'demo-coupon-welcome', 'operator_id': _USER, 'station_id': None,
            'code': 'DEMO10', 'description': '10% de desconto na recarga simulada',
            'discount_percent': 10, 'valid_until': self._iso(30 * 86400), 'active': True,
        }
        for index in range(2):
            sid = self._id('session')
            ended = -(index + 1) * 3600
            self._sessions[sid] = {
                'id': sid, 'user_id': _USER, 'connector_id': primary['id'], 'reservation_id': None,
                'status': 'completed', 'created_at': self._iso(ended - 1201),
                'started_at': self._iso(ended - 1200), 'ended_at': self._iso(ended),
                'max_duration_minutes': 20, 'max_cost': None, 'price_per_kwh': '1.5000',
                'discount_percent': 0, 'energy_wh': '2400.000', 'soc_percent': '24.00',
                'source': 'simulated', 'last_measurement_at': self._iso(ended),
                'cost_estimate': '3.6000', 'end_reason': 'duration_limit',
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
                      self._coupons, self._reservation_runtime, self._session_runtime, self._resets,
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
        elif method == 'GET' and path.startswith('charging-sessions/') and result:
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
                    session.update(status='failed', ended_at=self._iso(runtime['stop_at']), end_reason='requested')
                continue
            if self._elapsed < start:
                continue
            session['started_at'] = self._iso(start)
            if session['status'] == 'starting':
                session['status'] = 'charging'
            effective_price = Decimal(session['price_per_kwh']) * (100 - session['discount_percent']) / 100
            power = runtime['power_kw']
            deadlines = [(float(start + session['max_duration_minutes'] * 60), 'duration_limit')]
            if session['max_cost'] is not None and effective_price > 0:
                deadlines.append((start + float(Decimal(session['max_cost']) * 3600 / (effective_price * power)), 'cost_limit'))
            if runtime.get('stop_at') is not None:
                deadlines.append((runtime['stop_at'], 'requested'))
            deadline, reason = min(deadlines, key=lambda item: item[0])
            observed = min(self._elapsed, deadline)
            seconds = Decimal(str(max(0, observed - start)))
            energy = (power * 1000 * seconds / 3600).quantize(Decimal('0.001'), rounding=ROUND_DOWN)
            cost = energy / 1000 * effective_price
            if session['max_cost'] is not None:
                cost = min(cost, Decimal(session['max_cost']))
            session.update(energy_wh=_decimal(energy, '0.001'), cost_estimate=_decimal(cost, '0.0001'),
                           soc_percent=_decimal(min(Decimal(100), Decimal(20) + energy / 600), '0.01'),
                           last_measurement_at=self._iso(observed))
            if self._elapsed >= deadline:
                session.update(status='completed', ended_at=self._iso(deadline), end_reason=reason)
        for device_id, reset in self._resets.items():
            if reset['status'] == 'pending' and self._elapsed >= reset['due']:
                reset['status'] = 'applied'
                self._devices[device_id]['revoked'] = True
                self._points[self._devices[device_id]['connector_id']]['retired'] = True

    def _make_station(self, data, *, active=True):
        sid = self._id('station')
        station = {'id': sid, 'owner_id': _USER, 'name': data['name'], 'address': data['address'],
                   'latitude': float(data['latitude']), 'longitude': float(data['longitude']), 'active': active}
        self._stations[sid] = station
        return station

    def _make_point(self, station_id, *, active=True, online=True):
        pid = self._id('point')
        point = {'id': pid, 'station_id': station_id, 'public_code': 'DEMO-' + pid.rsplit('-', 1)[-1],
                 'connector_type': 'Tipo 2', 'power_kw': '7.200', 'price_per_kwh': '1.5000',
                 'max_duration_minutes': 120, 'active': active, 'control_version': 0, 'retired': False}
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

    def _point_row(self, point):
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
        return {**station, 'connectors': [self._point_row(p) for p in self._points.values() if p['station_id'] == station['id']]}

    def _operation_row(self, record, kind):
        if record is None:
            return None
        point = self._points[record['connector_id']]
        station = self._stations[point['station_id']]
        result = {**record, 'station_id': station['id'], 'station_name': station['name'],
                  'station_address': station['address'], 'connector': {key: point[key] for key in _PUBLIC_POINT}}
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
            stations = [s for s in self._stations.values() if s['owner_id'] == _USER] if path.startswith('operator/') else [s for s in self._stations.values() if s['active']]
            if (params.get('lat') is None) != (params.get('lng') is None):
                _fail('Informe latitude e longitude juntas.', 'coordinates_required')
            if params.get('lat') is not None:
                lat = float(_number(params['lat'], 'latitude', -90, 90))
                lng = float(_number(params['lng'], 'longitude', -180, 180))
                radius = float(_number(params.get('radius_km', 50), 'raio', 0, 500, positive=True))
                def distance(station):
                    first, second = math.radians(lat), math.radians(station['latitude'])
                    cosine = math.sin(first) * math.sin(second) + math.cos(first) * math.cos(second) * math.cos(math.radians(station['longitude'] - lng))
                    return 6371 * math.acos(max(-1, min(1, cosine)))
                stations = [s for s in stations if distance(s) <= radius]
            return self._page([self._station_row(s) for s in stations], params)
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
        if parts[0] == 'charging-sessions' and len(parts) == 2 and method == 'GET':
            record = self._current('session') if parts[1] == 'current' else self._get(self._sessions, parts[1])
            return self._operation_row(record, 'session')
        if parts[0] == 'charging-sessions' and len(parts) == 3 and parts[2] == 'stop' and method == 'POST':
            session = self._get(self._sessions, parts[1])
            if session['status'] in ('starting', 'charging'):
                runtime = self._session_runtime[session['id']]
                runtime.update(stop_at=self._elapsed + 1, never_started=session['status'] == 'starting')
                session['status'] = 'stopping'
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
        _fail('Esta operação não está disponível na demonstração. Nenhum servidor real foi consultado.', 'demo_route_not_supported', 404)

    def _station_fields(self, body, creating=False):
        allowed = ('name', 'address', 'latitude', 'longitude') + (() if creating else ('active',))
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
            elif isinstance(value, bool):
                result[key] = value
            else:
                _fail('Informe se o posto está ativo.')
        return result

    def _patch_point(self, identifier, body):
        point = self._get(self._points, identifier)
        self._owned(point['station_id'])
        if self._busy(identifier):
            _fail('Encerre reservas e recargas antes de editar o ponto.', 'point_busy', 409)
        if body.get('active') is True and (point['retired'] or any(r['status'] == 'pending' for did, r in self._resets.items() if self._devices[did]['connector_id'] == identifier)):
            _fail('Este equipamento está sendo restaurado. Adicione outro equipamento simulado.', 'point_retired', 409)
        _fields(body, ('public_code', 'connector_type', 'power_kw', 'price_per_kwh', 'max_duration_minutes', 'active'))
        changes = {}
        for name, value in body.items():
            if name in ('public_code', 'connector_type'):
                changes[name] = _text(value, name, 50)
            elif name == 'power_kw':
                changes[name] = _decimal(_number(value, 'potência', 0, 1000, positive=True), '0.001')
                if Decimal(changes[name]) <= 0:
                    _fail('A potência deve ser de pelo menos 0,001 kW.')
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
            changes['code'] = _text(body.get('code'), 'código do cupom', 50)
            if any(c['code'] == changes['code'] for c in self._coupons.values()):
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
                       'created_at': self._iso(), 'confirmation_deadline': self._iso(self._elapsed + 30), 'expires_at': None}
        self._reservations[rid] = reservation
        self._reservation_runtime[rid] = {'confirm_at': self._elapsed + 1, 'expires_at': self._elapsed + 601}
        return self._operation_row(reservation, 'reservation')

    def _start(self, body):
        _fields(body, ('public_code', 'presence_code', 'reservation_id', 'coupon_code', 'max_duration_minutes', 'max_cost'))
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
            coupon = next((c for c in self._coupons.values() if c['code'] == body['coupon_code']), None)
            if (not coupon or not coupon['active'] or _date(coupon['valid_until']) <= self._now()
                    or coupon['operator_id'] != self._stations[point['station_id']]['owner_id']
                    or coupon['station_id'] not in (None, point['station_id'])):
                _fail('Cupom inválido para este ponto simulado.', 'invalid_coupon')
            discount = coupon['discount_percent']
        sid = self._id('session')
        session = {'id': sid, 'user_id': _USER, 'connector_id': point['id'], 'reservation_id': reservation_id,
                   'status': 'starting', 'created_at': self._iso(), 'started_at': None, 'ended_at': None,
                   'max_duration_minutes': duration, 'max_cost': maximum, 'price_per_kwh': point['price_per_kwh'],
                   'discount_percent': discount, 'energy_wh': '0.000', 'soc_percent': None, 'source': 'simulated',
                   'last_measurement_at': None, 'cost_estimate': '0.0000', 'end_reason': None}
        self._sessions[sid] = session
        self._session_runtime[sid] = {'start_at': self._elapsed + 1, 'power_kw': Decimal(point['power_kw'])}
        if reservation:
            reservation['status'] = 'consumed'
        return self._operation_row(session, 'session')
