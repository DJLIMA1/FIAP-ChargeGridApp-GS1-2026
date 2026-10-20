from datetime import datetime

import httpx
import pytest
from test_http import clear_overrides, client_for

from app.models import Connector, Device, Station, now
from app.modules.driver import routes, weather
from app.security import digest

SAO_PAULO = {'lat': -23.5505, 'lng': -46.6333}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    weather.clear_cache()
    monkeypatch.setattr(routes, 'DISCONTINUED', False)  # testes do código guardado (descontinuado)
    monkeypatch.setattr(routes, 'local_now', lambda: datetime(2026, 10, 13, 14, 0))  # terça, 14h
    monkeypatch.setattr(routes, 'weather_signal', lambda lat, lng: None)
    yield
    clear_overrides()


def add_station(db, owner, name, lat, lng, kind='CCS2', power=60, price='2.20', amenities=None):
    station = Station(owner_id=owner, name=name, address='Rua Teste, 1', latitude=lat, longitude=lng,
                      amenities=amenities or [])
    db.add(station)
    db.flush()
    point = Connector(station_id=station.id, public_code=f'DRV-{name}', connector_type=kind, power_kw=power,
                      price_per_kwh=price, max_duration_minutes=120)
    db.add(point)
    db.flush()
    db.add(Device(connector_id=point.id, key_hash=digest(f'driver-{name}'), reconciled=True, last_seen=now(),
                  physical_state='idle'))
    return station.id


def test_profile_defaults_put_validation_and_isolation(factory, seed):
    client, selected = client_for(factory, seed['a'])
    initial = client.get('/v1/driver/profile')
    assert initial.status_code == 200
    body = initial.json()
    assert body['saved'] is False and body['vehicle']['preset'] == 'byd_dolphin'
    assert any(preset['key'] == 'byd_seal' and preset['estimate'] for preset in body['presets'])
    profile = {'vehicle': {'preset': 'byd_seal'},
               'preferences': {'shift_start': '16:00', 'shift_end': '23:30', 'earnings_per_hour': 45,
                               'meals': [{'kind': 'jantar', 'start': '20:00', 'duration_minutes': 40,
                                          'flex_minutes': 30}]}}
    saved = client.put('/v1/driver/profile', json=profile)
    assert saved.status_code == 200, saved.text
    assert saved.json()['saved'] is True and saved.json()['preferences']['shift_end'] == '23:30'
    again = client.get('/v1/driver/profile').json()
    assert again['vehicle']['preset'] == 'byd_seal' and again['preferences']['meals'][0]['kind'] == 'jantar'
    # Atualização substitui o perfil (upsert), sem duplicar linha.
    assert client.put('/v1/driver/profile', json={'vehicle': {'preset': 'byd_dolphin_mini'}}).status_code == 200
    assert client.get('/v1/driver/profile').json()['vehicle']['preset'] == 'byd_dolphin_mini'
    for invalid in (
        {'vehicle': {'preset': 'carro_inexistente'}},
        {'preferences': {'reserve_percent': 45, 'max_charge_percent': 50}},
        {'preferences': {'shift_start': '25:00'}},
        {'preferences': {'earnings_per_hour': 'NaN'}},
        {'vehicle': {'usable_battery_kwh': 9999}},
        {'unknown': True},
    ):
        response = client.put('/v1/driver/profile', json=invalid)
        assert response.status_code == 422, invalid
    selected['id'] = seed['b']
    assert client.get('/v1/driver/profile').json()['saved'] is False


def test_owner_edits_amenities_and_discovery_exposes_them(factory, seed):
    owner, _ = client_for(factory, seed['owner'])
    amenities = [{'kind': 'restaurante', 'name': 'Cantina', 'distance_m': 50}, {'kind': 'banheiro'}]
    response = owner.patch(f"/v1/stations/{seed['station']}", json={'amenities': amenities})
    assert response.status_code == 200, response.text
    assert response.json()['amenities'][0] == {'kind': 'restaurante', 'name': 'Cantina', 'distance_m': 50}
    assert owner.patch(f"/v1/stations/{seed['station']}", json={'amenities': [{'kind': 'cinema'}]}).status_code == 422
    assert owner.patch(f"/v1/stations/{seed['station']}", json={'amenities': None}).status_code == 422
    driver, _ = client_for(factory, seed['a'])
    listed = driver.get('/v1/stations').json()['items'][0]
    assert [a['kind'] for a in listed['amenities']] == ['restaurante', 'banheiro']
    assert driver.patch(f"/v1/stations/{seed['station']}", json={'amenities': []}).status_code in (403, 404)


def test_plan_uses_real_stations_avoids_peak_and_couples_dinner(factory, seed):
    with factory.begin() as db:
        food = add_station(db, seed['owner'], 'Shopping', -23.56, -46.64, price='2.30',
                           amenities=[{'kind': 'restaurante', 'name': 'Praça de alimentação', 'distance_m': 80}])
        add_station(db, seed['owner'], 'Rapido', -23.552, -46.634, price='1.90')
        add_station(db, seed['owner'], 'Longe', -22.0, -45.0, price='0.50')  # fora do raio
    client, _ = client_for(factory, seed['a'])
    body = {'soc_percent': 65, **SAO_PAULO, 'mode': 'auto',
            'preferences': {'shift_start': '14:00', 'shift_end': '22:00',
                            'meals': [{'kind': 'jantar', 'start': '20:00', 'duration_minutes': 45,
                                       'flex_minutes': 30}]}}
    response = client.post('/v1/driver/plan', json=body)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan['estimate'] is True and plan['window']['start'] == '14:00' and plan['window']['end'] == '22:00'
    assert plan['stations_considered'] == 2  # bancada incompatível e posto fora do raio ignorados
    assert plan['demand']['source'] == 'heuristica'
    assert plan['demand']['signals'][0]['status'] == 'indisponivel'
    dinner = [stop for stop in plan['stops'] if stop['meal'] == 'Jantar']
    assert dinner and dinner[0]['station_id'] == str(food) and dinner[0]['connector_id']
    assert dinner[0]['reason'].startswith('Jantar às')
    assert not any(stop['in_peak'] for stop in plan['stops'])
    assert plan['comparison']['net_profit_gain'] >= 0
    assert {'blocks', 'slots', 'peaks', 'alerts', 'totals', 'baseline'} <= set(plan)


def test_plan_signal_from_open_meteo_and_silent_fallback(factory, seed, monkeypatch):
    with factory.begin() as db:
        add_station(db, seed['owner'], 'Rapido', -23.552, -46.634)
    client, _ = client_for(factory, seed['a'])
    hourly = {'time': [f'2026-10-13T{h:02d}:00' for h in range(24)],
              'precipitation': [3.0 if 18 <= h <= 20 else 0.0 for h in range(24)],
              'temperature_2m': [24.0] * 24}
    calls = []

    def fake_request(lat, lng):
        calls.append((lat, lng))
        return {'hourly': hourly}

    monkeypatch.setattr(weather, '_request', fake_request)
    monkeypatch.setattr(routes, 'weather_signal', weather.weather_signal)
    plan = client.post('/v1/driver/plan', json={'soc_percent': 50, **SAO_PAULO}).json()
    assert plan['demand']['source'] == 'heuristica+open-meteo'
    assert plan['demand']['signals'][0]['status'] == 'ok'
    assert any(alert['code'] == 'rain' and '18h' in alert['message'] for alert in plan['alerts'])
    client.post('/v1/driver/plan', json={'soc_percent': 50, **SAO_PAULO})
    assert len(calls) == 1  # cache por região

    weather.clear_cache()

    def broken(lat, lng):
        raise httpx.ConnectTimeout('lento')

    monkeypatch.setattr(weather, '_request', broken)
    fallback = client.post('/v1/driver/plan', json={'soc_percent': 50, **SAO_PAULO}).json()
    assert fallback['demand']['source'] == 'heuristica'
    assert fallback['demand']['signals'][0]['status'] == 'indisponivel'
    off = client.post('/v1/driver/plan', json={'soc_percent': 50, **SAO_PAULO, 'live_signals': False,
                                              'context': {'rain': True}}).json()
    assert off['demand']['source'] == 'heuristica+informado'


def test_context_shows_weather_demand_and_earnings_source_without_planning(factory, seed, monkeypatch):
    client, _ = client_for(factory, seed['a'])
    hours = [f'2026-10-13T{h:02d}:00' for h in range(24)]
    payload = {'hourly': {'time': hours, 'precipitation': [2.0 if h == 18 else 0.0 for h in range(24)],
                          'temperature_2m': [25.0] * 24, 'weather_code': [61 if h == 18 else 3 for h in range(24)]},
               'current': {'time': '2026-10-13T13:45', 'temperature_2m': 24.4, 'precipitation': 0.0,
                           'weather_code': 2}}
    monkeypatch.setattr(weather, '_request', lambda lat, lng: payload)
    monkeypatch.setattr(routes, 'weather_signal', weather.weather_signal)
    response = client.get('/v1/driver/context', params=SAO_PAULO)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['estimate'] is True and body['in_shift'] is True and body['window']['end'] == '22:00'
    assert body['weather']['status'] == 'ok'
    assert body['weather']['label'] == '24° · parcialmente nublado · chuva às 18h'
    assert body['demand']['source'] == 'heuristica+open-meteo' and body['demand']['peaks']
    assert body['earnings'] == {'per_hour': 38.0, 'source': 'estimativa', 'estimated': True,
                                'label': 'R$ 38/h estimado'}
    assert any(alert['code'] == 'rain' for alert in body['alerts'])
    plan = client.post('/v1/driver/plan', json={'soc_percent': 50, **SAO_PAULO}).json()
    assert plan['demand']['weather']['label'].startswith('24°')
    assert plan['earnings']['estimated'] is True
    assert any('estimado pelo ChargeGrid' in text for text in plan['assumptions'])
    # Sem localização: sem clima, e a resposta diz o motivo.
    blind = client.get('/v1/driver/context').json()
    assert blind['weather']['status'] == 'sem_localizacao' and blind['weather']['label'] is None
    assert client.get('/v1/driver/context', params={'lat': -23.5}).status_code == 422
    assert client.get('/v1/driver/context', params={'lat': 200, 'lng': 0}).status_code == 422


def test_profile_sources_mark_typed_values_and_legacy_profiles_are_inferred(factory, seed):
    client, _ = client_for(factory, seed['a'])
    typed = client.put('/v1/driver/profile', json={'preferences': {
        'earnings_per_hour': 38, 'sources': {'earnings_per_hour': 'informado', 'shift': 'auto'}}})
    assert typed.status_code == 200, typed.text
    assert typed.json()['preferences']['sources'] == {'earnings_per_hour': 'informado', 'shift': 'auto'}
    assert client.get('/v1/driver/context').json()['earnings']['label'] == 'R$ 38/h (seu ganho)'
    # App antigo (sem ``sources``) que digitou outro ganho e outro turno: vira "informado".
    legacy = client.put('/v1/driver/profile', json={'preferences': {
        'earnings_per_hour': 52, 'shift_start': '06:00', 'shift_end': '14:00'}}).json()
    assert legacy['preferences']['sources'] == {'earnings_per_hour': 'informado', 'shift': 'informado'}
    for invalid in ({'sources': {'earnings_per_hour': 'chute'}}, {'sources': {'outro': 'auto'}}):
        assert client.put('/v1/driver/profile', json={'preferences': invalid}).status_code == 422, invalid


def test_next_stop_and_input_validation(factory, seed):
    with factory.begin() as db:
        add_station(db, seed['owner'], 'Rapido', -23.552, -46.634)
    client, _ = client_for(factory, seed['a'])
    client.put('/v1/driver/profile', json={'preferences': {'shift_start': '10:00', 'shift_end': '20:00'}})
    urgent = client.post('/v1/driver/next-stop', json={'soc_percent': 16, **SAO_PAULO})
    assert urgent.status_code == 200, urgent.text
    result = urgent.json()
    assert result['recommendation']['action'] == 'stop_now'
    assert result['alternatives'][0]['station_name'] == 'Rapido'
    relaxed = client.post('/v1/driver/next-stop', json={'soc_percent': 95, **SAO_PAULO}).json()
    assert relaxed['recommendation']['action'] == 'keep_driving'
    for invalid in ({'soc_percent': 120}, {'soc_percent': 50, 'lat': -23.5}, {'soc_percent': 'NaN'},
                    {'soc_percent': 50, 'mode': 'x'}, {}):
        assert client.post('/v1/driver/plan', json=invalid).status_code == 422, invalid
    empty = client.post('/v1/driver/plan', json={'soc_percent': 20, 'lat': 10.0, 'lng': 10.0}).json()
    assert {'needs_charge', 'no_station'} <= {alert['code'] for alert in empty['alerts']}


def test_driver_routes_require_authentication(factory, seed):
    from fastapi.testclient import TestClient

    from app.main import app
    clear_overrides()
    anonymous = TestClient(app)
    assert anonymous.get('/v1/driver/profile').status_code == 401
    assert anonymous.post('/v1/driver/plan', json={'soc_percent': 50}).status_code == 401
    assert anonymous.get('/v1/driver/context').status_code == 401


def test_driver_mode_is_discontinued_in_production(factory, seed, monkeypatch):
    monkeypatch.setattr(routes, 'DISCONTINUED', True)
    client, _ = client_for(factory, seed['a'])
    for method, path in (('GET', '/v1/driver/profile'), ('POST', '/v1/driver/plan'),
                         ('POST', '/v1/driver/next-stop'), ('GET', '/v1/driver/context')):
        response = client.request(method, path, json={} if method == 'POST' else None)
        assert response.status_code == 410, (path, response.text)
        assert response.json()['error']['code'] == 'driver_mode_discontinued'
