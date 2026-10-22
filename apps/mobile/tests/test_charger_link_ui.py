"""Estação (tela) × Carregadores: cada ponto é um carregador GoodWe HCA G2 (simulado).

Vendedor: lista "Carregadores" (status da tela separado do de cada carregador), Adicionar carregador,
seção do carregador (endereço, link, última leitura, potência lida) e o vínculo com a tela.
Motorista: "Carregador offline" (nunca disponível), 409 charger_offline com alternativas e o rótulo
de fim de sessão. Demo: carregadores simulados online, 2 carregadores na mesma tela.
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import flet as ft
import httpx

from chargegrid_app.api_client import ApiClient, ApiError
from chargegrid_app.demo import (
    DEMO_CLAIM_TOKEN,
    DEMO_EMAIL,
    DEMO_PASSWORD,
    DEMO_PRESENCE_CODE,
    DemoApi,
)
from chargegrid_app.screens import chargers, charging, operator, station_admin
from chargegrid_app.services import booking as rules
from chargegrid_app.ui import theme
from chargegrid_app.ui.availability import point_status, station_map_record
from chargegrid_core import receipt
from chargegrid_core.chargers import link as charger_link
from test_behavior import HandlerApp, click, descendants
from test_seller_flow_fixes import central_maintenance, fields, station_fixture, texts

ONLINE = {'model': 'goodwe_hca_g2', 'transport': 'modbus_tcp', 'address': 1, 'host': 'cg-hca-1.local',
          'label': 'GoodWe HCA G2', 'simulated': True, 'link': 'online',
          'last_online_at': '2026-10-21T12:00:00+00:00', 'measured_power_w': 7200,
          'reported': {'model': 'goodwe_hca_g2', 'transport': 'modbus_tcp', 'address': 1, 'link': 'online'}}
SCREEN = {'device_id': 'device', 'connector_id': 'point', 'public_code': 'CG-POINT', 'online': True,
          'last_seen': '2026-10-21T12:00:00+00:00', 'firmware_version': '0.4.0', 'role': 'screen',
          'multi_charger': True}
EMPTY = 'Endereço do carregador não pode ficar vazio: informe um número de 1 a 247'
OFFLINE = charger_link.CHARGER_OFFLINE_MESSAGE


def buttons(screen):
    return [item.content.value for item in descendants(screen)
            if isinstance(item, ft.Container) and isinstance(getattr(item, 'content', None), ft.Text)]


def visible_buttons(screen):
    """Botões de texto realmente visíveis (o controle e todos os ancestrais visíveis)."""
    found = []

    def walk(item, shown):
        shown = shown and getattr(item, 'visible', True) is not False
        if shown and isinstance(item, ft.Container) and isinstance(getattr(item, 'content', None), ft.Text):
            found.append(item.content.value)
        content = getattr(item, 'content', None)
        if content is not None and not isinstance(content, str):
            walk(content, shown)
        for child in getattr(item, 'controls', []) or []:
            walk(child, shown)
    walk(screen, True)
    return found


def point(**extra):
    return {**station_fixture()['connectors'][0], **extra}


class ChargerFieldTests(unittest.IsolatedAsyncioTestCase):
    async def form(self, app, connector, *responses):
        app.api.request.side_effect = list(responses)
        return await operator.connector_form(app, 'station', connector)

    async def test_charger_card_shows_address_link_last_reading_and_measured_power(self):
        app = HandlerApp()
        screen = await self.form(app, point(active=True, charger_address=2, charger_link={**ONLINE, 'address': 2},
                                            screen=SCREEN, power_kw='22', power_limit_kw='11'))
        field = fields(screen)[operator.CHARGER_FIELD]
        self.assertEqual(field.value, '2')
        copy = texts(screen)
        for expected in ('Editar carregador', 'Carregador 2', 'GoodWe HCA G2 · Tipo 2 · 22 kW (limite 11 kW)',
                         'publicado', 'Última leitura', 'Potência lida', '7,2 kW', 'CG_ADDR'):
            self.assertIn(expected, copy)
        for removed in ('Carregador externo', 'simulação da tela', 'Conexão do equipamento', 'Voltar aos conectores',
                        'Sem resposta do carregador', 'Voltar aos carregadores'):
            self.assertNotIn(removed, copy)
        card = next(item for item in descendants(screen) if getattr(item, 'data', None) == 'charger-card')
        self.assertIn('Online', texts(card))

    async def test_each_identifier_is_shown_once_and_save_is_the_last_action(self):
        app = HandlerApp()
        screen = await self.form(app, point(active=True, charger_address=2, charger_link={**ONLINE, 'address': 2},
                                            screen={**SCREEN, 'role': 'charger'}, station_name='Posto Central'))
        copy = texts(screen)
        # Código público e endereço: só nos campos de Identificação; nome e status: só no cartão do topo.
        self.assertEqual(fields(screen)['Código público'].value, 'CG-POINT')
        self.assertNotIn('CG-POINT', copy)
        self.assertEqual(copy.count('Carregador 2'), 1)
        self.assertEqual(copy.count('Online'), 1)
        self.assertEqual(copy.count('Posto Central'), 1)
        self.assertEqual(buttons(screen)[-1], 'Salvar alterações')
        self.assertNotIn('Salvar', buttons(screen))  # o endereço é salvo junto, sem um segundo botão

    async def test_screen_own_charger_has_no_remove_action(self):
        app = HandlerApp()
        for connector in (point(charger_address=1, charger_link=ONLINE, screen=SCREEN),
                          point(charger_address=1, charger_link=ONLINE)):
            screen = await self.form(app, connector)
            self.assertNotIn(chargers.REMOVE_LABEL, buttons(screen))
            self.assertFalse([item for item in descendants(screen) if getattr(item, 'data', None) == 'remove-charger'])

    async def test_editing_the_address_saves_an_int_with_the_form(self):
        app = HandlerApp()
        connector = point(active=True, charger_address=1, charger_link=ONLINE)
        screen = await self.form(app, connector, {**connector, 'charger_address': 4})
        fields(screen)[operator.CHARGER_FIELD].value = ' 4 '
        await click(screen, 'Salvar alterações')(None)
        method, path, body = app.api.request.await_args.args
        self.assertEqual((method, path, body['charger_address']), ('PATCH', 'connectors/point', 4))
        self.assertEqual(body['public_code'], 'CG-POINT')
        self.assertIn('CG_ADDR = 4', app.notices[-1])
        app.go.assert_awaited_once_with('station_admin', station_id='station', page='connectors')

    async def test_unchanged_address_is_not_resent(self):
        app = HandlerApp()
        connector = point(active=True, charger_address=1, charger_link=ONLINE)
        screen = await self.form(app, connector, connector)
        await click(screen, 'Salvar alterações')(None)
        self.assertNotIn('charger_address', app.api.request.await_args.args[2])
        self.assertEqual(app.notices, [])

    async def test_empty_address_shows_the_core_error_inline_and_sends_nothing(self):
        app = HandlerApp()
        screen = await self.form(app, point(charger_address=1, charger_link=ONLINE))
        field = fields(screen)[operator.CHARGER_FIELD]
        field.value = '  '
        with self.assertRaises(ApiError):
            await click(screen, 'Salvar alterações')(None)
        self.assertEqual(field.error_text, EMPTY)
        for value, message in (('0', 'entre 1 e 247'), ('248', 'entre 1 e 247'), ('abc', 'número inteiro')):
            field.value = value
            with self.assertRaises(ApiError):
                await click(screen, 'Salvar alterações')(None)
            self.assertIn(message, field.error_text)
        app.api.request.assert_not_awaited()

    async def test_taken_address_from_the_api_is_shown_inline(self):
        app = HandlerApp()
        message = 'O carregador 2 já está ligado ao ponto CG-9 deste posto. Escolha outro endereço.'
        screen = await self.form(app, point(charger_address=1, charger_link=ONLINE),
                                 ApiError(message, 409, 'charger_address_taken'))
        field = fields(screen)[operator.CHARGER_FIELD]
        field.value = '2'
        with self.assertRaises(ApiError):
            await click(screen, 'Salvar alterações')(None)
        self.assertEqual(field.error_text, message)
        app.go.assert_not_awaited()

    async def test_additional_charger_links_to_its_screen_without_credential_actions(self):
        app = HandlerApp()
        extra = point(id='extra', public_code='CG-EXTRA', charger_address=2, charger_link={**ONLINE, 'address': 2},
                      screen={**SCREEN, 'role': 'charger'})
        screen = await self.form(app, extra)
        self.assertNotIn('Central da estação', texts(screen))
        self.assertNotIn('Abrir a central', texts(screen))
        for action in ('Rotacionar', 'Revogar', 'Restaurar', 'Provisionar'):
            self.assertNotIn(action, visible_buttons(screen))

    async def test_screen_point_keeps_credential_actions_in_the_screen_card(self):
        app = HandlerApp()
        app.api.request.side_effect = [{'device_id':'device','online':True}, {'status':'not_requested'}]
        screen = await central_maintenance(app, point(charger_address=1, charger_link=ONLINE, screen=SCREEN))
        shown = visible_buttons(screen)
        for action in ('Rotacionar', 'Revogar', 'Restaurar'):
            self.assertIn(action, shown)
        self.assertNotIn('Provisionar', shown)

    def test_status_text(self):
        self.assertEqual(operator.charger_status(point(charger_address=1, charger_link=ONLINE)),
                         'Carregador 1 · GoodWe HCA G2 · online')
        self.assertEqual(operator.charger_status(point(charger_address=2, online=False)),
                         'Carregador 2 · GoodWe HCA G2 · offline')
        self.assertEqual(operator.charger_status(point()), '')  # payload de motorista

    def test_charger_pill_follows_the_link(self):
        for link, label in (('online', 'Online'), ('offline', 'Offline'), ('pending', 'Aguardando a central')):
            connector = point(active=True, charger_address=1, charger_link={**ONLINE, 'link': link})
            self.assertEqual(operator._point_status(connector)[0], label)
        self.assertEqual(operator._point_status(point(active=False, charger_link=ONLINE))[0], 'Desativado')


class RemoveChargerTests(unittest.IsolatedAsyncioTestCase):
    """``Remover carregador``: só carregador adicional, com confirmação, ``DELETE connectors/{id}`` e erros da API."""

    def extra(self, **changes):
        return point(**{'id': 'extra', 'public_code': 'CG-EXTRA', 'active': True, 'charger_address': 2,
                        'charger_link': {**ONLINE, 'address': 2}, 'screen': {**SCREEN, 'role': 'charger'}, **changes})

    async def open(self, app, connector):
        app.page.show_dialog, app.page.pop_dialog = Mock(), Mock()
        screen = await operator.connector_form(app, 'station', connector)
        await click(screen, chargers.REMOVE_LABEL)(None)
        return screen, app.page.show_dialog.call_args.args[0]

    def test_only_additional_chargers_are_removable(self):
        self.assertTrue(chargers.removable(self.extra()))
        self.assertFalse(chargers.removable(point(screen=SCREEN)))  # o da própria central
        self.assertFalse(chargers.removable(point()))  # payload sem central
        self.assertFalse(chargers.removable(self.extra(retired=True)))
        legacy = self.extra(screen={k: v for k, v in SCREEN.items() if k != 'role'})
        self.assertTrue(chargers.removable(legacy))  # sem ``role``: compara o ponto da central
        self.assertFalse(chargers.removable(point(screen={k: v for k, v in SCREEN.items() if k != 'role'})))

    async def test_confirm_dialog_is_destructive_and_cancel_sends_nothing(self):
        app = HandlerApp()
        screen, dialog = await self.open(app, self.extra())
        self.assertEqual(dialog.title.value, 'Remover carregador 2?')
        self.assertEqual(dialog.content.value, 'Ele sai da estação e o endereço fica livre.')
        cancel, remove = dialog.actions
        self.assertEqual((cancel.content, remove.content), ('Cancelar', 'Remover'))
        self.assertEqual(remove.style.color, theme.RED)
        cancel.on_click(None)
        app.api.request.assert_not_awaited()
        self.assertEqual(buttons(screen)[-1], 'Salvar alterações')  # remover nunca é a última ação

    async def test_confirm_deletes_and_returns_to_the_refreshed_list(self):
        app = HandlerApp()
        app.api.request.return_value = None  # 204
        _, dialog = await self.open(app, self.extra())
        await dialog.actions[1].on_click(None)
        app.api.request.assert_awaited_once_with('DELETE', 'connectors/extra')
        self.assertIn('Carregador 2 removido', app.notices[-1])
        app.go.assert_awaited_once_with('station_admin', station_id='station', page='connectors')

    async def test_api_conflicts_are_explained_and_keep_the_form(self):
        for code, expected in (('screen_charger', 'carregador da própria central'),
                               ('point_busy', 'recarga ou reserva em andamento'),
                               ('not_found', 'Carregador não encontrado')):
            app = HandlerApp()
            app.api.request.side_effect = ApiError('Carregador não encontrado', 409 if code != 'not_found' else 404, code)
            _, dialog = await self.open(app, self.extra())
            with self.assertRaises(ApiError) as caught:
                await dialog.actions[1].on_click(None)
            self.assertIn(expected, str(caught.exception))
            app.go.assert_not_awaited()

    async def test_client_sends_delete_and_reads_the_error_shape(self):
        seen = []

        def handler(request):
            seen.append((request.method, request.url.path))
            if request.url.path.endswith('/screen'):
                return httpx.Response(409, json={'error': {'code': 'screen_charger', 'message': 'x'}})
            return httpx.Response(204)
        client = ApiClient('https://api.example.test/v1', httpx.MockTransport(handler))
        self.assertIsNone(await client.request('DELETE', 'connectors/extra', auth=False))
        with self.assertRaises(ApiError) as caught:
            await client.request('DELETE', 'connectors/screen', auth=False)
        self.assertEqual((caught.exception.status, caught.exception.code), (409, 'screen_charger'))
        self.assertEqual(seen, [('DELETE', '/v1/connectors/extra'), ('DELETE', '/v1/connectors/screen')])
        await client.close()


class ChargersPageTests(unittest.IsolatedAsyncioTestCase):
    def station(self, **extra):
        station = station_fixture()
        station['connectors'][0].update(active=True, charger_address=1, charger_link=ONLINE, screen=SCREEN)
        station.update({'screen_online': True, 'screens': [{**SCREEN, 'charger_ids': ['point']}], **extra})
        return station

    def test_list_is_named_carregadores_and_separates_screen_and_charger_status(self):
        app = HandlerApp()
        station = self.station()
        station['connectors'][0]['charger_link'] = {**ONLINE, 'link': 'offline'}
        screen = station_admin._connectors_page(app, station)
        copy = texts(screen)
        for expected in ('Carregadores', 'Carregador 1 · Tipo 2 · 7,4 kW',
                         chargers.ADD_LABEL, chargers.ADD_HINT):
            self.assertIn(expected, copy)
        self.assertNotIn('Conectores', copy)
        pills = [item.content.value for item in descendants(screen) if isinstance(item, ft.Container)
                 and isinstance(item.content, ft.Text) and item.content.value in ('Online', 'Offline')]
        self.assertEqual(pills, ['Offline'])  # só o carregador; central fica em Dados
        self.assertNotIn('Central da estação', copy)

    async def test_add_charger_posts_to_the_screen_point_and_shows_the_new_address(self):
        app = HandlerApp()
        station = self.station()
        created = point(id='new', public_code='CG-NEW', active=False, charger_address=2,
                        charger_link={**ONLINE, 'address': 2, 'link': 'pending'}, screen={**SCREEN, 'role': 'charger'})
        app.api.request.return_value = created
        screen = station_admin._connectors_page(app, station)
        await click(screen, chargers.ADD_LABEL)(None)
        app.api.request.assert_awaited_once_with('POST', 'connectors/point/chargers')
        copy = texts(screen)
        self.assertIn('Carregador 2 criado (CG-NEW), inativo. Configure CG_ADDR = 2', copy)
        self.assertIn('CG-NEW', copy)
        self.assertIn('Carregador 2 · Tipo 2 · 7,4 kW · aguardando a central', copy)

    async def test_add_charger_conflicts_are_explained(self):
        for code, expected in (('screen_required', 'ainda não tem central vinculada'),
                               ('charger_address_full', '1 a 247')):
            app = HandlerApp()
            app.api.request.side_effect = ApiError('x', 409, code)
            screen = station_admin._connectors_page(app, self.station())
            with self.assertRaises(ApiError) as caught:
                await click(screen, chargers.ADD_LABEL)(None)
            self.assertIn(expected, str(caught.exception))
            result = next(item for item in descendants(screen) if getattr(item, 'data', None) == 'charger-added')
            self.assertTrue(result.visible)
            self.assertIn(expected, result.value)

    def test_screen_connector_prefers_the_screen_role(self):
        station = self.station(screens=None)
        station['connectors'].insert(0, point(id='extra', screen={**SCREEN, 'role': 'charger', 'connector_id': 'point'}))
        self.assertEqual(chargers.screen_connector_id(station), 'point')
        self.assertIsNone(chargers.screen_connector_id({'connectors': []}))

    def test_station_menu_shows_screen_status_and_carregadores(self):
        app = HandlerApp()
        app.back = lambda event=None: None
        screen = station_admin._main_page(app, self.station(), 'CG-001')
        self.assertIn('Central online', texts(screen))
        self.assertIn('Carregadores', texts(screen))
        self.assertIn('1 carregador · 1 publicado · 1 online', texts(screen))
        offline = station_admin._main_page(app, self.station(screen_online=False, screens=[]), 'CG-001')
        self.assertIn('Central offline', texts(offline))
        legacy = station_fixture()  # API sem screen_online: sem a etiqueta da tela
        self.assertNotIn('Central online', texts(station_admin._main_page(app, legacy, 'CG-001')))


class DriverChargerOfflineTests(unittest.TestCase):
    def offline_point(self, **extra):
        return {'id': 'p', 'public_code': 'CG-1', 'connector_type': 'CCS2', 'power_kw': '60', 'active': True,
                'online': False, 'screen_online': True, 'unavailable_reason': 'charger_offline', 'available': False,
                'availability_status': 'offline', 'price_per_kwh': '1.89', **extra}

    def test_point_status_says_carregador_offline_and_never_available(self):
        self.assertEqual(point_status(self.offline_point())[0], 'Carregador offline')
        # Mesmo um payload inconsistente nunca aparece como disponível.
        self.assertEqual(point_status(self.offline_point(availability_status='available', available=True))[0],
                         'Carregador offline')
        self.assertEqual(point_status(self.offline_point(unavailable_reason='screen_offline'))[0], 'Offline')

    def test_groups_and_map_explain_the_offline_charger(self):
        free = {**self.offline_point(id='q', public_code='CG-2'), 'online': True, 'unavailable_reason': None,
                'available': True, 'availability_status': 'available'}
        station = {'id': 's', 'active': True, 'connectors': [self.offline_point(), free]}
        group = rules.group_connectors(station)[0]
        self.assertEqual(rules.group_subtitle(group), '1 de 2 conectores livre · 1 carregador offline')
        alone = rules.group_connectors({'id': 's', 'active': True, 'connectors': [self.offline_point()]})[0]
        self.assertEqual(rules.group_subtitle(alone), 'Carregador offline · use outro ponto desta estação')
        record = station_map_record({'connectors': [self.offline_point()]}, lambda station, point: False)
        self.assertEqual(record['status'], 'Carregador offline')

    def test_end_reason_label_comes_from_the_core(self):
        self.assertEqual(charging.END_REASONS['charger_offline'], receipt.END_REASONS['charger_offline'])
        self.assertEqual(charging.END_REASONS['charger_offline'], OFFLINE)


class ApiChargerOfflineTests(unittest.IsolatedAsyncioTestCase):
    async def test_409_charger_offline_suggests_the_free_points(self):
        body = {'error': {'code': 'point_unavailable', 'reason': 'charger_offline', 'message': OFFLINE,
                          'alternatives': [{'id': 'a', 'public_code': 'CG-2'}, {'id': 'b', 'public_code': 'CG-3'}]}}
        client = ApiClient('https://api.example.test/v1', httpx.MockTransport(lambda request: httpx.Response(409, json=body)))
        with self.assertRaises(ApiError) as caught:
            await client.request('POST', 'charging-sessions', {'public_code': 'CG-1'}, auth=False)
        error = caught.exception
        self.assertTrue(error.charger_offline)
        self.assertEqual(str(error), f'{OFFLINE} (livres: CG-2, CG-3)')
        self.assertEqual([item['public_code'] for item in error.alternatives], ['CG-2', 'CG-3'])
        await client.close()

    async def test_without_alternatives_only_the_message(self):
        body = {'error': {'code': 'point_unavailable', 'reason': 'charger_offline', 'message': 'x', 'alternatives': []}}
        client = ApiClient('https://api.example.test/v1', httpx.MockTransport(lambda request: httpx.Response(409, json=body)))
        with self.assertRaises(ApiError) as caught:
            await client.request('POST', 'reservations', {'connector_id': 'p'}, auth=False)
        self.assertEqual(str(caught.exception), OFFLINE)
        await client.close()


class DemoChargerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = [0.0]
        night = datetime(2026, 10, 21, 3, 0, tzinfo=timezone(timedelta(hours=-3)))
        self.api = DemoApi(clock=lambda: self.clock[0], start_at=night)
        await self.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        stations = (await self.api.request('GET', 'operator/stations'))['items']
        self.station = stations[0]
        self.points = self.station['connectors']
        self.by_code = {p['public_code']: p for p in self.points}

    async def test_every_owner_point_has_addresses_1_to_n_and_simulated_chargers_are_online(self):
        self.assertGreater(len(self.points), 1)
        ordered = sorted(self.points, key=lambda p: int(p['id'].rsplit('-', 1)[-1]))
        self.assertEqual([p['charger_address'] for p in ordered], list(range(1, len(ordered) + 1)))
        for item in self.points:
            block = item['charger_link']
            self.assertEqual((block['address'], block['host']),
                             (item['charger_address'], f"cg-hca-{item['charger_address']}.local"))
            if not item['screen_online']:
                continue  # CG-15: a tela dele está offline (o ponto offline de sempre da demo)
            self.assertEqual(block['link'], 'online')
            self.assertTrue(item['online'])
            self.assertIsNone(item['unavailable_reason'])
            self.assertIsNotNone(block['last_online_at'])
            self.assertEqual(block['measured_power_w'], 0)
            self.assertEqual(operator.charger_status(item),
                             f"Carregador {item['charger_address']} · GoodWe HCA G2 · online")

    async def test_one_screen_commands_two_chargers(self):
        screen, extra = self.by_code['CG-11'], self.by_code['CG-13']
        self.assertEqual(screen['screen']['role'], 'screen')
        self.assertEqual(extra['screen']['role'], 'charger')
        self.assertEqual(extra['screen']['device_id'], screen['screen']['device_id'])
        self.assertEqual(extra['screen']['public_code'], 'CG-11')
        self.assertTrue(self.station['screen_online'])
        shared = next(s for s in self.station['screens'] if s['connector_id'] == screen['id'])
        self.assertEqual(sorted(shared['charger_ids']), sorted([screen['id'], extra['id']]))
        self.assertFalse(self.by_code['CG-15']['screen_online'])
        self.assertEqual(self.by_code['CG-15']['unavailable_reason'], 'screen_offline')

    async def test_both_chargers_of_the_screen_start_and_the_power_is_read(self):
        for code in ('CG-13', 'CG-11'):
            session = await self.api.request('POST', 'charging-sessions', {
                'presence_code': DEMO_PRESENCE_CODE, 'public_code': code, 'max_duration_minutes': 30},
                key=self.api.new_key())
            self.clock[0] += 2
            current = await self.api.request('GET', f"charging-sessions/{session['id']}")
            self.assertEqual(current['status'], 'charging')
            station = await self.api.request('GET', f"stations/{self.station['id']}")
            row = next(p for p in station['connectors'] if p['public_code'] == code)
            self.assertGreater(row['charger_link']['measured_power_w'], 0)
            await self.api.request('POST', f"charging-sessions/{session['id']}/stop", {}, key=self.api.new_key())
            self.clock[0] += 3

    async def test_add_charger_creates_the_next_address_inactive_on_the_same_screen(self):
        created = await self.api.request('POST', f"connectors/{self.by_code['CG-13']['id']}/chargers")
        self.assertEqual(created['charger_address'], 4)
        self.assertFalse(created['active'])
        self.assertEqual(created['screen']['public_code'], 'CG-11')
        self.assertEqual(created['screen']['role'], 'charger')
        self.assertEqual(created['charger_link']['link'], 'online')
        self.assertEqual((created['connector_type'], created['power_kw'], created['max_duration_minutes']),
                         ('CCS2', '60.000', 120))
        retired = self.by_code['CG-15']
        self.api._devices[next(d for d in self.api._devices if self.api._devices[d]['connector_id'] == retired['id'])
                          ]['revoked'] = True
        with self.assertRaises(ApiError) as caught:
            await self.api.request('POST', f"connectors/{retired['id']}/chargers")
        self.assertEqual((caught.exception.status, caught.exception.code), (409, 'screen_required'))

    async def test_add_charger_button_in_the_demo(self):
        app = HandlerApp()
        app.api = self.api
        screen = station_admin._connectors_page(app, self.station)
        await click(screen, chargers.ADD_LABEL)(None)
        self.assertIn('Carregador 4 criado', texts(screen))
        self.assertIn('CG_ADDR = 4', texts(screen))
        station = await self.api.request('GET', f"stations/{self.station['id']}")
        self.assertEqual(sorted(p['charger_address'] for p in station['connectors']), [1, 2, 3, 4])

    async def test_offline_charger_is_refused_with_alternatives_and_others_keep_working(self):
        extra = self.by_code['CG-13']
        self.api.set_charger_online(extra['id'], False)
        listing = await self.api.request('GET', 'stations')
        row = next(p for s in listing['items'] for p in s['connectors'] if p['id'] == extra['id'])
        self.assertEqual((row['online'], row['screen_online'], row['unavailable_reason'], row['available']),
                         (False, True, 'charger_offline', False))
        self.assertEqual(point_status(row)[0], 'Carregador offline')
        owner = await self.api.request('GET', f"stations/{self.station['id']}")
        self.assertEqual(next(p for p in owner['connectors'] if p['id'] == extra['id'])['charger_link']['link'], 'offline')
        self.assertTrue(owner['screen_online'])  # a estação (tela) continua online
        with self.assertRaises(ApiError) as caught:
            await self.api.request('POST', 'charging-sessions', {
                'presence_code': DEMO_PRESENCE_CODE, 'public_code': 'CG-13'}, key=self.api.new_key())
        error = caught.exception
        self.assertEqual((error.status, error.code, error.reason), (409, 'point_unavailable', 'charger_offline'))
        self.assertTrue(str(error).startswith(OFFLINE))
        self.assertIn('CG-11', str(error))
        self.assertIn('CG-11', [item['public_code'] for item in error.alternatives])
        session = await self.api.request('POST', 'charging-sessions', {
            'presence_code': DEMO_PRESENCE_CODE, 'public_code': 'CG-11'}, key=self.api.new_key())
        self.assertEqual(session['status'], 'starting')

    async def test_charger_that_drops_during_start_ends_with_charger_offline(self):
        session = await self.api.request('POST', 'charging-sessions', {
            'presence_code': DEMO_PRESENCE_CODE, 'public_code': 'CG-13'}, key=self.api.new_key())
        self.api.set_charger_online(self.by_code['CG-13']['id'], False)
        ended = await self.api.request('GET', f"charging-sessions/{session['id']}")
        self.assertEqual((ended['status'], ended['end_reason']), ('failed', 'charger_offline'))
        self.assertEqual(charging.END_REASONS[ended['end_reason']], OFFLINE)

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

    async def test_driver_payloads_do_not_carry_owner_charger_fields(self):
        listing = await self.api.request('GET', 'stations')
        others = [s for s in listing['items'] if s['id'] != self.station['id']]
        self.assertTrue(others)
        for station in others:
            self.assertNotIn('screens', station)
            self.assertIn('screen_online', station)
            for item in station['connectors']:
                for key in ('charger_address', 'charger_link', 'screen'):
                    self.assertNotIn(key, item)
                self.assertIn('screen_online', item)
                self.assertIn('unavailable_reason', item)

    async def test_demo_charger_screen_edits_through_the_demo_api(self):
        app = HandlerApp()
        app.api = self.api
        target = self.points[0]
        screen = await operator.connector_form(app, self.station['id'], dict(target))
        field = fields(screen)[operator.CHARGER_FIELD]
        self.assertEqual(field.value, str(target['charger_address']))
        field.value = '7'
        await click(screen, 'Salvar alterações')(None)
        station = await self.api.request('GET', f"stations/{self.station['id']}")
        self.assertEqual(next(p for p in station['connectors'] if p['id'] == target['id'])['charger_address'], 7)
        self.assertIn('CG_ADDR = 7', app.notices[-1])
        field.value = ''
        with self.assertRaises(ApiError):
            await click(screen, 'Salvar alterações')(None)
        self.assertEqual(field.error_text, EMPTY)

    async def test_demo_removes_an_additional_charger_and_frees_its_address(self):
        extra, own = self.by_code['CG-13'], self.by_code['CG-11']
        for target in (own, self.by_code['CG-15']):
            with self.assertRaises(ApiError) as caught:
                await self.api.request('DELETE', f"connectors/{target['id']}")
            self.assertEqual((caught.exception.status, caught.exception.code), (409, 'screen_charger'))
        session = await self.api.request('POST', 'charging-sessions', {
            'presence_code': DEMO_PRESENCE_CODE, 'public_code': 'CG-13', 'max_duration_minutes': 30},
            key=self.api.new_key())
        with self.assertRaises(ApiError) as caught:
            await self.api.request('DELETE', f"connectors/{extra['id']}")
        self.assertEqual((caught.exception.status, caught.exception.code), (409, 'point_busy'))
        await self.api.request('POST', f"charging-sessions/{session['id']}/stop", {}, key=self.api.new_key())
        self.clock[0] += 5
        self.assertIsNone(await self.api.request('DELETE', f"connectors/{extra['id']}"))
        station = await self.api.request('GET', f"stations/{self.station['id']}")
        self.assertEqual(sorted(p['public_code'] for p in station['connectors']), ['CG-11', 'CG-15'])
        # A recarga antiga continua no histórico e o endereço 2 volta a ser o próximo livre.
        history = await self.api.request('GET', 'me/charging-sessions')
        self.assertIn(session['id'], [item['id'] for item in history['items']])
        created = await self.api.request('POST', f"connectors/{own['id']}/chargers")
        self.assertEqual(created['charger_address'], extra['charger_address'])
        with self.assertRaises(ApiError) as caught:
            await self.api.request('DELETE', f"connectors/{extra['id']}")
        self.assertEqual(caught.exception.status, 404)

    async def test_remove_button_in_the_demo(self):
        app = HandlerApp()
        app.api = self.api
        app.page.show_dialog, app.page.pop_dialog = Mock(), Mock()
        extra = self.by_code['CG-13']
        own = await operator.connector_form(app, self.station['id'], dict(self.by_code['CG-11']))
        self.assertNotIn(chargers.REMOVE_LABEL, buttons(own))
        screen = await operator.connector_form(app, self.station['id'], dict(extra))
        await click(screen, chargers.REMOVE_LABEL)(None)
        await app.page.show_dialog.call_args.args[0].actions[1].on_click(None)
        station = await self.api.request('GET', f"stations/{self.station['id']}")
        self.assertNotIn(extra['id'], [p['id'] for p in station['connectors']])
        app.go.assert_awaited_with('station_admin', station_id=self.station['id'], page='connectors')
