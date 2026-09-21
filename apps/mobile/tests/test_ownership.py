import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.navigation import form_route, parent_route
from chargegrid_app.screens import onboarding, operator, ownership
from chargegrid_app.services.ownership import claim_token
from chargegrid_app.ui.availability import point_status
from test_behavior import HandlerApp, click, descendants

TOKEN = 'a' * 43
URI = 'chargegrid://claim?token=' + TOKEN


class OwnershipTests(unittest.IsolatedAsyncioTestCase):
    def test_strict_qr_parser_rejects_public_codes_urls_and_ambiguous_tokens(self):
        self.assertEqual(claim_token(URI), TOKEN)
        self.assertEqual(claim_token('  ' + TOKEN + '\n'), TOKEN)
        for value in ['', 'CG-PAINEL-01', 'https://example.com?token=' + TOKEN,
                      URI + '&token=' + TOKEN, URI + '&other=1', URI + '#fragment',
                      URI.replace('claim?', 'claim/path?'), 'x' * 10000,
                      URI.replace('claim?', 'claim.evil?'), URI.replace('token=', 'token=%0A')]:
            with self.subTest(value=value[:40]), self.assertRaises(ApiError):
                claim_token(value)

    async def test_vendor_without_operator_permission_can_open_claim(self):
        app = HandlerApp()
        app.api.request.return_value = {'account_type': 'vendor', 'operator_enabled': False}
        screen = await operator.build(app)
        await click(screen, 'Escanear QR da tela')(None)
        app.go.assert_awaited_once_with('operator', claim=True)
        screen = await operator.build(app, claim=True)
        self.assertTrue(click(screen, 'Vincular ponto à minha conta'))

    async def test_consumer_cannot_open_claim_screen(self):
        app = HandlerApp()
        app.api.request.return_value = {'account_type': 'consumer', 'operator_enabled': False}
        screen = await operator.build(app, claim=True)
        self.assertNotIn('Vincular ponto à minha conta', [item.value for item in descendants(screen) if isinstance(item, ft.Text)])

    async def test_vendor_dashboard_exposes_the_panel_setup_flow(self):
        app = HandlerApp()
        responses = {
            'me': {'account_type': 'vendor', 'operator_enabled': True},
            'operator/summary': {'stations': 1, 'total_sessions': 0,
                                 'total_energy_wh': 0, 'total_estimated_cost': 0},
            'operator/stations': {'items': [], 'total': 0},
        }
        async def request(method, path, **kwargs):
            return responses[path]
        app.api.request.side_effect = request
        screen = await operator.build(app)
        text = ' '.join(str(item.value) for item in descendants(screen) if isinstance(item, ft.Text))
        self.assertIn('O QR aparece no visor do ESP32 ainda sem dono.', text)
        self.assertIn('Defina nome, local e tarifa', text)
        await click(screen, 'Escanear QR da tela')(None)
        app.go.assert_awaited_once_with('operator', claim=True)

    async def test_claim_sends_secret_only_on_confirmation_and_clears_after_success(self):
        app = HandlerApp()
        app.api.request.return_value = {'station_id': 'station', 'connector_id': 'connector'}
        screen = await ownership.build(app, station_id='station')
        credential = next(item for item in descendants(screen) if isinstance(item, ft.TextField))
        self.assertTrue(credential.password)
        credential.value = URI
        app.api.request.assert_not_called()
        await click(screen, 'Vincular ponto à minha conta')(None)
        app.api.request.assert_awaited_once_with('POST', 'ownership/claim', {'token': TOKEN, 'station_id': 'station'})
        self.assertEqual(credential.value, '')
        app.go.assert_awaited_once_with('operator', station_id='station', point_id='connector',
                                        onboarding=True, step=1)
        self.assertTrue(app.profile['operator_enabled'])

    async def test_failed_claim_keeps_token_for_safe_idempotent_retry(self):
        app = HandlerApp()
        app.api.request.side_effect = [ApiError('Falha de rede'),
                                       {'station_id': 'station', 'connector_id': 'connector'}]
        screen = await ownership.build(app)
        credential = next(item for item in descendants(screen) if isinstance(item, ft.TextField))
        credential.value = TOKEN
        with self.assertRaises(ApiError):
            await click(screen, 'Vincular ponto à minha conta')(None)
        self.assertEqual(credential.value, TOKEN)
        await click(screen, 'Vincular ponto à minha conta')(None)
        self.assertEqual(app.api.request.await_count, 2)
        self.assertEqual(credential.value, '')

    async def test_web_camera_explains_fallback_without_starting_camera(self):
        app = HandlerApp()
        app.page.web = True
        screen = await ownership.build(app)
        with self.assertRaisesRegex(ApiError, 'APK Android'):
            await click(screen, 'Abrir câmera para ler o QR')(None)
        app.api.request.assert_not_called()

    async def test_scan_stops_camera_then_requires_explicit_confirmation(self):
        app = HandlerApp()
        scanner = ft.Container()
        scanner.active = True
        constructor = Mock(return_value=scanner)
        with patch.dict('sys.modules', {'chargegrid_scanner': SimpleNamespace(QRScanner=constructor)}):
            screen = await ownership.build(app)
            constructor.assert_not_called()
            await click(screen, 'Abrir câmera para ler o QR')(None)
            await constructor.call_args.kwargs['on_scan'](SimpleNamespace(data=URI))
        self.assertFalse(scanner.active)
        app.api.request.assert_not_called()
        credential = next(item for item in descendants(screen) if isinstance(item, ft.TextField))
        self.assertEqual(credential.value, TOKEN)

    def test_back_routes_keep_station_but_never_secret(self):
        self.assertEqual(parent_route('operator', {'claim': True}), ('operator', {}))
        self.assertEqual(parent_route('operator', {'claim': True, 'station_id': 'station'}), ('operator', {'station_id': 'station'}))
        self.assertTrue(form_route('operator', {'claim': True}))
        route = {'station_id': 'station', 'point_id': 'point', 'onboarding': True, 'step': 3}
        self.assertEqual(parent_route('operator', route), ('operator', {**route, 'step': 2}))
        self.assertEqual(parent_route('operator', {**route, 'step': 1}), ('operator', {}))

    async def test_seller_setup_saves_each_step_before_publish_and_keeps_draft_on_error(self):
        app = HandlerApp()
        station = {
            'id': 'station', 'name': 'Rascunho', 'address': 'Em configuração',
            'latitude': 0, 'longitude': 0, 'active': False,
            'connectors': [{
                'id': 'point', 'public_code': 'CG-01', 'connector_type': 'Tipo 2',
                'power_kw': '7.4', 'price_per_kwh': '1.5', 'max_duration_minutes': 60,
                'active': False, 'online': False,
            }],
        }
        requests = []

        async def request(method, path, body=None, **kwargs):
            requests.append((method, path, body))
            if method == 'GET':
                if path == 'me':
                    return {'account_type': 'vendor', 'operator_enabled': True}
                return station
            if path == 'stations/station':
                station.update(body)
            elif path == 'connectors/point':
                station['connectors'][0].update(body)
            return station

        app.api.request.side_effect = request
        routed = await operator.build(app, station_id='station', point_id='point',
                                      onboarding=True, step=1)
        self.assertIn('Localização', [item.value for item in descendants(routed) if isinstance(item, ft.Text)])
        screen = await onboarding.build(app, 'station', 'point', step=1)
        fields = {item.label: item for item in descendants(screen) if isinstance(item, ft.TextField)}
        fields['Nome da estação'].value = 'Estação Centro'
        fields['Endereço completo'].value = 'Rua das Flores, 50, São Paulo'
        fields['Latitude'].value = 'abc'
        fields['Longitude'].value = '-46,63'
        with self.assertRaises(ApiError):
            await click(screen, 'Salvar e continuar')(None)
        self.assertTrue(fields['Latitude'].error_text)
        self.assertFalse(any(method == 'PATCH' for method, _, _ in requests))
        fields['Latitude'].value = '-23,55'
        await click(screen, 'Salvar e continuar')(None)
        self.assertEqual(requests[-1], ('PATCH', 'stations/station', {
            'name': 'Estação Centro', 'address': 'Rua das Flores, 50, São Paulo',
            'latitude': '-23.55', 'longitude': '-46.63',
        }))
        app.go.assert_awaited_with('operator', station_id='station', point_id='point', onboarding=True, step=2)

        screen = await onboarding.build(app, 'station', 'point', step=2)
        fields = {item.label: item for item in descendants(screen) if isinstance(item, ft.TextField)}
        fields['Tarifa por kWh (R$)'].value = '-1'
        with self.assertRaises(ApiError):
            await click(screen, 'Salvar e revisar')(None)
        self.assertEqual(len([r for r in requests if r[0] == 'PATCH']), 1)
        fields['Tarifa por kWh (R$)'].value = '1,80'
        await click(screen, 'Salvar e revisar')(None)
        self.assertEqual(requests[-1][1], 'connectors/point')
        self.assertEqual(requests[-1][2]['price_per_kwh'], '1.80')

        screen = await onboarding.build(app, 'station', 'point', step=3)
        self.assertFalse(station['active'])
        self.assertFalse(station['connectors'][0]['active'])
        await click(screen, 'Publicar ponto')(None)
        self.assertEqual(requests[-2:], [
            ('PATCH', 'connectors/point', {'active': True}),
            ('PATCH', 'stations/station', {'active': True}),
        ])
        app.go.assert_awaited_with('operator')

    def test_reserved_never_appears_as_occupied_during_reboot(self):
        for status in ['reserved', 'reconciling']:
            self.assertEqual(point_status({'availability_status': status, 'reserved_until': 'date'})[0], 'Reservado')
        self.assertEqual(point_status({'availability_status': 'charging'})[0], 'Em recarga')
        self.assertEqual(point_status({'availability_status': 'offline'})[0], 'Offline')
