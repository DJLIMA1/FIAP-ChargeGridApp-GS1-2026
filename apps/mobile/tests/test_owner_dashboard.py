"""Código compartilhado com o dashboard web: cliente, demo e componentes visuais."""
import csv
import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import flet as ft
import httpx

from chargegrid_app.api_client import ApiClient, ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.owner_api import clean_params
from chargegrid_app.ui import charts, kpi, tables
from chargegrid_core import analytics
from test_api_client import tokens
from test_behavior import descendants

START = datetime(2026, 10, 13, 15, tzinfo=timezone.utc)


def texts(control):
    return ' '.join(str(item.value) for item in descendants(control) if isinstance(item, ft.Text) and item.value)


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class OwnerApiClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await self.client.close()

    async def test_owner_methods_clean_filters_and_download_refreshes_token(self):
        calls = []

        def handler(request):
            calls.append((request.url.path, dict(request.url.params), request.headers.get('authorization')))
            if request.url.path.endswith('/auth/refresh'):
                return httpx.Response(200, json=tokens('access-2', 'refresh-2'))
            if request.url.path.endswith('.csv'):
                if request.headers['authorization'] == 'Bearer access-1':
                    return httpx.Response(401, json={'error': {'code': 'unauthorized', 'message': 'expirado'}})
                return httpx.Response(200, content=b'ID,Posto\r\n', headers={'content-type': 'text/csv'})
            return httpx.Response(200, json={'kpis': {}})

        self.client = ApiClient('https://api.example.test/v1', httpx.MockTransport(handler))
        self.client.session.update(tokens())
        await self.client.owner_overview({'from': 'a', 'station_id': None, 'q': ''})
        self.assertEqual(calls[0][:2], ('/v1/owner/overview', {'from': 'a'}))
        content = await self.client.owner_export('sessions', 'csv', {'status': 'completed'})
        self.assertEqual(content, b'ID,Posto\r\n')
        self.assertEqual([path for path, _, _ in calls[1:]],
                         ['/v1/owner/export/sessions.csv', '/v1/auth/refresh', '/v1/owner/export/sessions.csv'])
        with self.assertRaises(ValueError):
            await self.client.owner_export('users', 'csv')
        with self.assertRaises(ValueError):
            await self.client.owner_get('secrets')

    async def test_download_reports_api_error_message(self):
        def handler(request):
            return httpx.Response(413, json={'error': {'code': 'export_too_large', 'message': 'Reduza o período'}})

        self.client = ApiClient('https://api.example.test/v1', httpx.MockTransport(handler))
        self.client.session.update(tokens())
        with self.assertRaises(ApiError) as raised:
            await self.client.owner_export('reservations', 'json')
        self.assertEqual((raised.exception.status, raised.exception.code), (413, 'export_too_large'))
        self.assertEqual(str(raised.exception), 'Reduza o período')

    async def test_insights_posts_to_ai_endpoint(self):
        seen = []

        def handler(request):
            seen.append((request.method, request.url.path, json.loads(request.content)))
            return httpx.Response(200, json={'summary': 'ok', 'recommendations': []})

        self.client = ApiClient('https://api.example.test/v1', httpx.MockTransport(handler))
        self.client.session.update(tokens())
        await self.client.owner_insights({'from': 'x', 'station_id': None})
        self.assertEqual(seen, [('POST', '/v1/ai/owner-insights', {'from': 'x'})])


class DemoOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.client = DemoApi(clock=self.clock, start_at=START)
        await self.client.login(DEMO_EMAIL, DEMO_PASSWORD)

    async def asyncTearDown(self):
        await self.client.close()

    async def test_overview_is_consistent_with_tables_and_series(self):
        params = {'from': (START - timedelta(days=30)).isoformat(), 'to': START.isoformat()}
        overview = await self.client.owner_overview(params)
        kpis = overview['kpis']
        self.assertGreater(kpis['sessions'], 50)
        self.assertEqual((kpis['points'], kpis['points_online'], kpis['uptime_percent']), (3, 2, '66.7'))
        series = await self.client.owner_timeseries({**params, 'granularity': 'day'})
        self.assertEqual(sum(series['series']['sessions']), kpis['sessions'])
        # Cada balde é arredondado a centavos; a soma pode diferir por arredondamento.
        drift = abs(sum(Decimal(v) for v in series['series']['revenue']) - Decimal(kpis['revenue']))
        self.assertLessEqual(drift, Decimal('0.01') * len(series['buckets']))
        ranking_revenue = sum(Decimal(item['revenue']) for item in overview['ranking'])
        self.assertLessEqual(abs(ranking_revenue - Decimal(kpis['revenue'])), Decimal('0.05'))
        heat = await self.client.owner_heatmap(params)
        self.assertEqual(len(heat['cells']), 7)
        self.assertTrue(heat['peak_hours'])
        reservations = await self.client.owner_reservations({**params, 'status': 'expired', 'limit': 100})
        self.assertEqual(reservations['total'], kpis['no_shows'])

    async def test_history_is_deterministic_per_login(self):
        first = await self.client.owner_overview({})
        other = DemoApi(clock=FakeClock(), start_at=START)
        await other.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.assertEqual((await other.owner_overview({}))['kpis'], first['kpis'])
        await other.close()

    async def test_tables_filter_search_paginate_and_export(self):
        page = await self.client.owner_sessions({'limit': 5, 'q': 'demo-11'})
        self.assertEqual(len(page['items']), 5)
        self.assertTrue(all(item['public_code'] == 'DEMO-11' for item in page['items']))
        self.assertNotIn('user_id', page['items'][0])
        failed = await self.client.owner_sessions({'status': 'failed', 'limit': 100})
        self.assertTrue(all(item['status'] == 'failed' for item in failed['items']))
        content = await self.client.owner_export('sessions', 'csv', {'status': 'failed'})
        rows = list(csv.reader(io.StringIO(content.decode('utf-8'))))
        self.assertEqual(rows[0][0], 'ID da sessão')
        self.assertEqual(len(rows) - 1, failed['total'])
        envelope = json.loads(await self.client.owner_export('reservations', 'json', {}))
        self.assertEqual(envelope['dataset'], 'reservations')
        self.assertIn('fictícios', envelope['notes'])
        with self.assertRaises(ApiError) as raised:
            await self.client.owner_sessions({'status': 'bogus'})
        self.assertEqual(raised.exception.code, 'invalid_status')

    async def test_scope_validation_and_operator_requirement(self):
        with self.assertRaises(ApiError) as raised:
            await self.client.owner_overview({'station_id': 'outro-posto'})
        self.assertEqual(raised.exception.status, 404)
        with self.assertRaises(ApiError) as raised:
            await self.client.owner_overview({'from': START.isoformat(), 'to': (START - timedelta(days=1)).isoformat()})
        self.assertEqual(raised.exception.code, 'invalid_period')
        claim = await self.client.request('POST', 'ownership/claim', {'token': self.client.new_claim_token()})
        inactive = await self.client.request('GET', f"stations/{claim['station_id']}")
        self.assertFalse(inactive['active'])
        scoped = await self.client.owner_overview({'station_id': inactive['id']})
        self.assertEqual(scoped['kpis']['sessions'], 0)
        self.client._profile['operator_enabled'] = False
        with self.assertRaises(ApiError) as raised:
            await self.client.owner_alerts()
        self.assertEqual(raised.exception.status, 403)

    async def test_alerts_live_and_new_demo_session_are_reflected(self):
        alerts = (await self.client.owner_alerts())['items']
        self.assertEqual({alert['kind'] for alert in alerts}, {'device_offline', 'command_failed'})
        live = (await self.client.owner_live())['items']
        self.assertEqual([item['availability_status'] for item in live], ['available', 'available', 'offline'])
        before = (await self.client.owner_overview({'to': (START + timedelta(hours=2)).isoformat()}))['kpis']
        await self.client.request('POST', 'charging-sessions', {'presence_code': '#F12345', 'public_code': 'DEMO-11',
                                                                'max_duration_minutes': 5}, key='k')
        self.clock.value = 3
        charging = next(item for item in (await self.client.owner_live())['items'] if item['public_code'] == 'DEMO-11')
        self.assertEqual(charging['availability_status'], 'charging')
        self.assertEqual(charging['session']['power_w'], '60000')
        self.clock.value = 400
        after = (await self.client.owner_overview({'to': (START + timedelta(hours=2)).isoformat()}))['kpis']
        self.assertEqual(after['sessions'], before['sessions'] + 1)

    async def test_insights_follow_the_ai_contract(self):
        result = await self.client.owner_insights({})
        self.assertEqual(set(result), {'summary', 'recommendations', 'generated_at', 'model'})
        self.assertTrue(result['recommendations'])
        for item in result['recommendations']:
            self.assertEqual(set(item), {'title', 'detail', 'impact', 'kind'})
            self.assertIn(item['impact'], ('high', 'medium', 'low'))


class SharedComponentTests(unittest.TestCase):
    def test_kpi_cards_have_accessible_labels_and_responsive_columns(self):
        grid = kpi.kpi_grid([kpi.kpi_card('Receita', 'R$ 10,00', hint='Período')])
        card = grid.controls[0]
        self.assertEqual(card.label, 'Receita: R$ 10,00. Período')
        self.assertEqual(card.col, {'xs': 6, 'md': 4, 'lg': 3})
        self.assertEqual(kpi.point_status_badge({'availability_status': 'offline'}).content.value, 'Offline')
        self.assertIn('Crítico', texts(kpi.alert_tile({'severity': 'critical', 'title': 'Offline', 'detail': 'x'})))
        self.assertIn('Tentar novamente', texts(kpi.error_state('falhou', lambda: None)))

    def test_charts_handle_empty_and_summarize_data(self):
        self.assertIn('Sem dados', texts(charts.bar_chart([0, 0], ['a', 'b'])))
        chart = charts.bar_chart(['1', '3'], ['seg', 'ter'], title='Receita')
        summary = next(item for item in descendants(chart) if isinstance(item, ft.Semantics))
        self.assertIn('máximo 3 em ter', summary.label)
        heat = charts.heatmap([[0, 2], [1, 0]], ['Seg', 'Ter'], ['00', '01'])
        self.assertIn('3', heat.label)
        ranking = charts.ranking_bars([{'n': 'A', 'v': '2'}], value_key='v', label_key='n')
        self.assertIn('1. A', texts(ranking))
        self.assertIsInstance(charts.sparkline([1, 2, 3]), ft.Semantics)

    def test_tables_pagination_and_period_selector(self):
        table = tables.data_table([('a', 'A')], [{'a': None}])
        self.assertEqual(table.controls[0].rows[0].cells[0].content.value, '—')
        self.assertIn('Nenhum', texts(tables.data_table([('a', 'A')], [])))
        footer = tables.pagination(30, 10, 10, None)
        self.assertIn('11–20 de 30', texts(footer))
        selector = tables.period_selector('7d', None)
        selected = [item.label for item in selector.controls if item.selected]
        self.assertEqual(selected, ['Período: 7 dias'])
        badge = tables.cell_badge(kpi.point_status_badge({'availability_status': 'available'}))
        self.assertEqual(badge.height, 26)

    def test_clean_params(self):
        self.assertEqual(clean_params({'a': 0, 'b': None, 'c': '', 'd': []}), {'a': 0})

    def test_core_csv_matches_demo_columns(self):
        self.assertEqual([key for key, _ in analytics.SESSION_EXPORT_COLUMNS][0], 'id')
