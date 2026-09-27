import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import (
    DEMO_CLAIM_TOKEN,
    DEMO_EMAIL,
    DEMO_PASSWORD,
    DEMO_PRESENCE_CODE,
    DemoApi,
)


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class DemoClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = Clock()
        self.client = DemoApi(clock=self.clock, start_at=datetime(2026, 9, 27, 15, tzinfo=timezone.utc))
        await self.client.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.station = (await self.client.request('GET', 'stations'))['items'][0]
        self.point = next(p for p in self.station['connectors'] if p['available'])

    async def asyncTearDown(self):
        await self.client.close()

    async def start(self, **changes):
        body = {'presence_code': DEMO_PRESENCE_CODE, 'public_code': self.point['public_code']}
        body.update(changes)
        return await self.client.request('POST', 'charging-sessions', body, key=self.client.new_key())

    async def assert_error(self, method, path, *, code, **kwargs):
        with self.assertRaises(ApiError) as caught:
            await self.client.request(method, path, **kwargs)
        self.assertEqual(caught.exception.code, code)

    async def test_login_logout_and_invalid_credentials_never_construct_network_client(self):
        with patch('httpx.AsyncClient', side_effect=AssertionError('network client constructed')):
            isolated = DemoApi(clock=self.clock)
            self.assertFalse(hasattr(isolated, 'http'))
            self.assertTrue(isolated.is_demo)
            with self.assertRaises(ApiError):
                await isolated.request('GET', 'me', auth=False)
            for email, password in [('real@example.com', DEMO_PASSWORD), (DEMO_EMAIL, 'wrong')]:
                with self.assertRaises(ApiError):
                    await isolated.login(email, password)
            await isolated.login(DEMO_EMAIL.upper(), DEMO_PASSWORD)
            self.assertEqual((await isolated.request('GET', 'me'))['account_type'], 'vendor')
            await isolated.refresh()
            self.assertIn('DEMO', isolated.session.access_token)
            await isolated.request('PATCH', 'me', {'name': 'Changed only here'})
            await isolated.request('POST', 'auth/logout')
            self.assertIsNone(isolated.session.access_token)
            self.assertEqual(isolated._profile, {})
            await isolated.login(DEMO_EMAIL, DEMO_PASSWORD)
            self.assertEqual((await isolated.request('GET', 'me'))['name'], 'Conta demonstração')
            await isolated.close()

    async def test_instances_and_response_snapshots_are_isolated(self):
        other = DemoApi(clock=self.clock)
        await other.login(DEMO_EMAIL, DEMO_PASSWORD)
        try:
            snapshot = await self.client.request('GET', 'stations')
            snapshot['items'][0]['connectors'][0]['price_per_kwh'] = '999'
            snapshot['items'][0]['name'] = 'External mutation'
            self.assertEqual((await self.client.request('GET', f"stations/{self.station['id']}"))['name'], self.station['name'])
            await self.client.request('PATCH', 'me', {'name': 'Private local edit'})
            self.assertEqual((await other.request('GET', 'me'))['name'], 'Conta demonstração')
            await self.client.request('POST', 'ownership/claim', {'token': DEMO_CLAIM_TOKEN})
            own = await self.client.request('GET', 'operator/stations')
            other_rows = await other.request('GET', 'operator/stations')
            self.assertEqual(own['total'], other_rows['total'] + 1)
        finally:
            await other.close()

    async def test_unknown_routes_explicitly_fail_without_network_or_real_device_access(self):
        with patch('httpx.AsyncClient', side_effect=AssertionError('no transport')):
            for method, path in [('POST', 'devices/sync'), ('DELETE', f"stations/{self.station['id']}"),
                                 ('GET', 'https://real.example/api'), ('POST', 'payments')]:
                await self.assert_error(method, path, code='demo_route_not_supported')
            await self.assert_error('POST', 'ownership/claim', body={'token': 'real-secret'}, code='invalid_claim')

    async def test_poll_count_does_not_advance_reservation_or_charging(self):
        reservation = await self.client.request('POST', 'reservations', {'connector_id': self.point['id']}, key='reserve')
        for _ in range(10):
            self.assertEqual(await self.client.request('GET', 'reservations/current'), reservation)
        self.clock.advance(1)
        confirmed = await self.client.request('GET', 'reservations/current')
        self.assertEqual(confirmed['status'], 'confirmed')
        self.assertEqual(reservation['status'], 'pending_device')
        started = await self.start(reservation_id=reservation['id'])
        for _ in range(5):
            self.assertEqual((await self.client.request('GET', 'charging-sessions/current'))['status'], 'starting')
        self.clock.advance(6)
        charging = await self.client.request('GET', f"charging-sessions/{started['id']}")
        self.assertEqual(charging['status'], 'charging')
        self.assertEqual(charging['energy_wh'], '10.000')
        for _ in range(10):
            self.assertEqual(await self.client.request('GET', 'charging-sessions/current'), charging)

    async def test_reservation_occupancy_cancellation_expiration_and_maintenance_guards(self):
        offline = next(p for p in self.station['connectors'] if not p['online'])
        await self.assert_error('POST', 'reservations', body={'connector_id': offline['id']}, key='offline', code='point_unavailable')
        reservation = await self.client.request('POST', 'reservations', {'connector_id': self.point['id']}, key='one')
        await self.assert_error('POST', 'reservations', body={'connector_id': offline['id']}, key='two', code='user_busy')
        device = await self.client.request('GET', f"connectors/{self.point['id']}/device")
        self.assertEqual(await self.client.request('GET', f"devices/{device['device_id']}/factory-reset"), {'status': 'not_requested'})
        await self.assert_error('POST', f"devices/{device['device_id']}/factory-reset", code='point_busy')
        await self.assert_error('PATCH', f"connectors/{self.point['id']}", body={'price_per_kwh': '9'}, code='point_busy')
        await self.assert_error('PATCH', f"stations/{self.station['id']}", body={'active': False}, code='point_busy')
        cancelling = await self.client.request('POST', f"reservations/{reservation['id']}/cancel")
        self.assertEqual(cancelling['status'], 'cancelling')
        self.clock.advance(1)
        self.assertIsNone(await self.client.request('GET', 'reservations/current'))
        self.assertEqual((await self.client.request('POST', f"reservations/{reservation['id']}/cancel"))['status'], 'cancelled')
        await self.client.request('POST', 'reservations', {'connector_id': self.point['id']}, key='new-reservation')
        self.clock.advance(602)
        self.assertIsNone(await self.client.request('GET', 'reservations/current'))
        points = (await self.client.request('GET', f"stations/{self.station['id']}"))['connectors']
        self.assertTrue(next(p for p in points if p['id'] == self.point['id'])['available'])

    async def test_cost_limit_discount_and_snapshot_are_clock_based(self):
        session = await self.start(max_cost='0.0300', coupon_code='DEMO10', max_duration_minutes=30)
        self.clock.advance(3)
        active = await self.client.request('GET', f"charging-sessions/{session['id']}")
        self.assertGreater(Decimal(active['energy_wh']), 0)
        await self.assert_error('PATCH', f"connectors/{self.point['id']}", body={'price_per_kwh': '10'}, code='point_busy')
        self.clock.advance(30)
        final = await self.client.request('GET', f"charging-sessions/{session['id']}")
        self.assertEqual(final['status'], 'completed')
        self.assertEqual(final['end_reason'], 'cost_limit')
        self.assertLessEqual(Decimal(final['cost_estimate']), Decimal('0.0300'))
        self.assertAlmostEqual(float(final['energy_wh']), float(Decimal('0.0300') / Decimal('1.35') * 1000), places=2)
        self.assertEqual(final['discount_percent'], 10)
        await self.client.request('PATCH', f"connectors/{self.point['id']}", {'price_per_kwh': '10'})
        history = await self.client.request('GET', f"charging-sessions/{session['id']}")
        self.assertEqual(history['price_per_kwh'], '1.5000')
        self.assertEqual(history['connector']['price_per_kwh'], '10.0000')
        self.assertEqual(history['cost_estimate'], final['cost_estimate'])

    async def test_duration_limit_and_manual_stop_are_terminal_and_allow_another_session(self):
        session = await self.start(max_duration_minutes=1)
        self.clock.advance(1000)
        final = await self.client.request('GET', f"charging-sessions/{session['id']}")
        self.assertEqual(final['end_reason'], 'duration_limit')
        self.assertEqual(final['energy_wh'], '120.000')
        self.assertEqual(final['cost_estimate'], '0.1800')
        self.assertIsNone(await self.client.request('GET', 'charging-sessions/current'))
        self.client.clear_operation('charging-sessions')
        another = await self.start(max_duration_minutes=2)
        self.clock.advance(6)
        active = await self.client.request('GET', f"charging-sessions/{another['id']}")
        self.assertEqual(active['energy_wh'], '10.000')
        stopping = await self.client.request('POST', f"charging-sessions/{another['id']}/stop", key='stop')
        self.assertEqual(stopping['status'], 'stopping')
        self.clock.advance(10)
        stopped = await self.client.request('GET', f"charging-sessions/{another['id']}")
        self.assertEqual(stopped['status'], 'completed')
        self.assertEqual(stopped['end_reason'], 'requested')
        self.assertEqual(stopped['energy_wh'], '12.000')
        self.clock.advance(100)
        self.assertEqual(await self.client.request('GET', f"charging-sessions/{another['id']}"), stopped)

    async def test_stop_before_confirmation_never_generates_energy(self):
        session = await self.start()
        await self.client.request('POST', f"charging-sessions/{session['id']}/stop", key='stop-before-start')
        self.clock.advance(100)
        final = await self.client.request('GET', f"charging-sessions/{session['id']}")
        self.assertEqual(final['status'], 'failed')
        self.assertEqual(final['energy_wh'], '0.000')
        self.assertIsNone(final['started_at'])

    async def test_idempotency_preserves_result_and_rejects_conflicting_body(self):
        body = {'public_code': self.point['public_code'], 'presence_code': DEMO_PRESENCE_CODE, 'max_duration_minutes': 1}
        first = await self.client.request('POST', 'charging-sessions', body, key='stable')
        second = await self.client.request('POST', 'charging-sessions', dict(body), key='new-key-after-redraw')
        self.assertEqual(second['id'], first['id'])
        self.assertEqual(self.client.last_session_id, first['id'])
        await self.assert_error('POST', 'charging-sessions', body={**body, 'max_duration_minutes': 2}, key='stable', code='idempotency_conflict')
        self.clock.advance(100)
        repeated = await self.client.request('POST', 'charging-sessions', body, key='stable')
        self.assertEqual(repeated['id'], first['id'])
        self.assertEqual(repeated['status'], 'completed')
        await self.client.request('GET', f"charging-sessions/{first['id']}")
        third = await self.client.request('POST', 'charging-sessions', body, key='new-session')
        self.assertNotEqual(third['id'], first['id'])

    async def test_invalid_limits_and_codes_do_not_create_sessions(self):
        history = await self.client.request('GET', 'me/charging-sessions')
        base = {'public_code': self.point['public_code'], 'presence_code': DEMO_PRESENCE_CODE}
        for changed in ({'presence_code': '#F00000'}, {'max_cost': 'NaN'}, {'max_cost': '0'},
                        {'max_duration_minutes': 121}, {'max_duration_minutes': 1.5}, {'coupon_code': 'UNKNOWN'}):
            with self.subTest(changed=changed), self.assertRaises(ApiError):
                await self.client.request('POST', 'charging-sessions', {**base, **changed}, key=self.client.new_key())
        self.assertIsNone(await self.client.request('GET', 'charging-sessions/current'))
        self.assertEqual((await self.client.request('GET', 'me/charging-sessions'))['total'], history['total'])

    async def test_claim_publish_extra_point_and_idempotent_claim(self):
        token = self.client.new_claim_token()
        self.assertEqual(len(token), 43)
        claim = await self.client.request('POST', 'ownership/claim', {'token': token})
        replay = await self.client.request('POST', 'ownership/claim', {'token': token})
        self.assertTrue(replay['already_claimed'])
        self.assertEqual(claim['connector_id'], replay['connector_id'])
        station = await self.client.request('GET', f"stations/{claim['station_id']}")
        self.assertFalse(station['active'])
        self.assertFalse(station['connectors'][0]['active'])
        await self.client.request('PATCH', f"stations/{station['id']}", {'name': 'Meu posto fictício', 'address': 'Rua simulada, 1', 'latitude': -23.56, 'longitude': -46.64})
        await self.client.request('PATCH', f"connectors/{claim['connector_id']}", {'price_per_kwh': '2.30', 'active': True})
        self.assertNotIn(station['id'], [s['id'] for s in (await self.client.request('GET', 'stations'))['items']])
        await self.client.request('PATCH', f"stations/{station['id']}", {'active': True})
        published = await self.client.request('GET', f"stations/{station['id']}")
        self.assertTrue(published['connectors'][0]['available'])
        extra = await self.client.request('POST', 'ownership/claim', {'token': self.client.new_claim_token(), 'station_id': station['id']})
        self.assertEqual(extra['station_id'], station['id'])
        self.assertEqual(len((await self.client.request('GET', f"stations/{station['id']}"))['connectors']), 2)
        await self.assert_error('POST', 'ownership/claim', body={'token': token, 'station_id': self.station['id']}, code='already_claimed')
        await self.assert_error('POST', 'charging-sessions', body={'presence_code': DEMO_PRESENCE_CODE}, key='ambiguous', code='ambiguous_presence_code')

    async def test_device_credentials_and_reset_are_fake_and_clock_driven(self):
        device = await self.client.request('GET', f"connectors/{self.point['id']}/device")
        rotated = await self.client.request('POST', f"devices/{device['device_id']}/rotate-key")
        self.assertIn('FAKE', rotated['device_key'])
        self.assertNotIn('device_key', await self.client.request('GET', f"connectors/{self.point['id']}/device"))
        await self.client.request('POST', f"devices/{device['device_id']}/revoke")
        await self.assert_error('GET', f"connectors/{self.point['id']}/device", code='not_found')
        provisioned = await self.client.request('POST', f"connectors/{self.point['id']}/device")
        self.assertIn('FAKE', provisioned['device_key'])
        endpoint = f"devices/{provisioned['device_id']}/factory-reset"
        reset = await self.client.request('POST', endpoint)
        self.assertEqual(reset['status'], 'pending')
        self.assertEqual(await self.client.request('POST', endpoint), reset)
        await self.assert_error('POST', f"devices/{provisioned['device_id']}/rotate-key", code='reset_pending')
        await self.assert_error('PATCH', f"connectors/{self.point['id']}", body={'active': True}, code='point_retired')
        self.clock.advance(2)
        self.assertEqual((await self.client.request('GET', endpoint))['status'], 'applied')
        retired = await self.client.request('GET', f"connectors/{self.point['id']}/device")
        self.assertTrue(retired['retired'])
        self.assertEqual(retired['device_id'], provisioned['device_id'])
        await self.assert_error('POST', f"connectors/{self.point['id']}/device", code='point_retired')
        await self.assert_error('PATCH', f"connectors/{self.point['id']}", body={'active': True}, code='point_retired')

    async def test_coupon_scope_expiry_partial_edits_and_discount(self):
        draft = next(s for s in (await self.client.request('GET', 'operator/stations'))['items'] if not s['active'])
        future = (datetime(2026, 9, 27, 15, tzinfo=timezone.utc) + timedelta(seconds=10)).isoformat()
        coupon = await self.client.request('POST', 'coupons', {'code': 'DRAFT50', 'description': 'Só rascunho',
                       'station_id': draft['id'], 'discount_percent': 50, 'valid_until': future})
        applicable = await self.client.request('GET', 'coupons', params={'station_id': self.station['id']})
        self.assertNotIn(coupon['id'], [c['id'] for c in applicable['items']])
        await self.assert_error('POST', 'charging-sessions', body={'public_code': self.point['public_code'],
            'presence_code': DEMO_PRESENCE_CODE, 'coupon_code': 'DRAFT50'}, key='wrong-scope', code='invalid_coupon')
        self.clock.advance(11)
        self.assertNotIn(coupon['id'], [c['id'] for c in (await self.client.request('GET', 'coupons'))['items']])
        edited = await self.client.request('PATCH', f"coupons/{coupon['id']}", {'description': 'Expirado editado', 'active': False})
        self.assertEqual(edited['valid_until'], future)
        await self.assert_error('PATCH', f"coupons/{coupon['id']}", body={'active': True}, code='invalid_time')
        all_owned = await self.client.request('GET', 'coupons', params={'mine': 'true'})
        self.assertIn(coupon['id'], [c['id'] for c in all_owned['items']])

    async def test_history_summary_context_pagination_and_geographic_filter(self):
        history = await self.client.request('GET', 'operator/charging-sessions', params={'limit': 1, 'offset': 1})
        self.assertEqual(history['total'], 2)
        self.assertEqual(len(history['items']), 1)
        record = history['items'][0]
        self.assertEqual(record['station_id'], self.station['id'])
        self.assertEqual(set(record['connector']), {'id', 'public_code', 'connector_type', 'power_kw', 'price_per_kwh', 'max_duration_minutes'})
        self.assertFalse({'presence_secret', 'device_key', 'owner_id'} & set(record))
        summary = await self.client.request('GET', 'me/summary')
        self.assertEqual(summary['sessions_count'], 2)
        self.assertEqual(summary['energy_wh'], '4800.000')
        nearby = await self.client.request('GET', 'stations', params={'lat': -23.5505, 'lng': -46.6333, 'radius_km': 1})
        distant = await self.client.request('GET', 'stations', params={'lat': 0, 'lng': 0, 'radius_km': 1})
        self.assertEqual(nearby['total'], 1)
        self.assertEqual(distant['total'], 0)
        await self.assert_error('GET', 'stations', params={'lat': 0}, code='coordinates_required')
        with self.assertRaises(ApiError):
            await self.client.request('GET', 'me/charging-sessions', params={'limit': 0})


if __name__ == '__main__':
    unittest.main()
