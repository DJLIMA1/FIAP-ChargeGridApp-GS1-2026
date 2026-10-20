import httpx
import pytest
from test_http import clear_overrides, client_for

from app.modules.geo import service

PAULISTA = {'type': 'Feature', 'geometry': {'coordinates': [-46.651918, -23.5648865]},
            'properties': {'osm_key': 'place', 'housenumber': '1000', 'street': 'Avenida Paulista',
                           'district': 'Bela Vista', 'city': 'São Paulo', 'state': 'São Paulo',
                           'postcode': '01310-100', 'countrycode': 'BR'}}
AUGUSTA = {'type': 'Feature', 'geometry': {'coordinates': [-46.65, -23.55]},
           'properties': {'osm_key': 'highway', 'name': 'Rua Augusta', 'district': 'Consolação',
                          'city': 'São Paulo', 'state': 'São Paulo', 'countrycode': 'BR'}}
ABROAD = {'type': 'Feature', 'geometry': {'coordinates': [-58.4, -34.6]},
          'properties': {'street': 'Avenida Paulista', 'city': 'Buenos Aires', 'countrycode': 'AR'}}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    service.clear_cache()
    calls = []

    def fake_get(url, params=None):
        calls.append((url, params))
        if 'viacep' in url:
            if url.endswith('/99999999/json/'):
                return {'erro': True}
            return {'cep': '01310-100', 'logradouro': 'Avenida Paulista', 'bairro': 'Bela Vista',
                    'localidade': 'São Paulo', 'uf': 'SP'}
        return {'features': [ABROAD, PAULISTA, AUGUSTA, PAULISTA]}
    monkeypatch.setattr(service, '_get', fake_get)
    yield calls
    clear_overrides()
    service.clear_cache()


def test_free_text_uses_photon_in_brazil_and_formats_like_saved_addresses(factory, seed, isolated):
    client, _ = client_for(factory, seed['a'])
    response = client.get('/v1/geo/address-suggestions', params={'q': 'av paulista 1000', 'lat': -23.55, 'lng': -46.63})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['available'] is True and 'OpenStreetMap' in body['attribution']
    labels = [item['label'] for item in body['items']]
    # País filtrado, duplicata removida, UF abreviada e número digitado aplicado à rua sem número.
    assert labels == ['Avenida Paulista, 1000, Bela Vista, São Paulo - SP',
                      'Rua Augusta, 1000, Consolação, São Paulo - SP']
    assert body['items'][0]['latitude'] == -23.5648865 and body['items'][0]['postcode'] == '01310-100'
    url, params = isolated[0]
    assert 'photon' in url and params['bbox'] == service.BRAZIL_BBOX and params['lat'] == -23.55
    # Cache: a mesma busca não consulta o provedor de novo.
    client.get('/v1/geo/address-suggestions', params={'q': 'Av Paulista  1000', 'lat': -23.55, 'lng': -46.63})
    assert len(isolated) == 1


def test_cep_uses_viacep_then_photon_for_coordinates(factory, seed, isolated):
    client, _ = client_for(factory, seed['a'])
    body = client.get('/v1/geo/address-suggestions', params={'q': '01310-100'}).json()
    assert [item['label'] for item in body['items']] == ['Avenida Paulista, Bela Vista, São Paulo - SP']
    assert body['items'][0]['latitude'] == -23.5648865
    assert 'viacep.com.br/ws/01310100/json/' in isolated[0][0] and 'photon' in isolated[1][0]
    assert client.get('/v1/geo/address-suggestions', params={'q': '99999-999'}).json()['items'] == []


def test_short_query_provider_failure_auth_and_validation(factory, seed, monkeypatch, isolated):
    client, _ = client_for(factory, seed['a'])
    assert client.get('/v1/geo/address-suggestions', params={'q': 'av'}).json()['items'] == []
    assert isolated == []

    def broken(url, params=None):
        raise httpx.ConnectTimeout('offline')
    monkeypatch.setattr(service, '_get', broken)
    body = client.get('/v1/geo/address-suggestions', params={'q': 'rua qualquer'}).json()
    assert body == {'items': [], 'available': False, 'attribution': service.ATTRIBUTION}
    assert client.get('/v1/geo/address-suggestions', params={'q': 'rua x', 'lat': 1}).status_code == 422


def test_route_requires_a_signed_in_user():
    import inspect

    from app.main import app
    from app.modules.geo.routes import address_suggestions
    from app.security import current_user
    assert app.url_path_for('address_suggestions') == '/v1/geo/address-suggestions'
    assert inspect.signature(address_suggestions).parameters['user'].default.dependency is current_user
