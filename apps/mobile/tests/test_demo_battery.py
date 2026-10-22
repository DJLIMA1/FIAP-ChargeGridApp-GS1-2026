"""Demo backend parity for the car battery contract (SoC, /soc, battery_full)."""

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DEMO_PRESENCE_CODE, DemoApi


class DemoBatteryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = [0.0]
        # Madrugada: a loja simulada (rebalanceamento) não reduz a potência; sem depender do relógio.
        night = datetime(2026, 10, 21, 3, 0, tzinfo=timezone(timedelta(hours=-3)))
        self.api = DemoApi(clock=lambda: self.clock[0], start_at=night)
        await self.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        stations = (await self.api.request('GET', 'stations'))['items']
        self.point = next(p for s in stations for p in s['connectors'] if p['available'])

    async def start(self, **battery):
        return await self.api.request(
            'POST', 'charging-sessions',
            {'presence_code': DEMO_PRESENCE_CODE, 'public_code': self.point['public_code'],
             'max_duration_minutes': 60, **battery},
            key=self.api.new_key())

    async def get(self, session_id):
        return await self.api.request('GET', f'charging-sessions/{session_id}')

    async def test_start_fields_and_history_shape(self):
        session = await self.start(soc_percent=42.5, battery_kwh=60, soc_source='simulated')
        self.assertEqual(session['soc_percent'], '42.50')
        self.assertEqual(session['start_soc_percent'], '42.50')
        self.assertEqual(session['battery_kwh'], '60.00')
        self.assertEqual(session['soc_source'], 'simulated')
        history = (await self.api.request('GET', 'me/charging-sessions'))['items']
        for item in history:
            self.assertIn('start_soc_percent', item)
            self.assertIn('battery_kwh', item)
            self.assertIn('soc_source', item)

    async def test_soc_without_source_defaults_to_simulated_and_validation(self):
        session = await self.start(soc_percent=30)
        self.assertEqual(session['soc_source'], 'simulated')
        await self.api.request('POST', f"charging-sessions/{session['id']}/stop", {}, key='stop')
        self.clock[0] += 5
        for bad in ({'soc_percent': 101}, {'battery_kwh': 4}, {'soc_source': 'car'}):
            with self.assertRaises(ApiError) as caught:
                await self.start(**bad)
            self.assertEqual(caught.exception.status, 422)

    async def test_simulated_soc_rises_with_energy_and_stops_battery_full(self):
        power = Decimal(self.point['power_kw'])
        session = await self.start(soc_percent=90, battery_kwh=10, soc_source='simulated')
        # 1 s to start; 0.5 kWh at `power` kW -> +5 %.
        self.clock[0] = 1 + float(Decimal('0.5') / power * 3600)
        current = await self.get(session['id'])
        self.assertEqual(current['status'], 'charging')
        self.assertAlmostEqual(float(current['soc_percent']), 95.0, delta=0.05)
        self.clock[0] = 1 + float(Decimal(2) / power * 3600)
        ended = await self.get(session['id'])
        self.assertEqual(ended['status'], 'completed')
        self.assertEqual(ended['end_reason'], 'battery_full')
        self.assertEqual(ended['soc_percent'], '100.00')
        self.assertAlmostEqual(float(ended['energy_wh']), 1000, delta=1)

    async def test_soc_endpoint_phone_flow(self):
        session = await self.start(soc_percent=80, battery_kwh=60, soc_source='phone')
        url = f"charging-sessions/{session['id']}/soc"
        self.clock[0] = 600
        self.assertEqual((await self.get(session['id']))['soc_percent'], '80.00')
        lower = await self.api.request('POST', url, {'soc_percent': 76})
        self.assertEqual((lower['soc_percent'], lower['soc_source'], lower['status']), ('76.00', 'phone', 'charging'))
        for bad in ({'soc_percent': -1}, {'soc_percent': 100.5}, {}, {'soc_percent': 50, 'extra': 1}):
            with self.assertRaises(ApiError) as caught:
                await self.api.request('POST', url, bad)
            self.assertEqual(caught.exception.status, 422)
        with self.assertRaises(ApiError) as caught:
            await self.api.request('POST', 'charging-sessions/demo-session-unknown/soc', {'soc_percent': 50})
        self.assertEqual(caught.exception.status, 404)
        full = await self.api.request('POST', url, {'soc_percent': 100})
        self.assertEqual((full['status'], full['end_reason']), ('stopping', 'battery_full'))
        with self.assertRaises(ApiError) as caught:
            await self.api.request('POST', url, {'soc_percent': 100})
        self.assertEqual((caught.exception.status, caught.exception.code), (409, 'session_not_active'))
        self.clock[0] += 2
        ended = await self.get(session['id'])
        self.assertEqual((ended['status'], ended['end_reason'], ended['soc_percent']),
                         ('completed', 'battery_full', '100.00'))

    async def test_session_without_battery_keeps_legacy_curve(self):
        session = await self.start()
        self.assertIsNone(session['soc_source'])
        self.clock[0] = 60
        self.assertIsNotNone((await self.get(session['id']))['soc_percent'])


if __name__ == '__main__':
    unittest.main()
