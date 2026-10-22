"""Rotas ``/driver/*`` do modo demo: mesmo motor (chargegrid_core) e mesmo contrato da API.

Nada sai do aparelho: os postos são os da demonstração e o clima é **simulado** (fixo: nublado, 23°,
chuva das 18h às 20h — ``chargegrid_core.driver.simulated_weather``), sempre rotulado "simulado".
"""
from copy import deepcopy
from datetime import timedelta, timezone

from chargegrid_core.driver import (
    build_context,
    build_next_stop,
    build_plan,
    default_profile,
    merge_profile,
    presets,
    rain_note,
    simulated_weather,
    validate_profile,
)

from ..api_client import ApiError

LOCAL_TZ = timezone(timedelta(hours=-3))
# Rede pública fictícia usada pelo Modo Motorista (postos de outro operador simulado).
DEMO_DRIVER_NETWORK = (
    {'name': 'Shopping Eldorado · Eletroposto', 'address': 'Av. Rebouças, 3970, Pinheiros, São Paulo - SP',
     'latitude': -23.5727, 'longitude': -46.6963, 'points': (('CCS2', '60.000', '2.2900'),),
     'amenities': [{'kind': 'shopping', 'name': 'Shopping Eldorado', 'distance_m': 0},
                   {'kind': 'restaurante', 'name': 'Praça de alimentação', 'distance_m': 80},
                   {'kind': 'cafe', 'name': 'Café do piso G', 'distance_m': 40}, {'kind': 'banheiro'}]},
    {'name': 'Posto Paulista 24h', 'address': 'Av. Paulista, 1000, Bela Vista, São Paulo - SP',
     'latitude': -23.5614, 'longitude': -46.6559, 'points': (('CCS2', '40.000', '2.4900'),),
     'amenities': [{'kind': 'conveniencia', 'name': 'Loja 24h', 'distance_m': 20},
                   {'kind': 'cafe', 'distance_m': 30}, {'kind': 'banheiro'}]},
    {'name': 'Cantina da Vila + carregador', 'address': 'Rua Aspicuelta, 300, Vila Madalena, São Paulo - SP',
     'latitude': -23.5535, 'longitude': -46.6908, 'points': (('CCS2', '50.000', '2.1900'), ('Tipo 2', '22.000', '1.4900')),
     'amenities': [{'kind': 'restaurante', 'name': 'Cantina da Vila', 'distance_m': 0}, {'kind': 'banheiro'}]},
    {'name': 'Estacionamento Pinheiros (AC)', 'address': 'Rua dos Pinheiros, 800, São Paulo - SP',
     'latitude': -23.5670, 'longitude': -46.6880, 'points': (('Tipo 2', '22.000', '1.3900'),),
     'amenities': [{'kind': 'cafe', 'name': 'Padaria', 'distance_m': 150}]},
    {'name': 'Hub Rápido Marginal Tietê', 'address': 'Av. Marginal do Tietê, 2000, São Paulo - SP',
     'latitude': -23.5165, 'longitude': -46.6250, 'points': (('CCS2', '120.000', '2.7900'),),
     'amenities': [{'kind': 'conveniencia', 'distance_m': 10}, {'kind': 'banheiro'}]},
    {'name': 'Aeroporto de Congonhas · Recarga', 'address': 'Av. Washington Luís, s/n, São Paulo - SP',
     'latitude': -23.6266, 'longitude': -46.6554, 'points': (('CCS2', '50.000', '2.5900'),),
     'amenities': [{'kind': 'cafe', 'distance_m': 100}, {'kind': 'banheiro'}]},
)
_NETWORK_OWNER = 'demo-network'



def ensure_network(api):
    """Cria uma vez por sessão demo os postos fictícios da rede parceira (com comodidades)."""
    if api._driver_network:
        return
    api._driver_network = True
    for spec in DEMO_DRIVER_NETWORK:
        station = api._make_station(spec)
        station['owner_id'] = _NETWORK_OWNER
        station['amenities'] = deepcopy(spec['amenities'])
        for kind, power, price in spec['points']:
            api._make_point(station['id'], connector_type=kind, power_kw=power, price_per_kwh=price)
PLAN_FIELDS = ('soc_percent', 'lat', 'lng', 'radius_km', 'vehicle', 'preferences', 'context', 'live_signals')


def _fail(message, code='validation_error', status=422):
    raise ApiError(message, status, code)


def _number(value, label, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        _fail(f'Informe {label} válido.')
    if number != number or not low <= number <= high:
        _fail(f'Informe {label} válido.')
    return number


def _check(body, allowed):
    if not isinstance(body, dict):
        _fail('Dados do Modo Motorista inválidos.')
    unknown = set(body) - set(allowed)
    if unknown:
        _fail('Campo não permitido: ' + ', '.join(sorted(unknown)))
    for section in ('vehicle', 'preferences', 'context'):
        if body.get(section) is not None and not isinstance(body[section], dict):
            _fail('Dados do Modo Motorista inválidos.')


def _validated(profile):
    try:
        return validate_profile(profile)
    except (ValueError, TypeError) as error:
        _fail(str(error) or 'Perfil do motorista inválido.', 'invalid_driver_profile')


def _profile_response(api, profile):
    saved = api._driver_profile is not None
    return {**deepcopy(profile), 'saved': saved, 'updated_at': api._driver_updated_at if saved else None,
            'presets': presets()}


SIGNALS_INFO = [{'source': 'simulado', 'status': 'simulado',
                 'detail': 'Clima estimado para a região (sem previsão online).'}]


def _coordinates(source):
    if (source.get('lat') is None) != (source.get('lng') is None):
        _fail('Informe latitude e longitude juntas.', 'coordinates_required')
    if source.get('lat') is None:
        return None, None
    return _number(source['lat'], 'a latitude', -90, 90), _number(source['lng'], 'a longitude', -180, 180)


def _local_now(api):
    return api._now().astimezone(LOCAL_TZ).replace(tzinfo=None)


def driver_route(api, method, path, body, params=None):
    ensure_network(api)
    if (method, path) == ('GET', 'driver/context'):
        _coordinates(dict(params or {}))
        now = _local_now(api)
        weather = simulated_weather(now)
        result = build_context(api._driver_profile or _validated(default_profile()), now, (weather,))
        result['demand']['signals'] = deepcopy(SIGNALS_INFO)
        note = rain_note(weather, now)
        result['alerts'] = [note] if note else []
        return result
    if (method, path) == ('GET', 'driver/profile'):
        return _profile_response(api, api._driver_profile or _validated(default_profile()))
    if (method, path) == ('PUT', 'driver/profile'):
        _check(body, ('vehicle', 'preferences'))
        profile = _validated(merge_profile(None, body))
        api._driver_profile, api._driver_updated_at = profile, api._iso()
        return _profile_response(api, profile)
    if method == 'POST' and path in ('driver/plan', 'driver/next-stop'):
        _check(body, PLAN_FIELDS + (('mode',) if path == 'driver/plan' else ()))
        soc = _number(body.get('soc_percent'), 'a bateria atual (%)', 0, 100)
        lat, lng = _coordinates(body)
        mode = body.get('mode') or 'auto'
        if mode not in ('auto', 'full_shift'):
            _fail('Escolha um modo de planejamento válido.')
        profile = _validated(merge_profile(api._driver_profile, body))
        stations = [api._station_row(station) for station in api._stations.values() if station['active']]
        now = _local_now(api)
        payload = {'soc_percent': soc, 'lat': lat, 'lng': lng, 'mode': mode, 'context': dict(body.get('context') or {})}
        live = body.get('live_signals') is not False
        signals = (simulated_weather(now),) if live else ()
        note = rain_note(signals[0], now) if live else None
        try:
            if path == 'driver/plan':
                result = build_plan(payload, profile, stations, now, signals, [note] if note else None)
                result['generated_at'] = now.isoformat()
            else:
                result = build_next_stop(payload, profile, stations, now, signals)
                result['alerts'] = ([note] if note else []) + result['alerts']
        except (ValueError, TypeError) as error:
            _fail(str(error) or 'Não foi possível planejar.', 'invalid_driver_plan')
        result['demand']['signals'] = deepcopy(SIGNALS_INFO) if live else [{'source': 'simulado', 'status': 'desativado'}]
        if result['demand'].get('weather') is None:
            result['demand']['weather'] = {'status': 'desativado', 'source': 'simulado', 'label': None}
        return result
    _fail('Esta operação não está disponível nesta conta.',
          'demo_route_not_supported', 404)
