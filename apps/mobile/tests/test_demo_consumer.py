"""The demo consumer UI never geocodes, loads map tiles or persists searches."""

import unittest
from unittest.mock import AsyncMock, patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import (
    DEMO_EMAIL,
    DEMO_LOCATIONS,
    DEMO_PASSWORD,
    DEMO_PRESENCE_CODE,
    DemoApi,
)
from chargegrid_app.screens import charging, history, home, reservations, stations
from chargegrid_app.services import maps
from chargegrid_app.services.location import geocode_demo_address
from chargegrid_app.services.search_location import SearchLocation
from test_behavior import HandlerApp, click, descendants
from test_consumer_flows import (
    CONTEXT,
    STATION,
    charging_app,
    fields,
    next_charging_step,
    reservation,
    texts,
)
from test_station_ux import search_box


class DemoConsumerTests(unittest.IsolatedAsyncioTestCase):
    async def test_demo_reserve_charge_stop_and_history_use_only_local_api(self):
        clock = [0.0]
        with patch('httpx.AsyncClient',side_effect=AssertionError('network client')), \
                patch.object(maps,'build_map_png',side_effect=AssertionError('network tiles')), \
                patch.object(SearchLocation,'save',side_effect=AssertionError('persistent storage')):
            app = HandlerApp()
            app.api = DemoApi(clock=lambda:clock[0])
            await app.api.login(DEMO_EMAIL,DEMO_PASSWORD)
            app.profile = await app.api.request('GET','me')
            screen = await stations.build(app)
            self.assertIn('Villa Lobos',texts(screen))
            first_station = (await app.api.request('GET','stations'))['items'][0]
            screen = await stations.build(app,station_id=first_station['id'])
            self.assertIn('Reservar estação',texts(screen))
            self.assertIn('Carregar agora',texts(screen))
            # A reserva em si é criada pelo assistente (test_booking); aqui segue a jornada até o histórico.
            point = next(p for p in first_station['connectors'] if p.get('available'))
            await app.api.request('POST','reservations',{'connector_id':point['id']},key='demo-reserve')
            reservation_screen = await reservations.build(app,detail=True)
            self.assertIn('Aguardando confirmação simulada',texts(reservation_screen))
            clock[0] += 2
            await app.poll()
            app.go.assert_awaited_with('reservations',detail=True)
            reservation_screen = await reservations.build(app,detail=True)
            self.assertIn('Reserva simulada confirmada',texts(reservation_screen))
            await click(reservation_screen,'Cheguei: informar código')(None)
            start_screen = await charging.build(app,**app.go.call_args.kwargs)
            self.assertEqual(fields(start_screen)['Código temporário do posto'].value,'12345')
            start_screen = await next_charging_step(app,start_screen)
            start_screen = await next_charging_step(app,start_screen)
            await click(start_screen,'Solicitar início')(None)
            session_id = app.go.call_args.kwargs['session_id']
            active_screen = await charging.build(app,session_id=session_id)
            self.assertIn('Aguardando início simulado',texts(active_screen))
            clock[0] += 2
            await app.poll()
            active_screen = await charging.build(app,session_id=session_id)
            self.assertIn('Recarga simulada em andamento',texts(active_screen))
            clock[0] += 5
            await app.poll()
            state = await app.api.request('GET',f'charging-sessions/{session_id}')
            self.assertGreater(float(state['energy_wh']),0)
            self.assertIn(f"Energia: {float(state['energy_wh'])/1000:.3f} kWh".replace('.',','),texts(active_screen))
            await click(active_screen,'Encerrar recarga')(None)
            stopping_screen = await charging.build(app,session_id=session_id)
            self.assertIn('Finalizando recarga simulada',texts(stopping_screen))
            clock[0] += 2
            await app.poll()
            completed_screen = await charging.build(app,session_id=session_id)
            self.assertIn('Recarga simulada concluída',texts(completed_screen))
            await click(completed_screen,'Ver eventos da sessão')(None)
            self.assertIn('Início confirmado na simulação',texts(completed_screen))
            self.assertIn('simulador local',texts(completed_screen))
            kinds = [event['kind'] for event in await app.api.request('GET',f'charging-sessions/{session_id}/events')]
            self.assertEqual(kinds,['start_requested','start_applied','stop_requested','ended'])
            history_screen = await history.build(app)
            self.assertIn('Villa Lobos',texts(history_screen))
            self.assertIn('HISTÓRICO SIMULADO',texts(history_screen))
            self.assertIsNone(await app.api.request('GET','charging-sessions/current'))
            await app.api.close()

    async def test_demo_map_is_local_before_any_tile_download(self):
        with patch.object(maps,'build_map_png',side_effect=AssertionError('network renderer')) as render:
            screen = await maps.map_widget(-23.55,-46.63,[(-23.55,-46.63,'⚡')],offline=True)
        render.assert_not_called()
        self.assertIn('Mapa esquemático da demonstração',texts(screen))
        self.assertIn('sem acesso à rede',texts(screen))
        self.assertFalse(any(isinstance(control,ft.Image) for control in descendants(screen)))

    async def test_demo_station_build_and_poll_never_touch_storage_or_network(self):
        app = HandlerApp()
        app.api.is_demo = True
        app.profile = {'id':'demo-profile'}
        app.api.request.side_effect = [
            {'items':[STATION],'total':1},
            {'items':[{**STATION,'connectors':[{**STATION['connectors'][0],'available':False}]}],'total':1},
        ]
        with patch.object(SearchLocation,'__init__',side_effect=AssertionError('persistent storage')) as storage, \
                patch.object(maps,'build_map_png',side_effect=AssertionError('network tiles')) as render, \
                patch('httpx.AsyncClient',side_effect=AssertionError('network client')):
            screen = await stations.build(app)
            await app.poll()
        storage.assert_not_called()
        render.assert_not_called()
        self.assertIn('Mapa esquemático da demonstração',texts(screen))
        self.assertNotIn('Código #F12345',texts(screen))
        self.assertNotIn('Salvar busca neste dispositivo',texts(screen))
        self.assertNotIn('Usar busca salva',texts(screen))
        self.assertNotIn('Busca inteligente',texts(screen))

    async def test_demo_known_search_uses_fixture_not_geocoding_service(self):
        app = HandlerApp()
        app.api.is_demo = True
        app.api.request.return_value = {'items':[],'total':0}
        screen = await stations.build(app)
        search = search_box(screen)
        search.value = DEMO_LOCATIONS[0]['name']
        with patch.object(stations,'geocode_address',new=AsyncMock(side_effect=AssertionError('online geocoder'))) as geocode:
            await search.on_submit(None)
        geocode.assert_not_called()
        self.assertEqual(app.go.call_args.kwargs['lat'],float(DEMO_LOCATIONS[0]['latitude']))
        self.assertEqual(app.go.call_args.kwargs['lng'],float(DEMO_LOCATIONS[0]['longitude']))
        self.assertEqual(app.go.call_args.kwargs['query'],DEMO_LOCATIONS[0]['name'])

    async def test_demo_unknown_search_explains_local_scope_without_fallback(self):
        app = HandlerApp()
        app.api.is_demo = True
        app.api.request.return_value = {'items':[],'total':0}
        screen = await stations.build(app)
        search_box(screen).value = 'Um endereço particular desconhecido'
        with patch.object(stations,'geocode_address',new=AsyncMock(side_effect=AssertionError('online geocoder'))) as geocode:
            with self.assertRaisesRegex(ApiError,'conta demo'):
                await search_box(screen).on_submit(None)
        geocode.assert_not_called()
        app.go.assert_not_called()

    async def test_demo_charging_prefills_only_demo_code_and_submits_selected_point(self):
        app = charging_app()
        app.api.is_demo = True
        screen = await charging.build(app,public_code='CG-ONE',point_context=CONTEXT)
        self.assertEqual(fields(screen)['Código temporário do posto'].value,DEMO_PRESENCE_CODE[2:])
        self.assertIn(DEMO_PRESENCE_CODE,texts(screen))
        self.assertIn('não é necessário um equipamento real',texts(screen))
        screen = await next_charging_step(app,screen)
        screen = await next_charging_step(app,screen)
        await click(screen,'Solicitar início')(None)
        body = app.api.request.call_args.args[2]
        self.assertEqual(body['presence_code'],DEMO_PRESENCE_CODE)
        self.assertEqual(body['public_code'],'CG-ONE')

    async def test_real_charging_never_prefills_demo_code(self):
        screen = await charging.build(charging_app(),public_code='CG-ONE',point_context=CONTEXT)
        self.assertEqual(fields(screen)['Código temporário do posto'].value,'')
        self.assertNotIn('CONTA DEMO',texts(screen))
        self.assertNotIn(DEMO_PRESENCE_CODE,texts(screen))

    async def test_demo_session_poll_displays_api_telemetry_without_inventing_progress(self):
        app = HandlerApp()
        app.api.is_demo = True
        original = {**CONTEXT,'id':'demo-session','status':'charging','max_duration_minutes':10,
                    'source':'simulated','online':True,'energy_wh':'100','soc_percent':23,'cost_estimate':'0.15'}
        refreshed = {**original,'energy_wh':'4321','soc_percent':37,'cost_estimate':'6.48'}
        app.api.request.side_effect = [original,refreshed]
        screen = await charging.build(app)
        self.assertIn('Bateria simulada: 23%',texts(screen))
        await app.poll()
        self.assertIn('Bateria simulada: 37%',texts(screen))
        self.assertIn('Energia: 4,321 kWh',texts(screen))
        self.assertIn('R$ 6,48',texts(screen))
        self.assertNotIn('sessão física',texts(screen))
        app.go.assert_not_called()

    async def test_demo_terminal_status_navigation_follows_api(self):
        app = HandlerApp()
        app.api.is_demo = True
        session = {**CONTEXT,'id':'demo-session','status':'charging','max_duration_minutes':10,'online':True}
        app.api.request.side_effect = [session,{**session,'status':'completed'}]
        await charging.build(app)
        await app.poll()
        app.go.assert_awaited_once_with('charging',session_id='demo-session')

    async def test_demo_reservation_and_history_are_explicitly_simulated(self):
        app = HandlerApp()
        app.api.is_demo = True
        app.api.request.return_value = reservation()
        reservation_screen = await reservations.build(app,detail=True)
        self.assertIn('Reserva simulada confirmada',texts(reservation_screen))
        self.assertIn(DEMO_PRESENCE_CODE,texts(reservation_screen))
        app.api.request.return_value = {'items':[{**CONTEXT,'id':'demo-session','status':'completed',
                                                'max_duration_minutes':10,'soc_percent':45}],'total':1}
        history_screen = await history.build(app)
        self.assertIn('HISTÓRICO SIMULADO',texts(history_screen))
        self.assertIn('Recarga simulada concluída',texts(history_screen))
        self.assertIn('Bateria simulada: 45%',texts(history_screen))

    async def test_demo_home_labels_simulated_state_without_duplicate_banner(self):
        app = HandlerApp()
        app.api.is_demo = True
        app.profile = {'name':'Demonstração'}
        responses = {'reservations/current':None,
                     'charging-sessions/current':{'id':'demo-session','status':'charging','soc_percent':31,'online':True},
                     'stations':{'items':[],'total':0},'me/summary':{}}
        app.api.request.side_effect = lambda method,path,**kwargs: responses[path]
        screen = await home.build(app)
        self.assertNotIn('Demonstração · sem cobrança real.',texts(screen))
        self.assertIn('Recarga simulada em andamento',texts(screen))
        self.assertIn('Bateria simulada 31%',texts(screen))
        self.assertIn('Simulação local',texts(screen))


class DemoGeocodingTests(unittest.TestCase):
    def test_fixture_match_normalizes_accents_and_case(self):
        self.assertEqual(geocode_demo_address('  VILLA   LOBOS  ',DEMO_LOCATIONS),
                         (float(DEMO_LOCATIONS[0]['latitude']),float(DEMO_LOCATIONS[0]['longitude'])))

    def test_ambiguous_or_unknown_location_is_not_guessed(self):
        for query in ('São Paulo','outro lugar',''):
            self.assertIsNone(geocode_demo_address(query,DEMO_LOCATIONS))
