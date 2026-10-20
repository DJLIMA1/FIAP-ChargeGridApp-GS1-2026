"""Vendor stations: landing list, station detail, data, power limits (station + connectors) and battery limit."""
import unittest
from types import SimpleNamespace

import flet as ft

from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import operator, station_admin
from chargegrid_app.services import station_settings
from test_behavior import HandlerApp, descendants


def texts(screen):
    return ' '.join(str(c.value) for c in descendants(screen) if isinstance(c, ft.Text))


def press(screen, label):
    """on_click of the container whose subtree shows ``label`` (innermost match)."""
    best = None
    for item in descendants(screen):
        if getattr(item, 'on_click', None) and isinstance(item, ft.Container) and label in texts(item):
            best = item
    return best.on_click


async def demo_app():
    app = HandlerApp()
    app.back = lambda event=None: None
    app.api = DemoApi()
    await app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
    app.profile = await app.api.request('GET', 'me')
    app.api.is_demo = True
    return app


class StationAdminTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        station_settings.reset_demo()

    async def test_list_opens_station_detail_and_keeps_operator_actions(self):
        app = await demo_app()
        screen = await operator.build(app)
        copy = texts(screen)
        self.assertIn('Suas Estações', copy)
        self.assertIn('Fale com o ChatBot', copy)
        self.assertIn('Gerenciar cupons', copy)
        self.assertIn('Adicionar equipamento simulado', copy)
        await press(screen, 'Marginal Pinheiros')(None)
        self.assertEqual(app.go.await_args.args[0], 'station_admin')
        await press(screen, 'Adicionar equipamento simulado')(None)
        app.go.assert_awaited_with('operator', claim=True)
        await app.api.close()

    async def test_detail_menu_routes(self):
        app = await demo_app()
        sid = (await app.api.request('GET', 'operator/stations'))['items'][0]['id']
        screen = await station_admin.build(app, station_id=sid)
        self.assertIn('Estação CG-001', texts(screen))
        for label, expected in (('Dados da estação', ('station_admin', {'station_id': sid, 'page': 'data'})),
                                ('Conectores', ('station_admin', {'station_id': sid, 'page': 'connectors'})),
                                ('Potência por conector', ('station_admin', {'station_id': sid, 'page': 'power'})),
                                ('Tarifa base, por horário', ('tariffs', {'station_id': sid}))):
            await press(screen, label)(None)
            self.assertEqual((app.go.await_args.args[0], app.go.await_args.kwargs), expected)
        self.assertNotIn('Limite de bateria', texts(screen))  # aba removida do operador
        # Sem repetições: nada de "Configurações adicionais" nem "Pontos e equipamentos".
        data = await station_admin.build(app, station_id=sid, page='data')
        for removed in ('Configurações adicionais', 'Pontos e equipamentos', 'Latitude'):
            self.assertNotIn(removed, texts(screen) + texts(data))
        connectors = await station_admin.build(app, station_id=sid, page='connectors')
        self.assertIn('Adicionar ponto simulado a este posto', texts(connectors))
        self.assertIn('A tarifa fica em Tarifa.', texts(connectors))
        await app.api.close()

    async def test_data_page_patches_name_address_and_status(self):
        app = await demo_app()
        sid = (await app.api.request('GET', 'operator/stations'))['items'][0]['id']
        screen = await station_admin.build(app, station_id=sid, page='data')
        fields = [c for c in descendants(screen) if isinstance(c, ft.TextField)]
        self.assertEqual(fields[2].value, 'CG-001')
        self.assertTrue(fields[2].read_only)
        fields[0].value = 'Marginal Pinheiros'
        await fields[0].on_blur(SimpleNamespace(control=fields[0]))
        self.assertEqual((await app.api.request('GET', f'stations/{sid}'))['name'], 'Marginal Pinheiros')
        await press(screen, 'Inativa')(None)
        self.assertFalse((await app.api.request('GET', f'stations/{sid}'))['active'])
        await app.api.close()

    async def _power_screen(self):
        app = await demo_app()
        station = (await app.api.request('GET', 'operator/stations'))['items'][0]
        screen = await station_admin.build(app, station_id=station['id'], page='power')
        sliders = [c for c in descendants(screen) if isinstance(c, ft.Slider)]
        return app, station, screen, sliders

    async def test_power_page_shows_rating_energy_and_saves_limits(self):
        app, station, screen, sliders = await self._power_screen()
        copy = texts(screen)
        self.assertIn('Limite do posto', copy)
        self.assertIn('Potência máxima do carregador: 60 kW', copy)
        self.assertIn('Energia entregue: 2,4 kWh', copy)
        self.assertIn('Alocado: 104 de 104 kW', copy)
        self.assertEqual([s.data for s in sliders], ['station_power'] + ['power'] * len(station['connectors']))
        # Lowering the station cap below the sum shows the proportional share immediately.
        sliders[0].value = 80.0
        await sliders[0].on_change(SimpleNamespace(control=sliders[0]))
        copy = texts(screen)
        self.assertIn('Efetivo: 46,1 kW (limitado pelo posto)', copy)
        self.assertIn('Alocado: 79,9 de 80 kW', copy)
        sliders[1].value = 40.0
        await sliders[1].on_change(SimpleNamespace(control=sliders[1]))
        self.assertIn('Efetivo: 38 kW (limitado pelo posto)', texts(screen))
        await press(screen, 'Salvar limites')(None)
        saved = await app.api.request('GET', f'stations/{station["id"]}')
        self.assertEqual(float(saved['max_power_kw']), 80.0)
        self.assertEqual(float(saved['connectors'][0]['power_limit_kw']), 40.0)
        self.assertEqual(float(saved['connectors'][0]['power_kw']), 60.0)  # rating untouched
        self.assertEqual(app.notices[-1], 'Limites de potência salvos.')
        detail = await station_admin.build(app, station_id=station['id'])
        self.assertIn('Limite do posto: 80 kW · CCS2: 40 kW · Tipo 2: 22 kW', texts(detail))
        # Restore defaults clears every limit after saving.
        screen = await station_admin.build(app, station_id=station['id'], page='power')
        await press(screen, 'Restaurar padrão')(None)
        await press(screen, 'Salvar limites')(None)
        saved = await app.api.request('GET', f'stations/{station["id"]}')
        self.assertIsNone(saved['max_power_kw'])
        self.assertTrue(all(p['power_limit_kw'] is None for p in saved['connectors']))
        await app.api.close()

    async def test_power_page_notify_toggle_and_partial_failure(self):
        app, station, screen, sliders = await self._power_screen()
        switch = next(c for c in descendants(screen) if isinstance(c, ft.Switch) and c.data == 'power_notify')
        switch.value = True
        await switch.on_change(SimpleNamespace(control=switch))
        sliders[2].value = 11.0
        await sliders[2].on_change(SimpleNamespace(control=sliders[2]))
        original = app.api.request

        async def flaky(method, path, body=None, **kwargs):
            if method == 'PATCH' and path.startswith('connectors/'):
                from chargegrid_app.api_client import ApiError
                raise ApiError('Sem conexão.', 503, 'network')
            return await original(method, path, body, **kwargs)
        app.api.request = flaky
        await press(screen, 'Salvar limites')(None)
        message = app.notices[-1]
        self.assertIn('Salvo: limite do posto.', message)
        self.assertIn('Não salvo: Tipo 2 - Conector 02: Sem conexão.', message)
        app.api.request = original
        self.assertTrue((await app.api.request('GET', f'stations/{station["id"]}'))['power_limit_notify'])
        # Retrying sends only what is still pending.
        await press(screen, 'Salvar limites')(None)
        saved = await app.api.request('GET', f'stations/{station["id"]}')
        self.assertEqual(float(saved['connectors'][1]['power_limit_kw']), 11.0)
        await app.api.close()

    def test_battery_rule_validation(self):
        app = HandlerApp()
        app.api.is_demo = True
        from chargegrid_app.api_client import ApiError
        with self.assertRaises(ApiError):
            station_settings.save_battery_rule(app, 's', 140)
        self.assertEqual(station_settings.battery_rule(app, 'other')['limit'], 80)


if __name__ == '__main__':
    unittest.main()
