"""Vendor stations: landing list (with "Adicionar nova estação"), station detail, data and battery limit.

The Potência screen is covered in test_station_ops.py."""
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

    async def test_list_opens_station_detail_and_offers_a_new_station(self):
        app = await demo_app()
        screen = await operator.build(app)
        copy = texts(screen)
        self.assertIn('Suas Estações', copy)
        self.assertIn('Fale com o ChatBot', copy)
        self.assertIn('Gerenciar cupons', copy)
        self.assertIn('Adicionar nova estação', copy)
        self.assertIn(operator.ADD_STATION_DEMO, copy)
        self.assertNotIn('Adicionar central simulada', copy)  # sem a linha repetida em "Mais opções"
        await press(screen, 'Marginal Pinheiros')(None)
        self.assertEqual(app.go.await_args.args[0], 'station_admin')
        await press(screen, 'Adicionar nova estação')(None)
        app.go.assert_awaited_with('operator', claim=True)
        await app.api.close()

    async def test_real_account_new_station_row_points_to_the_qr(self):
        app = HandlerApp()
        app.api.request.side_effect = [{'account_type': 'vendor', 'operator_enabled': True},
                                       {'items': [{'id': 's', 'name': 'Posto Central', 'connectors': []}], 'total': 1}]
        screen = await operator.build(app)
        self.assertIn(operator.ADD_STATION_HINT, texts(screen))
        await press(screen, 'Adicionar nova estação')(None)
        app.go.assert_awaited_with('operator', claim=True)

    async def test_new_station_flow_reuses_the_claim_onboarding_and_returns_to_the_list(self):
        from chargegrid_app.screens import onboarding
        from test_seller_flow_fixes import fields
        app = await demo_app()
        before = len((await app.api.request('GET', 'operator/stations'))['items'])
        await press(await operator.build(app), 'Adicionar nova estação')(None)
        self.assertEqual(app.go.await_args.kwargs, {'claim': True})
        first = await operator.build(app, claim=True)  # primeiro passo: o vínculo que já existe (Vincular Central)
        self.assertIn('Vincular Central', texts(first))
        self.assertIn('Será um novo local simulado', texts(first))
        await press(first, 'Adicionar central simulada')(None)
        target = app.go.await_args.kwargs
        self.assertEqual((target['onboarding'], target['step']), (True, 1))
        location = await onboarding.build(app, target['station_id'], target['point_id'], step=1)
        fields(location)['Nome da estação'].value = 'Posto Nova Estação'
        fields(location)['Endereço'].value = 'Rua Fictícia, 42, São Paulo - SP'
        await press(location, 'Salvar e continuar')(None)
        self.assertEqual(app.go.await_args.kwargs['step'], 2)
        point = await onboarding.build(app, target['station_id'], target['point_id'], step=2)
        await press(point, 'Salvar e revisar')(None)
        review = await onboarding.build(app, target['station_id'], target['point_id'], step=3)
        await press(review, 'Publicar ponto')(None)
        app.go.assert_awaited_with('operator')  # volta à lista
        listing = await operator.build(app)
        self.assertIn('Posto Nova Estação', texts(listing))
        self.assertEqual(len((await app.api.request('GET', 'operator/stations'))['items']), before + 1)
        await app.api.close()

    async def test_detail_menu_routes(self):
        app = await demo_app()
        sid = (await app.api.request('GET', 'operator/stations'))['items'][0]['id']
        screen = await station_admin.build(app, station_id=sid)
        self.assertIn('Estação CG-001', texts(screen))
        for label, expected in (('Dados da estação', ('station_admin', {'station_id': sid, 'page': 'data'})),
                                ('Carregadores', ('station_admin', {'station_id': sid, 'page': 'connectors'})),
                                ('Limite 75 kW (padrão)', ('station_admin', {'station_id': sid, 'page': 'power'})),
                                ('Tarifa base, por horário', ('tariffs', {'station_id': sid}))):
            await press(screen, label)(None)
            self.assertEqual((app.go.await_args.args[0], app.go.await_args.kwargs), expected)
        self.assertNotIn('Limite de bateria', texts(screen))  # aba removida do operador
        # Sem repetições: nada de "Configurações adicionais" nem "Pontos e equipamentos".
        data = await station_admin.build(app, station_id=sid, page='data')
        for removed in ('Configurações adicionais', 'Pontos e equipamentos', 'Latitude'):
            self.assertNotIn(removed, texts(screen) + texts(data))
        connectors = await station_admin.build(app, station_id=sid, page='connectors')
        self.assertIn('Adicionar carregador', texts(connectors))
        self.assertNotIn('Adicionar central simulada a este posto', texts(connectors))
        self.assertIn('Adicionar central simulada a este posto', texts(data))
        self.assertIn('Manutenção da central', texts(data))
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

    def test_battery_rule_validation(self):
        app = HandlerApp()
        app.api.is_demo = True
        from chargegrid_app.api_client import ApiError
        with self.assertRaises(ApiError):
            station_settings.save_battery_rule(app, 's', 140)
        self.assertEqual(station_settings.battery_rule(app, 'other')['limit'], 80)


if __name__ == '__main__':
    unittest.main()
