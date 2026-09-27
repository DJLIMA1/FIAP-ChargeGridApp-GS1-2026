"""Consumer journeys, point identity, limit modes and opt-in search storage."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.screens import charging, history, home, reservations, stations
from chargegrid_app.services.search_location import SearchLocation
from chargegrid_app.ui.point_summary import point_context
from test_behavior import HandlerApp, click, descendants

POINT = {'id':'point-one','public_code':'CG-ONE','connector_type':'Tipo 2',
         'power_kw':'6','price_per_kwh':'2','max_duration_minutes':10,'available':True}
STATION = {'id':'station-one','name':'Posto Central','address':'Rua Central, 10',
           'latitude':-23.5,'longitude':-46.6,'connectors':[POINT]}
CONTEXT = point_context(STATION,POINT)


def texts(screen):
    return ' '.join(str(item.value) for item in descendants(screen) if isinstance(item,ft.Text))


def fields(screen):
    return {item.label:item for item in descendants(screen) if isinstance(item,ft.TextField)}


def reservation(status='confirmed'):
    return {'id':'reservation-one','connector_id':POINT['id'],'status':status,
            'expires_at':'2026-09-27T12:00:00+00:00',**CONTEXT}


def charging_app(active_reservation=None):
    app = HandlerApp()

    async def request(method,path,*args,**kwargs):
        if method == 'POST':
            return {'id':'session-one'}
        return {'charging-sessions/current':None,'reservations/current':active_reservation}[path]

    app.api.request.side_effect = request
    return app


async def next_charging_step(app,screen):
    await click(screen,'Continuar')(None)
    return await charging.build(app,**app.go.call_args.kwargs)


async def charging_limits(app,**kwargs):
    screen = await charging.build(app,**kwargs)
    fields(screen)['Código temporário do posto'].value = '12345'
    return await next_charging_step(app,screen)


class ConsumerFlowsTests(unittest.IsolatedAsyncioTestCase):
    async def test_consumer_home_keeps_vendor_account_on_consumer_journey(self):
        app = HandlerApp()
        app.profile = {'account_type':'vendor','operator_enabled':True,'name':'Vendedor'}
        app.switch_mode = AsyncMock()
        responses = {'charging-sessions/current':None,'reservations/current':None,
                     'stations':{'items':[],'total':0},'me/summary':{}}
        app.api.request.side_effect = lambda method,path,**kwargs: responses[path]
        screen = await home.build(app)
        self.assertNotIn('Gerenciar postos',texts(screen))
        await click(screen,'Recarregar agora')(None)
        app.go.assert_awaited_once_with('stations')
        app.switch_mode.assert_not_called()

    async def test_generic_code_recovers_reserved_point_and_caps_initial_duration(self):
        app = charging_app(reservation())
        app.api.last_session_id = 'old-session'
        screen = await charging.build(app)
        self.assertIn('Posto Central',texts(screen))
        fields(screen)['Código temporário do posto'].value = '12345'
        screen = await next_charging_step(app,screen)
        self.assertEqual(fields(screen)['Duração máxima (min)'].value,'10')
        screen = await next_charging_step(app,screen)
        await click(screen,'Solicitar início')(None)
        body = app.api.request.call_args.args[2]
        self.assertEqual(body['reservation_id'],'reservation-one')
        self.assertEqual(body['max_duration_minutes'],10)
        self.assertEqual(body['presence_code'],'#F12345')

    async def test_pending_reservation_cannot_request_start(self):
        app = charging_app(reservation('pending_device'))
        screen = await charging.build(app)
        self.assertNotIn('Solicitar início',texts(screen))
        self.assertIn('Aguarde a confirmação',texts(screen))
        await click(screen,'Ver minha reserva')(None)
        app.go.assert_awaited_once_with('reservations')

    async def test_different_selected_point_does_not_silently_use_reservation(self):
        app = charging_app(reservation())
        screen = await charging.build(app,public_code='CG-OTHER')
        self.assertIn('outro ponto',texts(screen))
        self.assertNotIn('Solicitar início',texts(screen))
        self.assertEqual([call.args[0] for call in app.api.request.call_args_list],['GET','GET'])

    async def test_expired_selected_reservation_returns_to_reservations(self):
        app = charging_app()
        screen = await charging.build(app,reservation_id='expired')
        self.assertIn('Reserva não está mais ativa',texts(screen))
        self.assertFalse(fields(screen))

    async def test_context_must_match_explicit_public_code(self):
        app = charging_app()
        with self.assertRaisesRegex(ApiError,'ponto selecionado mudou'):
            await charging.build(app,public_code='CG-OTHER',point_context=CONTEXT)

    async def test_known_point_duration_rejected_before_post(self):
        app = charging_app()
        screen = await charging_limits(app,public_code='CG-ONE',point_context=CONTEXT)
        inputs = fields(screen)
        inputs['Duração máxima (min)'].value = '11'
        app.api.request.reset_mock()
        with self.assertRaisesRegex(ApiError,'1 a 10 minutos'):
            await click(screen,'Continuar')(None)
        app.api.request.assert_not_called()

    async def test_by_value_requires_cost_and_sends_both_safety_limits(self):
        app = charging_app()
        screen = await charging_limits(app,public_code='CG-ONE',point_context=CONTEXT)
        inputs = fields(screen)
        await click(screen,'Por valor')(None)
        with self.assertRaisesRegex(ApiError,'Informe o valor'):
            await click(screen,'Continuar')(None)
        inputs['Limite de custo estimado (R$)'].value = '1,50'
        await inputs['Limite de custo estimado (R$)'].on_change(None)
        self.assertIn('0.75 kWh',texts(screen))
        screen = await next_charging_step(app,screen)
        self.assertIn('nenhuma cobrança real',texts(screen).lower())
        await click(screen,'Solicitar início')(None)
        body = app.api.request.call_args.args[2]
        self.assertEqual(body['max_cost'],'1.50')
        self.assertEqual(body['max_duration_minutes'],10)
        self.assertEqual(body['public_code'],'CG-ONE')
        self.assertNotIn('payment',body)
        self.assertNotIn('soc_percent',body)

    async def test_by_time_estimate_is_explicitly_nominal_and_not_battery_soc(self):
        screen = await charging_limits(charging_app(),public_code='CG-ONE',point_context=CONTEXT)
        self.assertIn('Na potência nominal',texts(screen))
        self.assertIn('R$ 2,00',texts(screen))
        self.assertIn('O consumo real varia',texts(screen))
        self.assertNotIn('Bateria:',texts(screen))

    async def test_free_point_requires_time_mode_instead_of_unreachable_value_cap(self):
        app = charging_app()
        context = {**CONTEXT,'connector':{**CONTEXT['connector'],'price_per_kwh':'0'}}
        screen = await charging_limits(app,public_code='CG-ONE',point_context=context)
        inputs = fields(screen)
        inputs['Limite de custo estimado (R$)'].value = '5'
        await click(screen,'Por valor')(None)
        with self.assertRaisesRegex(ApiError,'tarifa gratuita'):
            await click(screen,'Continuar')(None)
        self.assertTrue(all(call.args[0] == 'GET' for call in app.api.request.call_args_list))

    async def test_invalid_estimate_inputs_do_not_crash_change_handler(self):
        screen = await charging_limits(charging_app(),public_code='CG-ONE',point_context=CONTEXT)
        duration = fields(screen)['Duração máxima (min)']
        for value in ('NaN','1e999999999','Infinity','abc'):
            duration.value = value
            await duration.on_change(None)
            self.assertIn('A estimativa depende',texts(screen))

    async def test_generic_charge_recovers_known_result_when_current_is_empty(self):
        app = HandlerApp()
        app.api.last_session_id = 'completed-old'
        app.api.request.side_effect = [None,None,{'id':'completed-old','status':'completed','max_duration_minutes':10}]
        screen = await charging.build(app)
        self.assertIn('Recarga concluída',texts(screen))
        self.assertIn('Iniciar outra recarga',texts(screen))
        self.assertEqual(app.api.request.call_args.args,('GET','charging-sessions/completed-old'))

    async def test_history_uses_session_tariff_and_limit_not_current_point_price(self):
        app = HandlerApp()
        session = {**CONTEXT,'id':'session','status':'completed','max_duration_minutes':5,'price_per_kwh':'1.25'}
        app.api.request.return_value = {'items':[session],'total':1}
        screen = await history.build(app)
        self.assertIn('Tarifa da sessão: R$ 1,25/kWh',texts(screen))
        self.assertNotIn('R$ 2,00/kWh',texts(screen))
        self.assertIn('limite de 5 min',texts(screen))

    async def test_reservation_screen_shows_destination_and_correct_charge_context(self):
        app = HandlerApp()
        app.api.request.return_value = reservation()
        screen = await reservations.build(app)
        self.assertIn('Posto Central',texts(screen))
        self.assertIn('Rua Central, 10',texts(screen))
        await click(screen,'Cheguei: informar código')(None)
        self.assertEqual(app.go.call_args.kwargs['max_duration'],10)
        self.assertEqual(app.go.call_args.kwargs['point_context']['connector']['id'],'point-one')

    async def test_operator_history_preserves_scope_through_pagination(self):
        app = HandlerApp()
        app.profile = {'operator_enabled': True}
        app.api.request.return_value = {'items':[],'total':41}
        screen = await history.build(app,manage=True,offset=20)
        app.api.request.assert_awaited_once_with('GET','operator/charging-sessions',params={'limit':20,'offset':20})
        self.assertIn('Histórico dos meus postos',texts(screen))
        await click(screen,'Mais sessões')(None)
        app.go.assert_awaited_once_with('history',station_id=None,offset=40,manage=True)

    async def test_station_selection_keeps_public_point_identity(self):
        app = HandlerApp()
        app.api.request.return_value = STATION
        with patch.object(stations, 'station_map_widget',new=AsyncMock(return_value=ft.Text('Map'))):
            screen = await stations.build(app,station_id=STATION['id'])
        self.assertNotIn('Endereço para buscar',fields(screen))
        self.assertIn('CG-ONE · Tipo 2',texts(screen))
        await click(screen,'Já estou aqui: iniciar')(None)
        self.assertEqual(app.go.call_args.kwargs['point_context'],CONTEXT)
        self.assertEqual(app.go.call_args.kwargs['public_code'],'CG-ONE')

    async def test_station_poll_updates_pagination_even_when_items_unchanged(self):
        app = HandlerApp()
        app.api.request.side_effect = [{'items':[STATION],'total':20},{'items':[STATION],'total':21},{'items':[STATION],'total':20}]
        with patch.object(stations, 'station_map_widget',new=AsyncMock(return_value=ft.Text('Map'))) as draw:
            screen = await stations.build(app)
            self.assertNotIn('Mais postos',texts(screen))
            await app.poll()
            self.assertIn('Mais postos',texts(screen))
            await app.poll()
            self.assertNotIn('Mais postos',texts(screen))
            self.assertEqual(draw.await_count,1)

    async def test_station_search_preserves_poll_state_and_map_is_inline_not_redundant(self):
        app = HandlerApp()
        app.api.request.side_effect = [
            {'items':[STATION],'total':1},
            {'items':[{**STATION,'connectors':[{**POINT,'available':False}]}],'total':1},
        ]
        with patch.object(stations, 'station_map_widget',new=AsyncMock(return_value=ft.Text('Map'))):
            screen = await stations.build(app)
            sections = {item.title.value:item for item in descendants(screen) if isinstance(item,ft.ExpansionTile)}
            search_section = sections['Buscar perto de um endereço']
            self.assertFalse(search_section.expanded)
            self.assertTrue(search_section.maintain_state)
            self.assertEqual(list(sections),['Buscar perto de um endereço'])
            map_section = next(item for item in screen.controls
                               if isinstance(item,ft.Column) and 'Estações no mapa' in texts(item))
            self.assertTrue(map_section.visible)
            self.assertIn('Map',texts(map_section))
            listing = next(item for item in screen.controls
                           if isinstance(item,ft.Column) and 'Ver pontos' in texts(item))
            self.assertLess(screen.controls.index(map_section),screen.controls.index(listing))
            address = fields(screen)['Endereço para buscar']
            address.value = 'Filtro em edição'
            search_section.expanded = True
            await app.poll()
            self.assertTrue(search_section.expanded)
            self.assertTrue(map_section.visible)
            self.assertIs(fields(screen)['Endereço para buscar'],address)
            self.assertEqual(address.value,'Filtro em edição')

    async def test_active_location_filter_is_initially_expanded(self):
        for data in ({'query':'Praça'}, {'lat':-23.5,'lng':-46.6}):
            with self.subTest(data=data):
                app = HandlerApp()
                app.api.request.return_value = {'items':[],'total':0}
                screen = await stations.build(app,**data)
                search_section = next(item for item in descendants(screen)
                                      if isinstance(item,ft.ExpansionTile) and item.title.value=='Buscar perto de um endereço')
                self.assertTrue(search_section.expanded)

    async def test_coordinate_mode_ignores_failed_address_and_retains_fields(self):
        app = HandlerApp()
        app.api.request.return_value = {'items':[],'total':0}
        screen = await stations.build(app)
        inputs = fields(screen)
        inputs['Endereço para buscar'].value = 'Endereço que falhou'
        inputs['Latitude'].value,inputs['Longitude'].value = '-23.5','-46.6'
        mode = next(item for item in descendants(screen) if isinstance(item,ft.Dropdown))
        mode.value = 'coordinates'
        await mode.on_select(None)
        with patch.object(stations,'geocode_address',new=AsyncMock()) as geocode:
            await click(screen,'Buscar')(None)
        geocode.assert_not_called()
        app.go.assert_awaited_once_with('stations',lat=-23.5,lng=-46.6,radius=5.0,query='')
        self.assertEqual(inputs['Endereço para buscar'].value,'Endereço que falhou')

    async def test_hidden_coordinates_do_not_filter_address_mode(self):
        app = HandlerApp()
        app.api.request.return_value = {'items':[],'total':0}
        screen = await stations.build(app)
        inputs = fields(screen)
        inputs['Latitude'].value,inputs['Longitude'].value = '-23.5','-46.6'
        await click(screen,'Buscar')(None)
        app.go.assert_awaited_once_with('stations',lat=None,lng=None,radius=5.0,query='')

    async def test_search_is_saved_only_by_explicit_click_and_can_be_removed(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ',{'FLET_APP_STORAGE_DATA':directory}):
            app = HandlerApp()
            app.profile = {'id':'user-one'}
            app.api.request.return_value = {'items':[],'total':0}
            screen = await stations.build(app,lat=-23.5,lng=-46.6)
            self.assertEqual(list(Path(directory).iterdir()),[])
            await click(screen,'Buscar')(None)
            self.assertEqual(list(Path(directory).iterdir()),[])
            await click(screen,'Salvar busca neste dispositivo')(None)
            stored = SearchLocation('user-one').load()
            self.assertEqual(stored,{'lat':-23.5,'lng':-46.6,'radius':5.0,'query':''})
            self.assertIsNone(SearchLocation('user-two').load())
            await click(screen,'Remover busca salva')(None)
            self.assertIsNone(SearchLocation('user-one').load())
            self.assertNotIn('Usar busca salva',texts(screen))


class SearchLocationTests(unittest.TestCase):
    def test_persistence_is_account_scoped_and_whitelists_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            first = SearchLocation('first-user',directory)
            data = {'lat':1,'lng':2,'radius':5,'query':'Praça','token':'secret-not-stored'}
            self.assertTrue(first.save(data))
            self.assertEqual(SearchLocation('first-user',directory).load()['query'],'Praça')
            self.assertIsNone(SearchLocation('other-user',directory).load())
            self.assertNotIn('secret-not-stored',first.path.read_text())
            self.assertNotIn('first-user',first.path.name)
            self.assertEqual(first.path.stat().st_mode & 0o777,0o600)
            self.assertTrue(first.remove())
            self.assertIsNone(first.load())

    def test_invalid_location_or_missing_account_never_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SearchLocation('user',directory)
            for data in [None,{}, {'lat':float('nan'),'lng':2,'radius':5},
                         {'lat':1,'lng':181,'radius':5},{'lat':1,'lng':2,'radius':0}]:
                self.assertFalse(store.save(data))
            self.assertFalse(SearchLocation(None,directory).save({'lat':1,'lng':2,'radius':5}))
            self.assertEqual(list(Path(directory).iterdir()),[])
