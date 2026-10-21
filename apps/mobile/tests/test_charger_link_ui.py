"""Todo ponto é um carregador GoodWe HCA G2: endereço (sempre preenchido), status e conta demo."""
import unittest

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_CLAIM_TOKEN, DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import operator, station_admin
from test_behavior import HandlerApp, click, descendants
from test_seller_flow_fixes import fields, station_fixture, texts

ONLINE = {'model': 'goodwe_hca_g2', 'transport': 'modbus_tcp', 'address': 1, 'host': 'cg-hca-1.local',
          'label': 'GoodWe HCA G2', 'simulated': True, 'link': 'online',
          'reported': {'model': 'goodwe_hca_g2', 'transport': 'modbus_tcp', 'address': 1, 'link': 'online'}}
WAITING = 'aguardando carregador (simulação da tela)'
EMPTY = 'Endereço do carregador não pode ficar vazio: informe um número de 1 a 247'


def buttons(screen):
    return [item.content.value for item in descendants(screen)
            if isinstance(item, ft.Container) and isinstance(getattr(item, 'content', None), ft.Text)]


def point(**extra):
    return {**station_fixture()['connectors'][0], **extra}


class ChargerFieldTests(unittest.IsolatedAsyncioTestCase):
    async def form(self, app, connector, *responses):
        app.api.request.side_effect = [{'device_id': 'device', 'online': True}, {'status': 'not_requested'},
                                       *responses]
        return await operator.connector_form(app, 'station', connector)

    async def test_connector_screen_shows_the_current_address_and_one_status_line(self):
        app = HandlerApp()
        screen = await self.form(app, point(charger_address=2, charger_link={**ONLINE, 'address': 2}))
        field = fields(screen)[operator.CHARGER_FIELD]
        self.assertEqual(field.value, '2')
        self.assertNotIn('sugerido', field.hint_text or '')
        lines = [item.value for item in descendants(screen) if isinstance(item, ft.Text)
                 and str(item.value).startswith('Carregador GoodWe ·')]
        self.assertEqual(lines, ['Carregador GoodWe · endereço 2 · online'])
        self.assertNotIn('Carregador externo', texts(screen))

    async def test_no_remove_button(self):
        app = HandlerApp()
        screen = await self.form(app, point(charger_address=1, charger_link=ONLINE))
        self.assertNotIn('Remover', buttons(screen))
        self.assertNotIn('Remover carregador', texts(screen))
        self.assertIn('Salvar', buttons(screen))

    async def test_editing_the_address_saves_an_int_with_patch(self):
        app = HandlerApp()
        connector = point(charger_address=1, charger_link=ONLINE)
        waiting = {**ONLINE, 'address': 4, 'host': 'cg-hca-4.local', 'link': 'pending', 'reported': None}
        screen = await self.form(app, connector, {**connector, 'charger_address': 4, 'charger_link': waiting})
        fields(screen)[operator.CHARGER_FIELD].value = ' 4 '
        await click(screen, 'Salvar')(None)
        app.api.request.assert_awaited_with('PATCH', 'connectors/point', {'charger_address': 4})
        self.assertIn(f'Carregador GoodWe · endereço 4 · {WAITING}', texts(screen))
        self.assertEqual((connector['charger_address'], fields(screen)[operator.CHARGER_FIELD].value), (4, '4'))

    async def test_empty_address_shows_the_core_error_inline_and_sends_nothing(self):
        app = HandlerApp()
        screen = await self.form(app, point(charger_address=1, charger_link=ONLINE))
        field = fields(screen)[operator.CHARGER_FIELD]
        field.value = '  '
        with self.assertRaises(ApiError):
            await click(screen, 'Salvar')(None)
        self.assertEqual(field.error_text, EMPTY)
        for value, message in (('0', 'entre 1 e 247'), ('248', 'entre 1 e 247'), ('abc', 'número inteiro')):
            field.value = value
            with self.assertRaises(ApiError):
                await click(screen, 'Salvar')(None)
            self.assertIn(message, field.error_text)
        self.assertEqual(app.api.request.await_count, 2)  # só o dispositivo e o estado da restauração

    async def test_taken_address_from_the_api_is_shown_inline(self):
        app = HandlerApp()
        message = 'O carregador 2 já está ligado ao ponto DEMO-9 deste posto. Escolha outro endereço.'
        screen = await self.form(app, point(charger_address=1, charger_link=ONLINE),
                                 ApiError(message, 409, 'charger_address_taken'))
        field = fields(screen)[operator.CHARGER_FIELD]
        field.value = '2'
        with self.assertRaises(ApiError):
            await click(screen, 'Salvar')(None)
        self.assertEqual(field.error_text, message)

    def test_status_text(self):
        self.assertEqual(operator.charger_status(point(charger_address=1, charger_link=ONLINE)),
                         'Carregador GoodWe · endereço 1 · online')
        self.assertEqual(operator.charger_status(point(charger_address=2, online=False)),
                         f'Carregador GoodWe · endereço 2 · {WAITING}')
        self.assertEqual(operator.charger_status(point()), '')  # payload de motorista

    def test_connectors_list_shows_the_charger_line(self):
        app = HandlerApp()
        station = station_fixture()
        station['connectors'][0].update(charger_address=1, charger_link={**ONLINE, 'link': 'offline'})
        screen = station_admin._connectors_page(app, station)
        self.assertIn(f'Carregador GoodWe · endereço 1 · {WAITING}', texts(screen))
        station['connectors'][0]['charger_link'] = ONLINE
        screen = station_admin._connectors_page(app, station)
        self.assertIn('Carregador GoodWe · endereço 1 · online', texts(screen))


class DemoChargerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = DemoApi()
        await self.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        stations = (await self.api.request('GET', 'operator/stations'))['items']
        self.station = stations[0]
        self.points = self.station['connectors']

    async def test_every_owner_point_has_addresses_1_to_n_in_creation_order(self):
        self.assertGreater(len(self.points), 1)
        ordered = sorted(self.points, key=lambda p: int(p['id'].rsplit('-', 1)[-1]))
        self.assertEqual([p['charger_address'] for p in ordered], list(range(1, len(ordered) + 1)))
        for item in self.points:
            block = item['charger_link']
            self.assertEqual((block['address'], block['host']),
                             (item['charger_address'], f"cg-hca-{item['charger_address']}.local"))
            # Demo sem carregador GoodWe de verdade: a tela carrega com a simulação interna.
            self.assertEqual(block['link'], 'offline')
            self.assertEqual(operator.charger_status(item),
                             f"Carregador GoodWe · endereço {item['charger_address']} · {WAITING}")

    async def test_new_connector_gets_the_next_free_address(self):
        last = max(self.points, key=lambda p: p['charger_address'])
        first = min(self.points, key=lambda p: p['charger_address'])
        await self.api.request('PATCH', f"connectors/{first['id']}", {'charger_address': 200})  # libera o 1
        claimed = await self.api.request('POST', 'ownership/claim',
                                         {'token': DEMO_CLAIM_TOKEN, 'station_id': self.station['id']})
        station = await self.api.request('GET', f"stations/{self.station['id']}")
        new = next(p for p in station['connectors'] if p['id'] == claimed['connector_id'])
        self.assertEqual(new['charger_address'], 1)
        self.assertLess(new['charger_address'], last['charger_address'])
        # Posto novo (criado pelo claim): o primeiro ponto nasce com o endereço 1.
        other = await self.api.request('POST', 'ownership/claim', {'token': self.api.new_claim_token()})
        fresh = await self.api.request('GET', f"stations/{other['station_id']}")
        self.assertEqual([p['charger_address'] for p in fresh['connectors']], [1])

    async def test_demo_patch_validates_and_keeps_address_unique_per_station(self):
        target, other = self.points[0], self.points[1]
        for bad in (None, 0, 248, '1', True, 1.5):
            with self.assertRaises(ApiError) as caught:
                await self.api.request('PATCH', f"connectors/{target['id']}", {'charger_address': bad})
            self.assertEqual((caught.exception.status, caught.exception.code), (422, 'invalid_charger_address'))
        with self.assertRaises(ApiError) as caught:
            await self.api.request('PATCH', f"connectors/{target['id']}", {'charger_address': None})
        self.assertEqual(str(caught.exception), EMPTY)
        with self.assertRaises(ApiError) as caught:
            await self.api.request('PATCH', f"connectors/{target['id']}", {'charger_address': other['charger_address']})
        self.assertEqual((caught.exception.status, caught.exception.code), (409, 'charger_address_taken'))
        self.assertEqual(str(caught.exception),
                         f"O carregador {other['charger_address']} já está ligado ao ponto {other['public_code']} "
                         'deste posto. Escolha outro endereço.')
        same = await self.api.request('PATCH', f"connectors/{target['id']}",
                                      {'charger_address': target['charger_address']})
        self.assertEqual(same['charger_address'], target['charger_address'])
        saved = await self.api.request('PATCH', f"connectors/{target['id']}", {'charger_address': 9})
        self.assertEqual((saved['charger_address'], saved['charger_link']['address']), (9, 9))

    async def test_same_address_is_a_no_op_even_while_busy(self):
        target = self.points[0]
        self.api._busy = lambda point_id: True
        same = await self.api.request('PATCH', f"connectors/{target['id']}",
                                      {'charger_address': target['charger_address']})
        self.assertEqual(same['charger_address'], target['charger_address'])
        with self.assertRaises(ApiError) as caught:
            await self.api.request('PATCH', f"connectors/{target['id']}", {'charger_address': 50})
        self.assertEqual(caught.exception.code, 'point_busy')

    async def test_driver_payloads_do_not_carry_charger_fields(self):
        listing = await self.api.request('GET', 'stations')
        others = [s for s in listing['items'] if s['id'] != self.station['id']]
        self.assertTrue(others)
        for station in others:
            for item in station['connectors']:
                self.assertNotIn('charger_address', item)
                self.assertNotIn('charger_link', item)

    async def test_demo_connector_screen_edits_through_the_demo_api(self):
        app = HandlerApp()
        app.api = self.api
        target = self.points[0]
        screen = await operator.connector_form(app, self.station['id'], dict(target))
        field = fields(screen)[operator.CHARGER_FIELD]
        self.assertEqual(field.value, str(target['charger_address']))
        field.value = '7'
        await click(screen, 'Salvar')(None)
        self.assertIn(f'Carregador GoodWe · endereço 7 · {WAITING}', texts(screen))
        station = await self.api.request('GET', f"stations/{self.station['id']}")
        self.assertEqual(next(p for p in station['connectors'] if p['id'] == target['id'])['charger_address'], 7)
        field.value = ''
        with self.assertRaises(ApiError):
            await click(screen, 'Salvar')(None)
        self.assertEqual(field.error_text, EMPTY)
