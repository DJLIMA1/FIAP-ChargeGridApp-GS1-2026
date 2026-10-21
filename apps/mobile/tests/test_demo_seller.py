"""Seller simulation uses local demo operations, never camera or geocoding."""
import unittest
from unittest.mock import Mock, patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import (
    DEMO_CLAIM_TOKEN,
    DEMO_EMAIL,
    DEMO_PASSWORD,
    DEMO_PRESENCE_CODE,
    DemoApi,
)
from chargegrid_app.screens import onboarding, operator, ownership
from test_behavior import HandlerApp, click, descendants
from test_seller_flow_fixes import fields, station_fixture, texts


class DemoSellerTests(unittest.IsolatedAsyncioTestCase):
    def demo_app(self):
        app = HandlerApp()
        app.api.is_demo = True
        app.api.new_claim_token = Mock(return_value=DEMO_CLAIM_TOKEN)
        return app

    async def test_demo_claim_needs_no_camera_and_retries_same_local_identity(self):
        app = self.demo_app()
        app.page.web = True
        app.api.request.side_effect = [ApiError('Falha simulada'),{'station_id':'station','connector_id':'point'}]
        screen = await ownership.build(app)
        self.assertNotIn('Escanear QR Code',texts(screen))
        self.assertNotIn('Código privado do QR',fields(screen))
        self.assertIn('inteiramente fictício',texts(screen))
        app.api.request.assert_not_called()
        app.api.new_claim_token.assert_not_called()
        with self.assertRaises(ApiError):
            await click(screen,'Adicionar equipamento simulado')(None)
        await click(screen,'Adicionar equipamento simulado')(None)
        app.api.new_claim_token.assert_called_once_with()
        self.assertEqual([call.args for call in app.api.request.await_args_list],[
            ('POST','ownership/claim',{'token':DEMO_CLAIM_TOKEN}),
            ('POST','ownership/claim',{'token':DEMO_CLAIM_TOKEN}),
        ])
        app.go.assert_awaited_with('operator',station_id='station',point_id='point',onboarding=True,step=1)

    async def test_demo_claim_into_existing_station_keeps_selected_destination(self):
        app = self.demo_app()
        app.api.request.side_effect = [station_fixture(),{'station_id':'station','connector_id':'new-point'}]
        screen = await ownership.build(app,station_id='station')
        self.assertIn('Posto Central',texts(screen))
        await click(screen,'Adicionar equipamento simulado')(None)
        app.api.request.assert_awaited_with('POST','ownership/claim',{
            'token':DEMO_CLAIM_TOKEN,'station_id':'station',
        })
        app.go.assert_awaited_with('operator',station_id='station',point_id='new-point',
                                  onboarding=True,step=2,existing_station=True)

    async def test_real_claim_keeps_camera_and_has_no_simulated_operation(self):
        app = HandlerApp()
        screen = await ownership.build(app)
        self.assertIn('Escanear QR Code',texts(screen))
        self.assertNotIn('Adicionar equipamento simulado',texts(screen))
        self.assertIn('Código privado do QR',fields(screen))

    async def test_demo_dashboard_lists_stations_and_keeps_local_add_action(self):
        app = self.demo_app()
        app.api.request.side_effect = [
            {'account_type':'vendor','operator_enabled':True},
            {'items':[station_fixture()],'total':1},
        ]
        screen = await operator.build(app)
        self.assertIn('Posto Central',texts(screen))
        self.assertIn('Adicionar nova estação',texts(screen))
        self.assertIn('Com um equipamento simulado',texts(screen))
        self.assertNotIn('Ligue a tela',texts(screen))
        add = next(c for c in descendants(screen) if isinstance(c,ft.Container) and c.on_click
                   and 'Adicionar nova estação' in texts(c) and not isinstance(c.content,ft.Column))
        await add.on_click(None)
        app.go.assert_awaited_with('operator',claim=True)

    async def test_demo_new_station_location_comes_from_the_address(self):
        app = self.demo_app()
        app.api.request.side_effect = [{'items': []}, {'id': 'new-station'}]
        screen = await operator.station_form(app)
        self.assertNotIn('Latitude', fields(screen))
        fields(screen)['Nome da estação'].value = 'Posto Novo'
        fields(screen)['Endereço'].value = 'Rua Fictícia, 42'
        await click(screen,'Salvar posto')(None)
        method, path, body = app.api.request.await_args.args[:3]
        # Demo sem sugestão: centro de São Paulo, sem geocodificador externo.
        self.assertEqual((method, path, body['latitude'], body['longitude']), ('POST', 'stations', '-23.5505', '-46.6333'))
        app.go.assert_awaited_with('station_admin', station_id='new-station')

    async def test_demo_onboarding_location_uses_the_address(self):
        app = self.demo_app()
        station = station_fixture(active=False)

        async def request(method, path, body=None, **kwargs):
            if path == 'geo/address-suggestions':
                return {'items': [{'label': 'Avenida Paulista, 1000, Bela Vista, São Paulo - SP',
                                   'latitude': -23.5648865, 'longitude': -46.651918}]}
            return station
        app.api.request.side_effect = request
        screen = await onboarding.build(app,'station','point',step=1)
        self.assertIn('PONTO SIMULADO',texts(screen))
        self.assertIn(DEMO_PRESENCE_CODE,texts(screen))
        self.assertNotIn('Latitude', fields(screen))
        fields(screen)['Endereço'].value = 'av paulista 1000'
        await click(screen,'Salvar e continuar')(None)
        self.assertEqual(app.api.request.await_args.args[:2],('PATCH','stations/station'))
        self.assertEqual(app.api.request.await_args.args[2]['longitude'],'-46.651918')

    async def test_demo_publish_displays_presence_code_without_physical_instructions(self):
        app = self.demo_app()
        station = station_fixture(active=False)
        station['connectors'][0]['online'] = False
        app.api.request.return_value = station
        screen = await onboarding.build(app,'station','point',step=3)
        self.assertIn('Offline simulado',texts(screen))
        self.assertNotIn('O equipamento ainda não está conectado',texts(screen))
        await click(screen,'Publicar ponto')(None)
        self.assertIn('Ponto simulado publicado',app.notices[-1])
        self.assertIn(DEMO_PRESENCE_CODE,app.notices[-1])

    async def test_demo_device_maintenance_is_labeled_and_does_not_request_hardware_setup(self):
        app = self.demo_app()
        app.page.show_dialog = Mock()
        app.page.pop_dialog = Mock()
        app.api.request.side_effect = [
            {'device_id':'demo-device','online':True},{'status':'not_requested'},
            {'device_id':'demo-device','device_key':'DEMO-KEY-NOT-REAL'},
        ]
        screen = await operator.connector_form(app,'station',station_fixture()['connectors'][0])
        self.assertIn('Credencial e restauração simuladas',texts(screen))
        self.assertIn(DEMO_PRESENCE_CODE,texts(screen))
        self.assertNotIn('ESP32',texts(screen))
        await click(screen,'Rotacionar')(None)
        dialog = app.page.show_dialog.call_args.args[0]
        self.assertEqual(dialog.title.value,'Chave fictícia de demonstração')
        self.assertIn('Não a instale em um equipamento real',texts(dialog.content))

    async def test_demo_reset_confirmation_is_explicitly_local(self):
        app = self.demo_app()
        app.page.show_dialog = Mock()
        app.page.pop_dialog = Mock()
        app.api.request.side_effect = [
            {'device_id':'demo-device','online':True},{'status':'not_requested'},{'status':'applied'},
        ]
        screen = await operator.connector_form(app,'station',station_fixture()['connectors'][0])
        await click(screen,'Restaurar')(None)
        dialog = app.page.show_dialog.call_args.args[0]
        self.assertIn('Nenhum dispositivo físico ou Wi-Fi será alterado',dialog.content.value)
        await dialog.actions[1].on_click(None)
        app.api.request.assert_awaited_with('POST','devices/demo-device/factory-reset')
        self.assertIn('Restauração simulada confirmada',texts(screen))


class DemoSellerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_equipment_can_complete_all_setup_steps_without_network(self):
        with patch('httpx.AsyncClient',side_effect=AssertionError('Demo must not create a network client')):
            app = HandlerApp()
            app.api = DemoApi()
            await app.api.login(DEMO_EMAIL,DEMO_PASSWORD)
            app.profile = await app.api.request('GET','me')
            before = await app.api.request('GET','operator/stations')

            claim_screen = await ownership.build(app)
            await click(claim_screen,'Adicionar equipamento simulado')(None)
            route = app.go.await_args.kwargs
            station_id,point_id = route['station_id'],route['point_id']
            self.assertEqual(route['step'],1)

            location_screen = await onboarding.build(app,station_id,point_id,step=1)
            fields(location_screen)['Nome da estação'].value = 'Posto de teste local'
            fields(location_screen)['Endereço'].value = 'Rua Fictícia, 42, Cidade Simulada'
            await click(location_screen,'Salvar e continuar')(None)

            price_screen = await onboarding.build(app,station_id,point_id,step=2)
            fields(price_screen)['Tarifa por kWh (R$)'].value = '2,15'
            await click(price_screen,'Salvar e revisar')(None)
            review = await onboarding.build(app,station_id,point_id,step=3)
            await click(review,'Publicar ponto')(None)

            station = await app.api.request('GET',f'stations/{station_id}')
            self.assertTrue(station['active'])
            self.assertEqual(station['name'],'Posto de teste local')
            point = next(item for item in station['connectors'] if item['id'] == point_id)
            self.assertTrue(point['active'])
            self.assertEqual(float(point['price_per_kwh']),2.15)
            after = await app.api.request('GET','operator/stations')
            self.assertEqual(after['total'],before['total']+1)
            self.assertIn(DEMO_PRESENCE_CODE,texts(review))

    async def test_two_demo_claim_screens_add_distinct_points_to_same_existing_station(self):
        with patch('httpx.AsyncClient',side_effect=AssertionError('Demo must remain local')):
            app = HandlerApp()
            app.api = DemoApi()
            await app.api.login(DEMO_EMAIL,DEMO_PASSWORD)
            app.profile = await app.api.request('GET','me')
            owned = await app.api.request('GET','operator/stations')
            selected = owned['items'][0]
            station_id = selected['id']
            initial_points = len(selected['connectors'])
            claimed = []
            for _ in range(2):
                screen = await ownership.build(app,station_id=station_id)
                await click(screen,'Adicionar equipamento simulado')(None)
                route = app.go.await_args.kwargs
                self.assertEqual(route['station_id'],station_id)
                self.assertTrue(route['existing_station'])
                self.assertEqual(route['step'],2)
                claimed.append(route['point_id'])
            self.assertEqual(len(set(claimed)),2)
            final_station = await app.api.request('GET',f'stations/{station_id}')
            self.assertEqual(final_station['name'],selected['name'])
            self.assertEqual(final_station['address'],selected['address'])
            self.assertEqual(len(final_station['connectors']),initial_points+2)
