import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.navigation import form_route, parent_route
from chargegrid_app.screens import onboarding, operator, ownership
from chargegrid_app.services.ownership import claim_token
from chargegrid_app.ui.availability import point_status
from test_behavior import HandlerApp, click, descendants

TOKEN = 'a' * 43
URI = 'chargegrid://claim?token=' + TOKEN


def shown_texts(control):
    """Textos realmente exibidos: ignora controles ocultos e tudo dentro deles."""
    if not getattr(control, 'visible', True):
        return []
    found = [str(control.value)] if isinstance(control, ft.Text) else []
    content = getattr(control, 'content', None)
    if content is not None and not isinstance(content, str):
        found += shown_texts(content)
    for child in getattr(control, 'controls', []) or []:
        found += shown_texts(child)
    return found


def fake_scanner():
    scanner = ft.Container()
    scanner.active = True
    constructor = Mock(return_value=scanner)
    return scanner, constructor, patch.dict('sys.modules', {'chargegrid_scanner': SimpleNamespace(QRScanner=constructor)})


def back_arrow(screen):
    return next(item.on_click for item in descendants(screen) if getattr(item, 'tooltip', None) == 'Voltar')


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
        await click(screen, 'Escanear QR da central')(None)
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
            'operator/stations': {'items': [], 'total': 0},
        }
        async def request(method, path, **kwargs):
            return responses[path]
        app.api.request.side_effect = request
        screen = await operator.build(app)
        text = ' '.join(str(item.value) for item in descendants(screen) if isinstance(item, ft.Text))
        self.assertIn('O QR é exibido pela central ainda sem dono.', text)
        self.assertIn('Defina nome, local e tarifa', text)
        await click(screen, 'Escanear QR da central')(None)
        app.go.assert_awaited_once_with('operator', claim=True)

    async def test_claim_sends_secret_only_on_confirmation_and_clears_after_success(self):
        app = HandlerApp()
        app.api.request.side_effect = [
            {'id': 'station', 'name': 'Posto Central', 'address': 'Rua Central, 100'},
            {'station_id': 'station', 'connector_id': 'connector'},
        ]
        screen = await ownership.build(app, station_id='station')
        credential = next(item for item in descendants(screen) if isinstance(item, ft.TextField))
        self.assertTrue(credential.password)
        credential.value = URI
        app.api.request.assert_awaited_once_with('GET', 'stations/station')
        await click(screen, 'Vincular ponto à minha conta')(None)
        self.assertEqual(app.api.request.await_count, 2)
        app.api.request.assert_awaited_with('POST', 'ownership/claim', {'token': TOKEN, 'station_id': 'station'})
        self.assertEqual(credential.value, '')
        app.go.assert_awaited_once_with('operator', station_id='station', point_id='connector',
                                        onboarding=True, step=2, existing_station=True)
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
        self.assertNotIn('Vincular ponto à minha conta', shown_texts(screen))
        with self.assertRaisesRegex(ApiError, 'APK Android'):
            await click(screen, 'Escanear QR Code')(None)
        app.api.request.assert_not_called()
        # Sem câmera no navegador, colar o código vira o caminho (aberto sozinho).
        self.assertIn('Vincular ponto à minha conta', shown_texts(screen))
        credential = next(item for item in descendants(screen) if isinstance(item, ft.TextField))
        self.assertTrue(credential.visible and credential.password)

    async def test_idle_screen_has_one_action_and_paste_is_a_discreet_fallback(self):
        app = HandlerApp()
        screen = await ownership.build(app)
        text = shown_texts(screen)
        self.assertIn('Escanear QR Code', text)
        self.assertIn('Não consegue escanear? Colar código do QR', text)
        self.assertNotIn('Vincular ponto à minha conta', text)
        self.assertNotIn('Inserir o Código Privado do QR', '\n'.join(str(c.value) for c in descendants(screen)
                                                                    if isinstance(c, ft.Text)))
        await click(screen, 'Não consegue escanear? Colar código do QR')(None)
        text = shown_texts(screen)
        self.assertIn('Vincular ponto à minha conta', text)
        self.assertNotIn('Não consegue escanear? Colar código do QR', text)
        app.api.request.assert_not_called()

    async def test_camera_takes_the_place_of_the_content_and_cancel_restores_it(self):
        app = HandlerApp()
        app.back = AsyncMock()
        scanner, constructor, modules = fake_scanner()
        with modules:
            screen = await ownership.build(app)
            intro = 'Depois informe nome, endereço e tarifa. O ponto só aparece aos motoristas quando você publicar.'
            for close in (lambda: click(screen, 'Cancelar')(None), lambda: back_arrow(screen)(None)):
                await click(screen, 'Escanear QR Code')(None)
                text = shown_texts(screen)
                self.assertIn('Aponte a câmera para o QR exibido na tela da central.', text)
                self.assertIn('Cancelar', text)
                self.assertNotIn(intro, text)
                self.assertNotIn('Escanear QR Code', text)
                self.assertTrue(any(item is scanner for item in descendants(screen)))
                await close()
                text = shown_texts(screen)
                self.assertFalse(scanner.active)
                self.assertIn(intro, text)
                self.assertIn('Escanear QR Code', text)
                self.assertNotIn('Cancelar', text)
                scanner.active = True
        app.back.assert_not_awaited()  # o "<" com a câmera aberta só fecha a câmera
        await back_arrow(screen)(None)
        app.back.assert_awaited_once()
        app.api.request.assert_not_called()

    async def test_camera_error_opens_the_paste_fallback(self):
        app = HandlerApp()
        scanner, constructor, modules = fake_scanner()
        with modules:
            screen = await ownership.build(app)
            await click(screen, 'Escanear QR Code')(None)
            await constructor.call_args.kwargs['on_error'](SimpleNamespace(data='permission_denied'))
        self.assertFalse(scanner.active)
        self.assertIn('Não foi possível abrir a câmera', app.notices[-1])
        text = shown_texts(screen)
        self.assertIn('Vincular ponto à minha conta', text)
        self.assertNotIn('Aponte a câmera para o QR exibido na tela da central.', text)

    async def test_missing_scanner_opens_the_paste_fallback(self):
        app = HandlerApp()
        with patch.dict('sys.modules', {'chargegrid_scanner': None}):
            screen = await ownership.build(app)
            with self.assertRaisesRegex(ApiError, 'Leitor não instalado'):
                await click(screen, 'Escanear QR Code')(None)
        self.assertIn('Vincular ponto à minha conta', shown_texts(screen))

    async def test_scan_param_opens_camera_on_entry_or_fallback_without_camera(self):
        app = HandlerApp()
        scanner, constructor, modules = fake_scanner()
        with modules:
            screen = await ownership.build(app, scan=True)
        constructor.assert_called_once()
        text = shown_texts(screen)
        self.assertIn('Aponte a câmera para o QR exibido na tela da central.', text)
        self.assertNotIn('Escanear QR Code', text)
        app.api.request.assert_not_called()

        web = HandlerApp()
        web.page.web = True
        screen = await ownership.build(web, scan=True)
        text = shown_texts(screen)
        self.assertIn(ownership.WEB_CAMERA, text)  # motivo na própria tela, sem erro ao abrir
        self.assertIn('Vincular ponto à minha conta', text)
        self.assertNotIn('Aponte a câmera para o QR exibido na tela da central.', text)

    async def test_operator_route_passes_scan_to_the_claim_screen(self):
        app = HandlerApp()
        app.api.request.return_value = {'account_type': 'vendor', 'operator_enabled': True}
        with patch.object(ownership, 'build', AsyncMock(return_value='claim')) as build:
            self.assertEqual(await operator.build(app, claim=True, scan=True), 'claim')
        build.assert_awaited_once_with(app, station_id=None, show_real=False, scan=True)

    async def test_scan_stops_camera_then_requires_explicit_confirmation(self):
        app = HandlerApp()
        scanner = ft.Container()
        scanner.active = True
        constructor = Mock(return_value=scanner)
        with patch.dict('sys.modules', {'chargegrid_scanner': SimpleNamespace(QRScanner=constructor)}):
            screen = await ownership.build(app)
            constructor.assert_not_called()
            await click(screen, 'Escanear QR Code')(None)
            await constructor.call_args.kwargs['on_scan'](SimpleNamespace(data=URI))
        self.assertFalse(scanner.active)
        app.api.request.assert_not_called()
        credential = next(item for item in descendants(screen) if isinstance(item, ft.TextField))
        self.assertEqual(credential.value, TOKEN)
        text = shown_texts(screen)
        self.assertIn('Vincular ponto à minha conta', text)
        self.assertIn('Escanear novamente', text)
        self.assertTrue(any(line.startswith('QR reconhecido') for line in text))
        self.assertNotIn('Aponte a câmera para o QR exibido na tela da central.', text)
        await click(screen, 'Vincular ponto à minha conta')(None)
        app.api.request.assert_awaited_once_with('POST', 'ownership/claim', {'token': TOKEN})

    def test_back_routes_keep_station_but_never_secret(self):
        self.assertEqual(parent_route('operator', {'claim': True}), ('operator', {}))
        self.assertEqual(parent_route('operator', {'claim': True, 'station_id': 'station'}),
                         ('station_admin', {'station_id': 'station', 'page': 'connectors'}))
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
        suggestions = {'items': []}

        async def request(method, path, body=None, **kwargs):
            requests.append((method, path, body))
            if method == 'GET':
                if path == 'me':
                    return {'account_type': 'vendor', 'operator_enabled': True}
                if path == 'geo/address-suggestions':
                    return suggestions
                return station
            if path == 'stations/station':
                station.update(body)
            elif path == 'connectors/point':
                station['connectors'][0].update(body)
            return station

        app.api.request.side_effect = request
        routed = await operator.build(app, station_id='station', point_id='point',
                                      onboarding=True, step=1)
        self.assertIn('Etapa 1 de 3 · Localização', [item.value for item in descendants(routed) if isinstance(item, ft.Text)])
        screen = await onboarding.build(app, 'station', 'point', step=1)
        fields = {(item.label or item.data): item for item in descendants(screen) if isinstance(item, ft.TextField)}
        fields['Nome da estação'].value = 'Estação Centro'
        fields['Endereço'].value = 'Rua das Flores, 50, São Paulo'
        self.assertNotIn('Latitude', fields)  # a localização vem do endereço
        with self.assertRaises(ApiError):  # endereço não encontrado: não salva coordenadas inventadas
            await click(screen, 'Salvar e continuar')(None)
        self.assertIn('Não encontramos este endereço', fields['Endereço'].error_text)
        self.assertFalse(any(method == 'PATCH' for method, _, _ in requests))
        suggestions['items'] = [{'label': 'Rua das Flores, 50, Centro, São Paulo - SP',
                                 'latitude': -23.55, 'longitude': -46.63}]
        await click(screen, 'Salvar e continuar')(None)
        self.assertEqual(requests[-1], ('PATCH', 'stations/station', {
            'name': 'Estação Centro', 'address': 'Rua das Flores, 50, São Paulo',
            'latitude': '-23.55', 'longitude': '-46.63',
        }))
        app.go.assert_awaited_with('operator', station_id='station', point_id='point', onboarding=True, step=2)

        screen = await onboarding.build(app, 'station', 'point', step=2)
        fields = {(item.label or item.data): item for item in descendants(screen) if isinstance(item, ft.TextField)}
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
