from datetime import timedelta
from decimal import Decimal

import pytest
from test_http import clear_overrides, client_for

from app.models import Connector, Device, Station, now
from app.security import digest


def add_point(db, station, code, kind, price, online=True):
    point = Connector(station_id=station, public_code=code, connector_type=kind,
                      price_per_kwh=price, power_kw=22, max_duration_minutes=60)
    db.add(point)
    db.flush()
    db.add(Device(connector_id=point.id, key_hash=digest(code), reconciled=True,
                  last_seen=now() if online else now()-timedelta(days=1), physical_state='idle'))
    return point.id


def test_filters_use_same_point_and_apply_before_pagination(factory, seed):
    with factory.begin() as db:
        # The cheap offline CCS connector must not be combined with an available Type 2.
        eligible = add_point(db, seed['station'], 'TYPE-2', 'Type 2', 4)
        add_point(db, seed['station'], 'CHEAP', 'CCS2', 1, online=False)
        another = Station(owner_id=seed['owner'], name='Far cheaper', address='Away', latitude=.02, longitude=0)
        db.add(another)
        db.flush()
        far_id = str(another.id)
        add_point(db, another.id, 'FAR', 'Tipo 2', 3)
    client, _ = client_for(factory, seed['a'])
    try:
        params = {'connector_type':'TYPE-2','available_only':True,'sort':'price','limit':1}
        response = client.get('/v1/stations',params=params)
        assert response.status_code == 200
        data = response.json()
        assert data['total'] == 2 and data['items'][0]['id'] == far_id
        second = client.get('/v1/stations',params={**params,'offset':1}).json()['items'][0]
        assert second['discovery']['point']['id'] == str(eligible)
        assert Decimal(second['discovery']['point']['price_per_kwh']) == 4
        assert second['discovery']['matching_connector_ids'] == [str(eligible)]
        assert client.get('/v1/stations',params={**params,'max_price_per_kwh':2}).json()['total'] == 0
        assert client.get('/v1/stations',params={'connector_type':'ccs2','available_only':True}).json()['total'] == 0
        near = client.get('/v1/stations',params={**params,'sort':'distance','lat':0,'lng':0}).json()
        assert near['items'][0]['id'] == str(seed['station'])
        assert near['items'][0]['discovery']['distance_km'] == 0
    finally:
        clear_overrides()


@pytest.mark.parametrize('params',[
    {'sort':'distance'}, {'sort':'unknown'}, {'lat':0}, {'connector_type':' '},
    {'max_price_per_kwh':'NaN'}, {'max_price_per_kwh':'Infinity'}, {'max_price_per_kwh':-1},
    {'available_only':'maybe'}, {'radius_km':'NaN'},
])
def test_invalid_discovery_inputs_rejected(factory,seed,params):
    client, _ = client_for(factory,seed['a'])
    try:
        assert client.get('/v1/stations',params=params).status_code == 422
    finally:
        clear_overrides()


def test_default_discovery_only_serializes_requested_page(factory,seed,monkeypatch):
    from app.modules.stations import routes

    with factory.begin() as db:
        db.add_all([Station(owner_id=seed['owner'],name=f'Station {i}',address='Test',latitude=0,longitude=0)
                    for i in range(3)])
    rendered = []
    original = routes.station_row

    def tracked(db,station):
        rendered.append(station.id)
        return original(db,station)

    monkeypatch.setattr(routes,'station_row',tracked)
    client, _ = client_for(factory,seed['a'])
    try:
        response = client.get('/v1/stations',params={'limit':1})
        assert response.status_code == 200
        assert response.json()['total'] == 4
        assert len(rendered) == 1
    finally:
        clear_overrides()
