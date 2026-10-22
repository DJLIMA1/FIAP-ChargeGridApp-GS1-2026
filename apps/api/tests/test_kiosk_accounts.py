"""Account kiosk coverage: independently authenticated identity, saved car and simulated wallet."""
import uuid
from decimal import Decimal

import pytest
from fastapi import Depends
from test_kiosk_totem import DEVICE, Bench

from app.database import db_session
from app.main import app
from app.models import Profile
from app.modules.kiosk_totem import account
from chargegrid_core.charge_plan import autonomy_energy

pytest_plugins = ("test_kiosk_totem",)

@pytest.fixture
def logged(factory, seed):
    def user(db=Depends(db_session)):
        return db.get(Profile, seed['a'])
    app.dependency_overrides[account.kiosk_user] = user
    yield
    app.dependency_overrides.pop(account.kiosk_user, None)


def test_guest_cannot_use_autonomy_or_balance(http, presentation):
    bench = Bench(http)
    response = bench.quote(mode='autonomy', autonomy_km=60)
    assert response.status_code == 401
    order = bench.order().json()
    response = bench.pay(order['id'], funding_source='balance')
    assert response.status_code == 401


def test_account_vehicle_and_power(http, presentation, logged):
    bench = Bench(http)
    assert bench.offer().json()['account']['vehicle'] is None
    assert bench.quote(mode='autonomy', autonomy_km=60).status_code == 422
    saved = http.put('/v1/me/vehicle', json={'vehicle': {'preset': 'byd_dolphin'}, 'preferences': {}})
    assert saved.status_code == 200, saved.text
    assert http.get('/v1/me/vehicle').json()['saved']
    offer = bench.offer().json()
    assert offer['account']['vehicle']['name']
    quote = bench.quote(mode='autonomy', autonomy_km=60, power='reduced')
    assert quote.status_code == 200, quote.text
    assert quote.json()['mode'] == 'autonomy'
    assert quote.json()['autonomy_km'] == 60
    assert float(quote.json()['power_kw']) <= float(offer['power_kw']) / 2
    car = offer['account']['vehicle']
    expected = autonomy_energy(60, car['consumption_kwh_per_100km'], 0, car['usable_battery_kwh'])
    assert Decimal(quote.json()['energy_kwh']) == expected['energy_kwh']
    assert quote.json()['autonomy']['km'] == expected['km']
    short = bench.quote(mode='autonomy', autonomy_km=5)
    assert short.status_code == 200, short.text
    assert Decimal(short.json()['energy_kwh']) < 1
    body = {'mode': 'autonomy', 'autonomy_km': 60, 'power': 'reduced',
            'quote_hash': quote.json()['quote_hash'], 'overstay_terms_version': quote.json()['overstay']['version']}
    created = http.post('/v1/devices/kiosk/orders', headers={**DEVICE, 'Idempotency-Key': uuid.uuid4().hex}, json=body)
    assert created.status_code == 201, created.text


def test_shared_simulated_wallet_payment_and_refund(http, presentation, logged):
    headers = {'Idempotency-Key': 'legacy-import'}
    move = {'kind': 'import', 'amount': '100.00'}
    assert http.post('/v1/me/wallet/simulate', headers=headers, json=move).json()['balance'] == '100.00'
    assert http.post('/v1/me/wallet/simulate', headers=headers, json=move).json()['balance'] == '100.00'
    bench = Bench(http)
    offer = bench.offer().json()
    assert offer['balance_available']
    assert offer['account']['wallet']['balance'] == '100.00'
    order = bench.order().json()
    amount = float(order['quote']['total'])
    pay_key = bench.key()
    response = bench.pay(order['id'], key=pay_key, funding_source='balance')
    assert response.status_code == 200, response.text
    assert bench.pay(order['id'], key=pay_key, funding_source='balance').status_code == 200
    assert float(http.get('/v1/me/wallet').json()['balance']) == 100 - amount
    sid, _ = bench.apply_start()
    bench.charge_and_stop_locally(sid, energy_wh=1000)
    bench.sync(connected=False)
    bench.get(order['id'])
    final = http.get('/v1/me/wallet').json()
    assert float(final['balance']) > 100 - amount
    assert len([x for x in final['transactions'] if x['key'].startswith('payment-refund:')]) == 1
    bench.get(order['id'])
    assert http.get('/v1/me/wallet').json()['balance'] == final['balance']


def test_insufficient_balance_never_pays(http, presentation, logged):
    bench = Bench(http)
    order = bench.order().json()
    response = bench.pay(order['id'], funding_source='balance')
    assert response.status_code == 402, response.text
    assert bench.get(order['id']).json()['payment'] is None


def test_simulated_balance_cannot_fund_stripe(http, stripe, logged):
    bench = Bench(http)
    assert bench.offer().json()['balance_available'] is False
    order = bench.order().json()
    assert bench.pay(order['id'], funding_source='balance').status_code == 409


def test_kiosk_selects_only_chargers_managed_by_its_central(http, presentation, factory, seed):
    from app.models import Connector, Device, now
    from app.security import digest
    with factory.begin() as db:
        child_point = Connector(station_id=seed['station'], public_code='CG-02', connector_type='Tipo 2',
                                power_kw=1, price_per_kwh=2, max_duration_minutes=60, charger_address=2)
        db.add(child_point)
        db.flush()
        child = Device(connector_id=child_point.id, parent_device_id=seed['device'], key_hash=digest('child-key'),
                       last_seen=now(), physical_state='idle', reconciled=True,
                       charger={'model': 'goodwe_hca_g2', 'transport': 'modbus_tcp', 'address': 2, 'link': 'online'})
        db.add(child)
    headers = {**DEVICE, 'X-Kiosk-Charger-Address': '2'}
    offer = http.get('/v1/devices/kiosk/offer', headers=headers)
    assert offer.status_code == 200, offer.text
    assert offer.json()['public_code'] == 'CG-02'
    assert [x['address'] for x in offer.json()['connectors']] == [0, 2]
    with factory.begin() as db:
        db.get(Connector, seed['point']).active = False
    central_offer = http.get('/v1/devices/kiosk/offer', headers=DEVICE).json()
    assert central_offer['enabled'] and not central_offer['available']
    assert central_offer['connectors'][0]['address'] == 2
    quote = http.post('/v1/devices/kiosk/quote', headers=headers, json={'mode': 'value', 'amount': '20'})
    assert quote.status_code == 200, quote.text
    body = {'mode': 'value', 'amount': '20', 'quote_hash': quote.json()['quote_hash'],
            'overstay_terms_version': quote.json()['overstay']['version']}
    order = http.post('/v1/devices/kiosk/orders', headers={**headers, 'Idempotency-Key': uuid.uuid4().hex}, json=body)
    assert order.status_code == 201, order.text
    order_id = order.json()['id']
    assert http.get(f'/v1/devices/kiosk/orders/{order_id}', headers=DEVICE).status_code == 404
    assert http.get(f'/v1/devices/kiosk/orders/{order_id}', headers=headers).status_code == 200
    assert http.get('/v1/devices/kiosk/offer', headers={**DEVICE, 'X-Kiosk-Charger-Address': '3'}).status_code == 409


def _account_start(http, factory):
    """Recarga por valor da conta no totem até o START; devolve os parâmetros e a sessão."""
    from app.models import ChargingSession
    bench = Bench(http)
    bench.sync()
    order = bench.order().json()
    assert bench.pay(order['id']).status_code == 200
    session_id, synced = bench.apply_start()
    start = next(cmd for cmd in synced['commands'] if cmd['type'] == 'START')['parameters']
    with factory() as db:
        session = db.get(ChargingSession, uuid.UUID(session_id))
        return bench, start, session


def _finish(bench, session_id):
    bench.charge_and_stop_locally(session_id, energy_wh=1000)
    bench.sync(connected=False)


@pytest.mark.parametrize('saved', [False, True])
def test_account_without_battery_history_gets_simulated_battery(http, presentation, logged, factory, saved):
    if saved:
        car = {'vehicle': {'preset': 'byd_seal'}, 'preferences': {}}
        assert http.put('/v1/me/vehicle', json=car).status_code == 200
    _, start, session = _account_start(http, factory)
    assert start['soc_source'] == 'simulated' and 15 <= start['soc_percent'] <= 60
    assert start['battery_kwh'] == (82.5 if saved else 44.9)  # carro salvo; sem carro, o padrão do app
    assert session.start_soc_percent == Decimal(str(start['soc_percent']))


@pytest.mark.parametrize('previous, inherited', [('80.00', True), ('94.99', True), ('95.00', False),
                                                 ('100.00', False)])
def test_account_inherits_last_soc_below_95_else_redraws(http, presentation, logged, factory, seed,
                                                         previous, inherited):
    from app.models import ChargingSession
    assert http.put('/v1/me/vehicle', json={'vehicle': {'preset': 'byd_dolphin'}, 'preferences': {}}).status_code == 200
    bench, _, first = _account_start(http, factory)
    _finish(bench, str(first.id))
    with factory.begin() as db:
        db.get(ChargingSession, first.id).soc_percent = Decimal(previous)
    _, start, session = _account_start(http, factory)
    assert start['soc_source'] == 'simulated' and start['battery_kwh'] == 44.9
    if inherited:
        assert Decimal(str(start['soc_percent'])) == Decimal(previous)
    else:
        assert 15 <= start['soc_percent'] <= 60
    assert session.status in ('starting', 'charging') and session.end_reason is None
