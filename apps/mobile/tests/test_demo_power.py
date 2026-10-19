"""Demo backend parity for station power limits (same rules as apps/api, chargegrid_core.power)."""

import unittest
from decimal import Decimal

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DEMO_PRESENCE_CODE, DemoApi


class DemoPowerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = [0.0]
        self.api = DemoApi(clock=lambda: self.clock[0])
        await self.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.station = (await self.api.request('GET', 'operator/stations'))['items'][0]
        self.ccs = next(p for p in self.station['connectors'] if p['connector_type'] == 'CCS2')

    async def patch_station(self, body):
        return await self.api.request('PATCH', f"stations/{self.station['id']}", body)

    async def patch_point(self, body, point=None):
        return await self.api.request('PATCH', f"connectors/{(point or self.ccs)['id']}", body)

    async def test_serialization_matches_api_shape(self):
        self.assertIsNone(self.station['max_power_kw'])
        self.assertFalse(self.station['power_limit_notify'])
        self.assertEqual(self.station['allocated_power_kw'], '104.000')
        self.assertEqual(self.ccs['effective_power_kw'], '60.000')
        self.assertFalse(self.ccs['power_limited'])
        self.assertIsNone(self.ccs['power_limited_by'])
        self.assertEqual(self.ccs['energy_kwh_total'], '2.400')
        public = (await self.api.request('GET', 'stations'))['items']
        other = next(s for s in public if s['owner_id'] != 'demo-user')
        self.assertNotIn('energy_kwh_total', other['connectors'][0])

    async def test_validation_messages(self):
        for body, message in (({'power_limit_kw': 61}, 'potência máxima do carregador (60 kW)'),
                              ({'power_limit_kw': 0}, 'maior que zero'),
                              ({'power_limit_kw': 1}, 'mínimo por conector')):
            with self.assertRaises(ApiError) as caught:
                await self.patch_point(body)
            self.assertEqual(caught.exception.code, 'invalid_power_limit')
            self.assertIn(message, str(caught.exception))
        with self.assertRaises(ApiError) as caught:
            await self.patch_station({'max_power_kw': 4})
        self.assertIn('pelo menos 4,2 kW para 3 conectores ativos', str(caught.exception))

    async def test_share_limits_and_clearing(self):
        body = await self.patch_station({'max_power_kw': 80, 'power_limit_notify': True})
        self.assertEqual(body['max_power_kw'], '80.000')
        self.assertTrue(body['power_shared'])
        self.assertEqual([p['effective_power_kw'] for p in body['connectors']], ['46.100', '16.900', '16.900'])
        point = await self.patch_point({'power_limit_kw': 40})
        self.assertEqual((point['power_limit_kw'], point['effective_power_kw'], point['power_kw']),
                         ('40.000', '38.000', '60.000'))
        self.assertEqual(point['power_limited_by'], 'station')
        self.assertIsNone((await self.patch_point({'power_kw': 30}))['power_limit_kw'])  # rating below limit
        self.assertIsNone((await self.patch_station({'max_power_kw': None}))['max_power_kw'])

    async def test_start_applies_effective_and_driver_limit_and_charges_slower(self):
        await self.patch_point({'power_limit_kw': 20})
        session = await self.api.request(
            'POST', 'charging-sessions',
            {'presence_code': DEMO_PRESENCE_CODE, 'public_code': self.ccs['public_code'],
             'max_duration_minutes': 60, 'max_power_kw': 50}, key=self.api.new_key())
        self.assertEqual(session['power_limit_kw'], '20.000')
        # Busy point: only the power limit may change, and it does not affect the running charge.
        with self.assertRaises(ApiError):
            await self.patch_point({'price_per_kwh': 3})
        await self.patch_point({'power_limit_kw': None})
        self.clock[0] = 1 + 180  # 3 min at 20 kW = 1 kWh
        current = await self.api.request('GET', f"charging-sessions/{session['id']}")
        self.assertEqual(Decimal(current['energy_wh']), Decimal('1000.000'))
        self.assertEqual(current['power_limit_kw'], '20.000')

    async def test_driver_limit_below_effective(self):
        session = await self.api.request(
            'POST', 'charging-sessions',
            {'presence_code': DEMO_PRESENCE_CODE, 'public_code': self.ccs['public_code'],
             'max_duration_minutes': 60, 'max_power_kw': 6.6}, key=self.api.new_key())
        self.assertEqual(session['power_limit_kw'], '6.600')


if __name__ == '__main__':
    unittest.main()
