"""Carregador GoodWe HCA G2 (simulado) ligado ao ponto: campo de endereço, status e conta demo."""
import unittest

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import operator, station_admin
from test_behavior import HandlerApp, click, descendants
from test_seller_flow_fixes import fields, station_fixture, texts

LINKED = {'model': 'goodwe_hca_g2', 'transport': 'modbus_tcp', 'address': 1, 'host': 'cg-hca-1.local',
          'label': 'GoodWe HCA G2', 'simulated': True, 'link': 'online',
          'reported': {'model': 'goodwe_hca_g2', 'transport': 'modbus_tcp', 'address': 1, 'link': 'online'}}


def remove_button(screen):
    return next(item for item in descendants(screen) if isinstance(getattr(item, 'content', None), ft.Text)
                and item.content.value == 'Remover')


def point(**extra):
    return {**station_fixture()['connectors'][0], **extra}


class ChargerFieldTests(unittest.IsolatedAsyncioTestCase):
    async def form(self, app, connector, *responses):
        app.api.request.side_effect = [{'device_id': 'device', 'online': True}, {'status': 'not_requested'},
                                       *responses]
        return await operator.connector_form(app, 'station', connector)

    async def test_unlinked_point_suggests_address_1_and_links_with_patch(self):
        app = HandlerApp()
        connector = point(charger_address=None, charger_link=None)
        screen = await self.form(app, connector, {**connector, 'charger_address': 1,
                                                  'charger_link': {**LINKED, 'link': 'pending', 'reported': None}})
        field = fields(screen)[operator.CHARGER_FIELD]
        self.assertEqual(field.value, '1')
        self.assertIn(operator.CHARGER_NONE, texts(screen))
        self.assertFalse(remove_button(screen).visible)  # nada a remover antes de ligar
        await click(screen, 'Salvar')(None)
        app.api.request.assert_awaited_with('PATCH', 'connectors/point', {'charger_address': 1})
        self.assertIn('Carregador 1 · GoodWe HCA G2 (simulado) · aguardando a tela', texts(screen))
        self.assertEqual(app.notices[-1], 'Carregador 1 ligado a este ponto.')

    async def test_linked_point_shows_status_and_can_remove(self):
        app = HandlerApp()
        connector = point(charger_address=1, charger_link=LINKED)
        screen = await self.form(app, connector, {**connector, 'charger_address': None, 'charger_link': None})
        self.assertIn('Carregador 1 · GoodWe HCA G2 (simulado) · online', texts(screen))
        self.assertIn('Salvar endereço', texts(screen))
        self.assertTrue(remove_button(screen).visible)
        await click(screen, 'Remover')(None)
        app.api.request.assert_awaited_with('PATCH', 'connectors/point', {'charger_address': None})
        self.assertIn(operator.CHARGER_NONE, texts(screen))
        self.assertIsNone(connector['charger_address'])

    async def test_invalid_address_is_refused_before_the_api(self):
        app = HandlerApp()
        screen = await self.form(app, point())
        field = fields(screen)[operator.CHARGER_FIELD]
        for value in ('0', '248', 'abc', ''):
            field.value = value
            with self.assertRaises(ApiError):
                await click(screen, 'Salvar')(None)
            self.assertEqual(field.error_text, 'Informe um endereço de 1 a 247.')
        self.assertEqual(app.api.request.await_count, 2)  # só o dispositivo e o estado da restauração

    def test_status_without_link_block_uses_the_address(self):
        self.assertEqual(operator.charger_status(point(charger_address=2, online=False)),
                         'Carregador 2 · GoodWe HCA G2 (simulado) · offline')
        self.assertEqual(operator.charger_status(point()), '')

    def test_connectors_list_shows_the_charger_line(self):
        app = HandlerApp()
        station = station_fixture()
        station['connectors'][0].update(charger_address=1, charger_link={**LINKED, 'link': 'offline'})
        screen = station_admin._connectors_page(app, station)
        self.assertIn('Carregador 1 · GoodWe HCA G2 (simulado) · offline', texts(screen))


class DemoChargerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = DemoApi()
        await self.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        stations = (await self.api.request('GET', 'operator/stations'))['items']
        self.station = stations[0]
        self.points = self.station['connectors']

    async def test_demo_owner_has_a_linked_simulated_charger(self):
        linked = [p for p in self.points if p['charger_address'] is not None]
        self.assertEqual(len(linked), 1)
        self.assertEqual(linked[0]['charger_address'], 1)
        self.assertEqual(linked[0]['charger_link']['host'], 'cg-hca-1.local')
        self.assertEqual(operator.charger_status(linked[0]), 'Carregador 1 · GoodWe HCA G2 (simulado) · online')

    async def test_demo_patch_validates_and_keeps_address_unique_per_station(self):
        free = next(p for p in self.points if p['charger_address'] is None)
        for bad in (0, 248, '1', True, 1.5):
            with self.assertRaises(ApiError) as caught:
                await self.api.request('PATCH', f"connectors/{free['id']}", {'charger_address': bad})
            self.assertEqual(caught.exception.status, 422)
        with self.assertRaises(ApiError) as caught:
            await self.api.request('PATCH', f"connectors/{free['id']}", {'charger_address': 1})
        self.assertEqual((caught.exception.status, caught.exception.code), (409, 'charger_address_taken'))
        self.assertIn('já está ligado ao ponto', str(caught.exception))
        saved = await self.api.request('PATCH', f"connectors/{free['id']}", {'charger_address': 2})
        self.assertEqual((saved['charger_address'], saved['charger_link']['address']), (2, 2))
        removed = await self.api.request('PATCH', f"connectors/{free['id']}", {'charger_address': None})
        self.assertEqual((removed['charger_address'], removed['charger_link']), (None, None))

    async def test_driver_payloads_do_not_carry_charger_fields(self):
        listing = await self.api.request('GET', 'stations')
        others = [s for s in listing['items'] if s['id'] != self.station['id']]
        self.assertTrue(others)
        for station in others:
            for item in station['connectors']:
                self.assertNotIn('charger_address', item)
                self.assertNotIn('charger_link', item)

    async def test_demo_connector_screen_links_through_the_demo_api(self):
        app = HandlerApp()
        app.api = self.api
        free = next(p for p in self.points if p['charger_address'] is None)
        screen = await operator.connector_form(app, self.station['id'], dict(free))
        fields(screen)[operator.CHARGER_FIELD].value = '3'
        await click(screen, 'Salvar')(None)
        self.assertIn('Carregador 3 · GoodWe HCA G2 (simulado) · online', texts(screen))
        station = await self.api.request('GET', f"stations/{self.station['id']}")
        self.assertEqual(next(p for p in station['connectors'] if p['id'] == free['id'])['charger_address'], 3)
