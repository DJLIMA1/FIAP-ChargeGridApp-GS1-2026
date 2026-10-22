"""Commercial speed choice keeps its tariff through quotes, reservations and START."""
from datetime import timedelta
from decimal import Decimal

import pytest
from test_http import clear_overrides, client_for

from app.models import Connector, Device, Profile, Reservation, Station, now
from app.modules.payments.schemas import PaymentInput
from app.modules.payments.service import quote
from app.presence_code import current_code

pytest_plugins = ("test_payments",)


@pytest.fixture(autouse=True)
def cleanup():
    yield
    clear_overrides()


def test_owner_customizes_both_speeds_in_existing_pricing_menu(factory, seed):
    owner, _ = client_for(factory, seed['owner'])
    url = f"/v1/stations/{seed['station']}/pricing"
    saved = owner.put(url, json={'speed': {'prices': {str(seed['point']): {'max': '3.00', 'reduced': '1.25'}}}})
    assert saved.status_code == 200, saved.text
    assert saved.json()['connectors'][0]['speed_prices'] == {'max': '3.0000', 'reduced': '1.2500'}
    assert owner.put(url, json={'demand': {'enabled': False}}).json()['connectors'][0]['speed_prices']['reduced'] == '1.2500'
    invalid = owner.put(url, json={'speed': {'prices': {str(seed['point']): {'max': '1', 'reduced': '2'}}}})
    assert invalid.status_code == 422
    client, _ = client_for(factory, seed['a'])
    point = client.get(f"/v1/stations/{seed['station']}").json()['connectors'][0]
    assert point['speed_prices'] == {'max': '3.0000', 'reduced': '1.2500'}
    assert point['dynamic_price_per_kwh'] == '3.0000'
    assert client.put(url, json={'speed': {'prices': {}}}).status_code in (403, 404)


def test_reduced_quote_has_lower_tariff_and_power_and_keeps_coupon_rules(factory, seed):
    with factory() as db:
        user, connector = db.get(Profile, seed['a']), db.get(Connector, seed['point'])
        maximum = quote(db, user, connector, PaymentInput(connector_id=connector.id, mode='time', minutes=60))
        reduced = quote(db, user, connector, PaymentInput(connector_id=connector.id, mode='time', minutes=60, power_tier='reduced'))
        assert maximum['price_per_kwh'] == Decimal('2')
        assert reduced['price_per_kwh'] == Decimal('1.6')
        assert reduced['quote']['power_kw'] == '0.500'
        assert reduced['max_power_kw'] == Decimal('.5')
        assert reduced['energy_cap_cents'] < maximum['energy_cap_cents']
        assert reduced['quote']['price_terms']['power_tier'] == 'reduced'


def test_direct_reduced_start_and_receipt_use_chosen_tier(factory, seed):
    client, _ = client_for(factory, seed['a'])
    with factory() as db:
        code = current_code(db.get(Station, seed['station']))[0]
    started = client.post('/v1/charging-sessions', headers={'Idempotency-Key': 'reduced-start'}, json={
        'public_code': 'CG-01', 'presence_code': code, 'power_tier': 'reduced'})
    assert started.status_code == 202, started.text
    session = started.json()
    assert session['power_tier'] == 'reduced'
    assert session['price_per_kwh'] == '1.6000'
    assert Decimal(session['power_limit_kw']) == Decimal('.5')
    receipt = client.get(f"/v1/charging-sessions/{session['id']}/receipt").json()
    assert receipt['price']['power_tier'] == 'reduced'
    assert receipt['price']['power_tier_label'] == 'Velocidade reduzida'


def test_reservation_locks_tier_and_custom_base_even_after_owner_changes(factory, seed):
    client, _ = client_for(factory, seed['a'])
    response = client.post('/v1/reservations', headers={'Idempotency-Key': 'reduced-reserve'}, json={
        'connector_id': str(seed['point']), 'power_tier': 'reduced'})
    assert response.status_code == 202, response.text
    reserved = response.json()
    assert reserved['power_tier'] == 'reduced'
    assert reserved['connector']['price_per_kwh'] == '1.6000'
    with factory.begin() as db:
        reservation = db.get(Reservation, reserved['id'])
        reservation.status, reservation.expires_at = 'confirmed', now() + timedelta(minutes=15)
        device = db.get(Device, seed['device'])
        device.physical_state, device.reconciled, device.last_seen = 'reserved', True, now()
        db.get(Station, seed['station']).pricing = {'speed': {'prices': {str(seed['point']): {'max': '5', 'reduced': '4'}}}}
        code = current_code(db.get(Station, seed['station']))[0]
    started = client.post('/v1/charging-sessions', headers={'Idempotency-Key': 'reserved-start'}, json={
        'reservation_id': reserved['id'], 'presence_code': code})
    assert started.status_code == 202, started.text
    assert started.json()['power_tier'] == 'reduced'
    assert started.json()['price_per_kwh'] == '1.6000'


def test_payment_contract_persists_speed(factory, seed, stripe):
    client, _ = client_for(factory, seed['a'])
    response = client.post('/v1/payments', headers={'Idempotency-Key': 'speed-payment'}, json={
        'connector_id': str(seed['point']), 'mode': 'value', 'max_cost': '20', 'power_tier': 'reduced'})
    assert response.status_code == 201, response.text
    payment = response.json()
    assert payment['power_tier'] == 'reduced'
    assert payment['quote']['price_terms']['power_tier'] == 'reduced'
    assert payment['price_per_kwh'] == '1.6000'


def test_paid_reduced_terms_survive_price_change_and_refund_unused_balance(flow, stripe, factory, seed):
    from test_payments import _paid

    payment = _paid(flow, stripe, power_tier='reduced')
    with factory.begin() as db:
        db.get(Station, seed['station']).pricing = {'speed': {'prices': {str(seed['point']): {'max': '9', 'reduced': '7'}}}}
    response = flow.start(payment_id=payment['id'])  # client default max cannot override the funded tier
    assert response.status_code == 202, response.text
    session = response.json()
    assert session['price_per_kwh'] == '1.6000'
    assert session['power_tier'] == 'reduced'
    flow.charge(session['id'], 500)
    flow.stop(session['id'], 500)
    settled = flow.get(payment['id'])
    assert settled['settlement']['charged'] == '0.80'
    assert settled['settlement']['returned'] == '19.20'


def test_legacy_qr_page_shows_both_speeds_and_passes_selection_to_checkout(client, seed, flow, factory):
    with factory.begin() as db:
        db.get(Station, seed['station']).kiosk_payments = True
    http = client[0]
    page = http.get(f"/pay/k/CG-01?c={flow.code()[2:]}")
    assert page.status_code == 200
    assert 'name="power_tier"' in page.text
    assert 'value="reduced"' in page.text
    created = http.post('/pay/k/CG-01', data={'c': flow.code()[2:], 'amount': '2000', 'power_tier': 'reduced'},
                        follow_redirects=False)
    assert created.status_code == 303, created.text


def test_station_search_uses_custom_maximum_tariff_instead_of_legacy_base(factory, seed):
    owner, _ = client_for(factory, seed['owner'])
    saved = owner.put(f"/v1/stations/{seed['station']}/pricing", json={'speed': {'prices': {
        str(seed['point']): {'max': '1', 'reduced': '.50'}}}})
    assert saved.status_code == 200
    client, _ = client_for(factory, seed['a'])
    response = client.get('/v1/stations?max_price_per_kwh=1.50&sort=price')
    assert response.status_code == 200, response.text
    assert response.json()['total'] == 1
    assert response.json()['items'][0]['discovery']['point']['speed_prices']['max'] == '1.0000'


def test_real_charger_capacity_limits_maximum_and_reduced_before_halving(factory, seed):
    from app.modules.charging.service import session_power_limit

    with factory.begin() as db:
        connector = db.get(Connector, seed['point'])
        connector.power_kw = Decimal(22)
        device = db.get(Device, seed['device'])
        device.charger = {'model': 'GoodWe HCA G2', 'transport': 'modbus_tcp', 'link': 'online',
                          'max_power_w': 7000, 'min_power_w': 1380, 'step_w': 230}
        db.flush()
        user = db.get(Profile, seed['a'])
        maximum = quote(db, user, connector, PaymentInput(connector_id=connector.id, mode='time', minutes=60))
        reduced = quote(db, user, connector, PaymentInput(connector_id=connector.id, mode='time', minutes=60,
                                                        power_tier='reduced'))
        assert Decimal(maximum['quote']['power_kw']) == 7
        assert Decimal(reduced['quote']['power_kw']) == Decimal('3.5')
        assert reduced['max_power_kw'] == Decimal('3.5')
        # A stale/offline hardware declaration cannot constrain a fresh nominal quote.
        device.charger = {**device.charger, 'link': 'offline'}
        assert session_power_limit(db, connector) > 7


@pytest.mark.parametrize('legacy_base,maximum,expected', [('0', '2', 402), ('2', '0', 202)])
def test_prepayment_requirement_uses_selected_tariff(factory, seed, legacy_base, maximum, expected):
    with factory.begin() as db:
        db.get(Connector, seed['point']).price_per_kwh = Decimal(legacy_base)
        station = db.get(Station, seed['station'])
        station.prepay_required = True
        station.pricing = {'speed': {'prices': {str(seed['point']): {'max': maximum}}}}
        code = current_code(station)[0]
    client, _ = client_for(factory, seed['a'])
    response = client.post('/v1/charging-sessions', headers={'Idempotency-Key': 'tier-prepay'}, json={
        'public_code': 'CG-01', 'presence_code': code})
    assert response.status_code == expected, response.text


@pytest.mark.parametrize('maximum,reduced,expected', [('2', '2', 422), ('0', '0', 200), ('2', '1.99', 200)])
def test_paid_speed_pair_requires_real_price_difference(factory, seed, maximum, reduced, expected):
    owner, _ = client_for(factory, seed['owner'])
    response = owner.put(f"/v1/stations/{seed['station']}/pricing", json={'speed': {'prices': {
        str(seed['point']): {'max': maximum, 'reduced': reduced}}}})
    assert response.status_code == expected, response.text
