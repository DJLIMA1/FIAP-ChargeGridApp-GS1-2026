"""Construção das seções do dashboard com a conta demo e com uma API simulada."""
import os
import unittest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.session import Session
from chargegrid_dashboard.app import DashboardApp
from chargegrid_dashboard.state import DashboardState, bucket_label
from chargegrid_dashboard.views import VIEWS
from chargegrid_dashboard.views import sessions as sessions_view
from chargegrid_dashboard.views.amenities import amenities_payload, amenities_summary
from chargegrid_dashboard.views.stations import parse_price
from helpers import FakePage, MemoryPreferences, clickable, descendants, settle, texts

NOW = datetime(2026, 10, 13, 15, tzinfo=timezone.utc)


class StateTests(unittest.TestCase):
    def test_params_include_period_and_station(self):
        state = DashboardState(period='today', station_id='st')
        params = state.params(NOW, status='completed', q='')
        self.assertEqual(params['from'], '2026-10-13T03:00:00+00:00')
        self.assertEqual(params['to'], NOW.isoformat())
        self.assertEqual((params['station_id'], params['status']), ('st', 'completed'))
        self.assertNotIn('q', params)
        self.assertEqual(state.granularity(NOW), 'hour')
        self.assertEqual(DashboardState(period='30d').granularity(NOW), 'day')

    def test_custom_period_is_validated_before_applying(self):
        state = DashboardState()
        with self.assertRaises(ValueError):
            state.set_custom(date(2026, 10, 2), date(2026, 10, 1))
        self.assertEqual(state.period, '7d')
        state.set_custom(date(2026, 10, 1), date(2026, 10, 3))
        self.assertEqual(state.period_label(), '01/10/2026 – 03/10/2026')
        self.assertEqual(bucket_label('2026-10-01T03:00:00+00:00', 'day'), '01/10')
        self.assertEqual(bucket_label('2026-10-01T15:00:00+00:00', 'hour'), '12h')

    def test_amenities_payload_validation(self):
        rows = [{'kind': 'cafe', 'name': ' Café ', 'distance': '60'}, {'kind': 'shopping', 'name': '', 'distance': ''}]
        self.assertEqual(amenities_payload(rows), [{'kind': 'cafe', 'name': 'Café', 'distance_m': 60},
                                                   {'kind': 'shopping', 'name': ''}])
        for bad in ({'kind': 'bar'}, {'kind': 'cafe', 'distance': '1,5'}, {'kind': 'cafe', 'distance': '9000'},
                    {'kind': 'cafe', 'name': 'x' * 81}):
            with self.assertRaises(ValueError):
                amenities_payload([bad])
        with self.assertRaises(ValueError):
            amenities_payload([{'kind': 'cafe'}] * 13)
        self.assertEqual(amenities_summary([]), 'Nenhuma comodidade cadastrada')

    def test_price_parsing(self):
        self.assertEqual(parse_price('R$ 1,5'), '1.5000')
        for bad in ('abc', '-1', '10001'):
            with self.assertRaises(ValueError):
                parse_price(bad)


class DemoDashboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {'CHARGEGRID_ENABLE_DEMO': '1'})
        self.env.start()
        self.page = FakePage()
        self.dash = DashboardApp(self.page, preferences=MemoryPreferences())
        await self.dash.enter_demo()
        await settle(self.dash)

    async def asyncTearDown(self):
        self.dash.stop_view()
        await self.dash.api.close()
        self.env.stop()

    async def open(self, section, **data):
        await self.dash.open_section(section, **data)
        await settle(self.dash)
        return texts(self.dash.content)

    async def test_overview_shows_kpis_charts_ranking_and_alerts(self):
        content = texts(self.dash.content)
        for label in ('RECEITA ESTIMADA', 'ENERGIA ENTREGUE', 'SESSÕES', 'TICKET MÉDIO', 'OCUPAÇÃO',
                      'DISPONIBILIDADE', 'RESERVAS', 'NÃO COMPARECIMENTO', 'Receita por dia',
                      'Sessões por dia da semana e hora', 'Ranking de pontos', 'Dispositivo offline'):
            self.assertIn(label, content)
        shell = texts(self.dash.root)
        self.assertIn('DEMONSTRAÇÃO', shell)
        self.assertIn('Atualizado às', self.dash.status_text.value)
        self.assertEqual(self.dash.view.poll_seconds, 30)

    async def test_every_section_builds_without_errors(self):
        expected = {'stations': 'Marginal Pinheiros', 'sessions': 'Sessões de recarga', 'coupons': 'BEMVINDO10',
                    'insights': 'Gerar recomendações'}
        for section, marker in expected.items():
            content = await self.open(section)
            self.assertIn(marker, content, section)
            self.assertNotIn('Não foi possível carregar', content, section)
        self.assertEqual(set(VIEWS), {'overview', *expected})

    async def test_period_station_and_theme_controls(self):
        await self.dash.choose_period('30d')
        await settle(self.dash)
        self.assertEqual(self.dash.state.period, '30d')
        station = self.dash.stations[0]['id']
        await self.dash.choose_station(type('E', (), {'control': type('C', (), {'value': station})()})())
        await settle(self.dash)
        self.assertEqual(self.dash.state.station_id, station)
        dark = self.dash.dark_mode
        await self.dash.toggle_theme()
        await settle(self.dash)
        self.assertEqual(self.dash.preferences.dark, not dark)
        await self.dash.choose_period('custom')
        self.assertIsInstance(self.page.dialogs[-1], ft.DateRangePicker)

    async def test_sessions_filters_tabs_and_export(self):
        await self.open('sessions')
        view = self.dash.view
        view.status.value = 'failed'
        await view.filter_changed()
        self.assertIn('Falhou', texts(self.dash.content))
        self.assertEqual(self.dash.state.filters['status'], 'failed')
        with patch.object(sessions_view, 'save_bytes', AsyncMock()) as save:
            await view.export('csv')
        name, content = save.await_args.args[1:]
        self.assertTrue(name.startswith('chargegrid-sessoes-') and name.endswith('.csv'))
        self.assertTrue(content.decode('utf-8').startswith('ID da sessão'))
        await view.tab_button('reservations', 'Reservas').content.on_click(None)
        self.assertIn('Reservas', texts(self.dash.content))
        self.assertEqual(view.tab, 'reservations')
        await view.change_page(25)
        self.assertEqual(view.offset, 25)

    async def test_station_actions_use_existing_endpoints(self):
        await self.open('stations')
        point = self.dash.stations[0]['connectors'][0]
        await self.dash.view.edit_price(point)
        dialog = self.page.dialogs[-1]
        field = next(item for item in descendants(dialog.content) if isinstance(item, ft.TextField))
        field.value = '1,80'
        await clickable(dialog, 'Salvar')(None)
        stations = await self.dash.load_stations()
        self.assertEqual(stations[0]['connectors'][0]['price_per_kwh'], '1.8000')
        station = stations[0]
        await self.dash.view.set_station_active(station, False)
        self.assertFalse((await self.dash.load_stations())[0]['active'])
        content = await self.open('stations', station_id=station['id'])
        self.assertIn('Configurar Estação', content)  # formulário reaproveitado do app
        content = await self.open('stations', station_id=station['id'], connector_id=point['id'], connector=point)
        self.assertIn('Salvar alterações', content)
        await self.dash.go('operator', claim=True)
        self.assertEqual(self.dash.state.section, 'stations')

    async def test_station_amenities_editor_patches_station(self):
        await self.open('stations')
        station = self.dash.stations[0]
        await self.dash.view.edit_amenities(station)
        dialog = self.page.dialogs[-1]
        editor_rows = [row for row in descendants(dialog.content) if isinstance(row, ft.Row)
                       and any(isinstance(c, ft.Dropdown) for c in row.controls)]
        before = len(editor_rows)
        await clickable(dialog, '+ Adicionar comodidade')(None)
        dropdowns = [item for item in descendants(dialog.content) if isinstance(item, ft.Dropdown)]
        self.assertEqual(len(dropdowns), before + 1)
        dropdowns[-1].value = 'banheiro'
        fields = [item for item in descendants(dialog.content) if isinstance(item, ft.TextField)]
        fields[-2].value, fields[-1].value = 'Sanitário', '30'
        await clickable(dialog, 'Salvar')(None)
        updated = next(s for s in await self.dash.load_stations() if s['id'] == station['id'])
        self.assertEqual(updated['amenities'][-1], {'kind': 'banheiro', 'name': 'Sanitário', 'distance_m': 30})
        self.assertIn('Sanitário (30 m)', texts(self.dash.content))

    async def test_coupons_reuse_app_form(self):
        content = await self.open('coupons', create=True)
        self.assertIn('Novo cupom', content)
        await self.dash.go('coupons')
        await settle(self.dash)
        self.assertIn('Criar cupom', texts(self.dash.content))
        coupon = (await self.dash.api.request('GET', 'coupons', params={'mine': 'true'}))['items'][0]
        await self.dash.view.toggle(coupon)
        self.assertIn('Inativo', texts(self.dash.content))

    async def test_insights_demo_result_and_cache(self):
        await self.open('insights')
        await self.dash.view.generate()
        content = texts(self.dash.content)
        self.assertIn('Resumo', content)
        self.assertIn('Alto impacto', content)
        self.assertIn('dados fictícios da conta demo', content)
        self.assertIn('Gerado por', content)
        content = await self.open('insights')
        self.assertIn('Resumo', content)

    async def test_logout_returns_to_login(self):
        await self.dash.logout()
        self.assertEqual(self.dash.route, 'auth')
        self.assertFalse(getattr(self.dash.api, 'is_demo', False))
        self.assertIn('PAINEL DO PROPRIETÁRIO', texts(self.dash.root))


class FakeApi:
    def __init__(self, profile, errors=None):
        self.session = Session(access_token='token', refresh_token='refresh', expires_at=10 ** 12)
        self.profile, self.errors = profile, errors or {}

    async def request(self, method, path, body=None, **kwargs):
        if path in self.errors:
            raise self.errors[path]
        if path == 'me':
            return self.profile
        if path == 'operator/stations':
            return {'items': [], 'total': 0}
        raise ApiError('not found', 404, 'not_found')

    async def owner_insights(self, params=None):
        raise self.errors.get('insights', ApiError('Not Found', 404, 'http_error'))

    async def owner_overview(self, params=None):
        raise ApiError('Servidor indisponível', 503, 'unavailable')

    async def owner_timeseries(self, params=None):
        return {}

    async def owner_heatmap(self, params=None):
        return {}

    async def owner_alerts(self, params=None):
        return {'items': []}

    async def close(self):
        pass


class AccessAndErrorTests(unittest.IsolatedAsyncioTestCase):
    def make(self, profile, **errors):
        self.dash = DashboardApp(FakePage(), api=FakeApi(profile, errors), preferences=MemoryPreferences(False))
        return self.dash

    async def asyncTearDown(self):
        self.dash.stop_view()

    async def test_consumer_sees_restricted_notice(self):
        dash = self.make({'account_type': 'consumer', 'operator_enabled': False})
        await dash.signed_in()
        self.assertEqual(dash.route, 'restricted')
        self.assertIn('exclusivo para proprietários', texts(dash.root))

    async def test_vendor_without_equipment_is_guided_to_the_app(self):
        dash = self.make({'account_type': 'vendor', 'operator_enabled': False})
        await dash.signed_in()
        self.assertIn('Vincule seu primeiro equipamento', texts(dash.root))

    async def test_api_error_shows_retry_state(self):
        dash = self.make({'account_type': 'vendor', 'operator_enabled': True})
        await dash.signed_in()
        await settle(dash)
        self.assertIn('Servidor indisponível', texts(dash.content))
        self.assertIn('Tentar novamente', texts(dash.content))
        self.assertIn('Falha ao atualizar', dash.status_text.value)

    async def test_missing_ai_endpoint_shows_elegant_empty_state(self):
        dash = self.make({'account_type': 'vendor', 'operator_enabled': True})
        await dash.signed_in('insights')
        await settle(dash)
        await dash.view.generate()
        self.assertIn('Insights de IA indisponíveis', texts(dash.content))
        dash.api.errors['insights'] = ApiError('Tempo esgotado', 504, 'timeout')
        await dash.view.generate()
        self.assertIn('Não foi possível gerar agora', texts(dash.content))

    async def test_compact_width_collapses_sidebar(self):
        dash = self.make({'account_type': 'vendor', 'operator_enabled': True})
        dash.page.width = 800
        await dash.signed_in('insights')
        await settle(dash)
        self.assertTrue(dash.sidebar.data)
        self.assertEqual(dash.sidebar.width, 76)


class AuthScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_screen_reuses_app_auth(self):
        with patch.dict(os.environ, {'CHARGEGRID_ENABLE_DEMO': '1'}):
            dash = DashboardApp(FakePage(), preferences=MemoryPreferences())
            await dash.go('auth')
            content = texts(dash.root)
            self.assertIn('Entrar na conta demo', content)
            self.assertIn('Esqueci minha senha', content)
            await dash.go('auth', mode='forgot')
            self.assertIn('Recuperar senha', texts(dash.root))
            await dash.api.close()



class PublishedBuildTests(unittest.IsolatedAsyncioTestCase):
    """O site estático liga a demo pelo dashboard_config.json empacotado (sem variável de ambiente)."""

    async def asyncTearDown(self):
        from chargegrid_app import config
        config.set_build_options()

    async def run_main(self, config_text):
        import tempfile
        from pathlib import Path

        from chargegrid_dashboard import app as dashboard_app
        page = FakePage()
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'CHARGEGRID_ENABLE_DEMO': '0'}):
            path = Path(folder) / 'dashboard_config.json'
            if config_text is not None:
                path.write_text(config_text)
            with patch.object(dashboard_app, 'BUILD_CONFIG_FILE', path), \
                    patch.object(dashboard_app, 'dashboard_preferences', MemoryPreferences), \
                    patch.object(ft, 'SemanticsService', side_effect=RuntimeError):
                await dashboard_app.main(page)
                return texts(page.controls[0])

    async def test_packaged_config_enables_public_demo(self):
        self.assertIn('Entrar na conta demo', await self.run_main('{"demo": true}'))

    async def test_without_packaged_config_demo_stays_off(self):
        self.assertNotIn('Entrar na conta demo', await self.run_main(None))
