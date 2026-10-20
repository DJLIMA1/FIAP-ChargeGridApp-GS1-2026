"""Autocomplete de endereço (API própria: Photon/ViaCEP; conta demo: endereços fixos)."""
import asyncio
import unittest
from unittest.mock import AsyncMock

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.screens import onboarding, station_admin
from chargegrid_app.services import station_settings
from chargegrid_app.ui import address_autocomplete
from test_behavior import HandlerApp, descendants
from test_station_admin import demo_app, texts


def suggestion_rows(screen):
    return [c for c in descendants(screen) if isinstance(c, ft.Container) and c.data == 'address-suggestion']


def panel_of(screen):
    return next(c for c in descendants(screen) if isinstance(c, ft.Container) and c.data == 'address-suggestions')


async def type_address(field, value):
    field.value = value
    await field.on_change(None)


class AddressAutocompleteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        station_settings.reset_demo()
        self.debounce = address_autocomplete.DEBOUNCE_SECONDS
        address_autocomplete.DEBOUNCE_SECONDS = 0

    def tearDown(self):
        address_autocomplete.DEBOUNCE_SECONDS = self.debounce

    async def test_station_data_page_suggests_and_saves_address_with_coordinates(self):
        app = await demo_app()
        sid = (await app.api.request('GET', 'operator/stations'))['items'][0]['id']
        screen = await station_admin.build(app, station_id=sid, page='data')
        field = next(c for c in descendants(screen) if isinstance(c, ft.TextField)
                     and str(c.value).startswith('Av. das Nações'))
        await type_address(field, 'av paulista')
        await asyncio.sleep(0.05)
        self.assertTrue(panel_of(screen).visible)
        self.assertIn('Avenida Paulista, 1000', texts(panel_of(screen)))
        self.assertIn('demonstração', texts(panel_of(screen)))
        await suggestion_rows(screen)[0].on_click(None)
        self.assertEqual(field.value, 'Avenida Paulista, 1000, Bela Vista, São Paulo - SP')
        self.assertFalse(panel_of(screen).visible)
        station = await app.api.request('GET', f'stations/{sid}')
        self.assertEqual(station['address'], field.value)
        self.assertAlmostEqual(float(station['latitude']), -23.5648865, places=5)
        # Picked text is not looked up again; short text hides the list without a request.
        app.api.request = AsyncMock(side_effect=AssertionError('no lookup'))
        await field.on_change(None)
        await type_address(field, 'av')
        self.assertFalse(panel_of(screen).visible)

    async def test_onboarding_pick_fills_latitude_and_longitude(self):
        app = HandlerApp()
        app.api = AsyncMock()
        app.api.is_demo = False
        point = {'id': 'point', 'public_code': 'CG-9', 'connector_type': 'CCS2', 'active': False}
        station = {'id': 'station', 'name': '', 'address': '', 'latitude': '', 'longitude': '', 'connectors': [point]}
        item = {'label': 'Avenida Paulista, 1000, Bela Vista, São Paulo - SP', 'street': 'Avenida Paulista',
                'number': '1000', 'district': 'Bela Vista', 'city': 'São Paulo', 'state': 'SP',
                'postcode': '01310-100', 'latitude': -23.5648865, 'longitude': -46.651918}

        async def request(method, path, body=None, **kwargs):
            if path == 'geo/address-suggestions':
                self.assertEqual(kwargs['params'], {'q': 'paulista 1000'})
                return {'items': [item], 'available': True, 'attribution': 'Dados © colaboradores do OpenStreetMap'}
            return station
        app.api.request.side_effect = request
        screen = await onboarding.build(app, 'station', 'point', step=1)
        fields = {c.data: c for c in descendants(screen) if isinstance(c, ft.TextField)}
        await type_address(fields['Endereço'], 'paulista 1000')
        await asyncio.sleep(0.05)
        self.assertIn('OpenStreetMap', texts(panel_of(screen)))
        await suggestion_rows(screen)[0].on_click(None)
        self.assertEqual(fields['Endereço'].value, item['label'])
        self.assertEqual((fields['Latitude'].value, fields['Longitude'].value), ('-23.5648865', '-46.651918'))

    async def test_failure_and_stale_answers_never_show_a_list(self):
        app = HandlerApp()
        field = ft.TextField()
        app.api = AsyncMock()
        app.api.request.side_effect = ApiError('offline')
        panel = address_autocomplete.attach(app, field)
        await type_address(field, 'rua augusta')
        await asyncio.sleep(0.05)
        self.assertFalse(panel.visible)
        app.api.request.side_effect = None
        app.api.request.return_value = {'items': [{'label': 'Rua Augusta, Consolação, São Paulo - SP'}]}
        field.value = 'rua augusta 9'  # o usuário continuou digitando antes da resposta
        await panel.lookup('rua augusta')
        self.assertFalse(panel.visible)


if __name__ == '__main__':
    unittest.main()
