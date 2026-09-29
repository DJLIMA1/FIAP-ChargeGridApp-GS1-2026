"""Freshness and journey claims stay honest across failure and recovery."""
import asyncio
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.app import ChargeGridApp
from chargegrid_app.navigation import parent_route
from chargegrid_app.screens import charging
from chargegrid_app.services.planning import estimate_text
from chargegrid_app.session import Session
from chargegrid_app.ui.point_summary import journey_summary
from test_behavior import click, descendants
from test_charging_wizard import (
    CONTEXT,
    WizardApp,
    fields,
    next_screen,
    review_screen,
    texts,
)


class FreshnessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.page = SimpleNamespace(width=390, window=SimpleNamespace(), views=[SimpleNamespace()],
                                    add=Mock(), update=Mock(), show_dialog=Mock())
        self.client = SimpleNamespace(session=Session(), request=AsyncMock(), close=AsyncMock(),
                                      operation_keys={}, charging_operation_sessions={},
                                      last_session_id=None, last_reservation_id=None)
        with patch('chargegrid_app.app.ApiClient', return_value=self.client), patch('chargegrid_app.app.Preferences') as preferences:
            preferences.return_value.load.return_value = True
            self.app = ChargeGridApp(self.page)
        self.client.session.access_token = 'test-session'
        self.app.generation = 1

    async def asyncTearDown(self):
        self.app.cancel_screen()
        await asyncio.sleep(0)

    async def test_failed_query_retains_receipt_time_and_retry_clears_warning(self):
        self.app.poll_callback = AsyncMock(side_effect=[ApiError('Rede indisponível'), None])
        self.app.mark_refresh(True)
        last_success = self.app.last_refresh_at
        await self.app.retry_refresh()
        self.assertEqual(self.app.last_refresh_at, last_success)
        self.assertTrue(self.app.refresh_failed)
        self.assertTrue(self.app.freshness.visible)
        self.assertIn('último estado conhecido', self.app.freshness_text.value)
        self.assertEqual(self.app.freshness_retry.content.value, 'Tentar novamente')
        await self.app.retry_refresh()
        self.assertFalse(self.app.refresh_failed)
        self.assertIn('Consulta atualizada', self.app.freshness_text.value)
        self.assertNotIn('último estado', self.app.freshness_text.value)
        self.assertFalse(self.app.freshness.visible)
        self.assertTrue(self.app.freshness.live_region)
        self.assertFalse(self.app.freshness_retry.disabled)

    async def test_old_response_cannot_mark_another_screen_fresh(self):
        async def navigate_during_request():
            self.app.generation += 1
            self.app.freshness.visible = False
        self.app.poll_callback = navigate_during_request
        await self.app.retry_refresh()
        self.assertIsNone(self.app.last_refresh_at)
        self.assertFalse(self.app.freshness.visible)

    async def test_retry_is_serialized_and_does_not_interrupt_a_mutation(self):
        self.app.poll_callback = AsyncMock()
        self.app.active_actions.add('pending-start')
        await self.app.retry_refresh()
        self.app.poll_callback.assert_not_awaited()
        self.app.active_actions.clear()
        self.app.refresh_in_progress = True
        await self.app.retry_refresh()
        self.app.poll_callback.assert_not_awaited()

    async def test_navigation_cancels_manual_retry_before_it_mutates_old_screen(self):
        entered = asyncio.Event()
        late_update = Mock()
        async def slow_query():
            entered.set()
            await asyncio.Future()
            late_update()
        self.app.poll_callback = slow_query
        task = asyncio.create_task(self.app.retry_refresh())
        await entered.wait()
        with patch.dict('chargegrid_app.app.SCREENS', {'home': AsyncMock(return_value=ft.Column())}):
            await self.app.go('home')
        with self.assertRaises(asyncio.CancelledError):
            await task
        late_update.assert_not_called()
        self.assertFalse(self.app.refresh_in_progress)
        self.assertNotIn(task, self.app.tasks)

    async def test_poll_reports_failure_then_recovery_without_changing_session(self):
        self.app.route = 'charging'
        self.app.charging_draft = {'uncertain': True, 'key': 'same-request'}
        calls = 0
        async def query():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ApiError('Rede indisponível')
            if calls == 2:
                self.assertTrue(self.app.refresh_failed)
            else:
                self.assertFalse(self.app.refresh_failed)
                self.app.generation += 1
        with patch('chargegrid_app.app.asyncio.sleep', new=AsyncMock()):
            await self.app.poll(query, 5, 1)
        self.assertEqual(self.app.charging_draft, {'uncertain': True, 'key': 'same-request'})

    async def test_selected_tab_is_exposed_and_uses_native_keyboard_button(self):
        with patch.dict('chargegrid_app.app.SCREENS', {'home': AsyncMock(return_value=ft.Column())}):
            await self.app.go('home')
        tabs = [item for item in descendants(self.app.scene) if isinstance(item, ft.Semantics)
                and item.selected is not None]
        self.assertEqual(len(tabs), 5)
        self.assertEqual(sum(bool(item.selected) for item in tabs), 1)
        self.assertTrue(all(isinstance(item.content, ft.TextButton) for item in tabs))
        self.assertEqual(next(item.content.tooltip for item in tabs if item.selected), 'Início')


class JourneyClaimTests(unittest.TestCase):
    def test_no_ack_does_not_claim_confirmed_start_even_when_request_has_timestamp(self):
        screen = journey_summary({'status': 'starting', 'created_at': '2026-09-29T12:00:00Z'})
        self.assertIn('aguardando confirmação', texts(screen))
        self.assertNotIn('Início confirmado pelo', texts(screen))
        self.assertNotIn('em andamento', texts(screen))

    def test_failed_start_has_no_fabricated_confirmation_history(self):
        screen = journey_summary({'status': 'failed', 'ended_at': '2026-09-29T12:01:00Z'})
        self.assertIn('Sem registro de início confirmado', texts(screen))
        self.assertNotIn('Início confirmado pelo', texts(screen))

    def test_offline_and_stop_pending_are_not_presented_as_physical_stop(self):
        screen = journey_summary({'status': 'stopping', 'online': False,
                                  'started_at': '2026-09-29T12:00:00Z'})
        self.assertIn('aguardando confirmação', texts(screen))
        self.assertIn('último estado recebido', texts(screen))
        self.assertNotIn('Sessão encerrada', texts(screen))

    def test_reservation_cancellation_does_not_invent_prior_confirmation(self):
        screen = journey_summary({'status': 'cancelling'}, reservation=True)
        self.assertIn('aguardando liberação', texts(screen))
        self.assertNotIn('Confirmada pelo', texts(screen))


class PlanningHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def test_back_from_presence_preserves_location_filters_and_plan(self):
        app = WizardApp()
        search = {'lat': -23.5, 'lng': -46.6, 'query': 'Centro', 'sort': 'price',
                  'connector_type': 'type2', 'planning_intent': {'mode': 'time', 'minutes': 3}}
        await charging.build(app, public_code='CG-ONE', point_context=CONTEXT,
                             station_search=search, planning_intent=search['planning_intent'])
        route, data = parent_route('charging', app.data)
        self.assertEqual(route, 'stations')
        self.assertEqual(data, {**search, 'station_id': 'station'})
        search['query'] = 'alterada fora do wizard'
        self.assertEqual(app.charging_draft['station_search']['query'], 'Centro')

    async def test_price_change_requires_new_review_without_posting(self):
        app = WizardApp()
        screen = await review_screen(app)
        app.station['connectors'][0]['price_per_kwh'] = '3.5'
        await click(screen, 'Solicitar início')(None)
        self.assertEqual(app.posts, [])
        self.assertEqual(app.charging_draft['step'], 2)
        self.assertEqual(app.charging_draft['point_context']['connector']['price_per_kwh'], '3.5')
        self.assertIn('condições do ponto mudaram', app.notices[-1])

    async def test_uncertain_retry_does_not_revalidate_or_replace_original_terms(self):
        app = WizardApp()
        screen = await review_screen(app)
        app.outcomes = [ApiError('Resposta perdida'), {'id': 'confirmed-session'}]
        with self.assertRaises(ApiError):
            await click(screen, 'Solicitar início')(None)
        original = deepcopy(app.posts[0])
        calls = len([call for call in app.api.request.call_args_list if call.args[1].startswith('stations/')])
        app.station['connectors'] = []
        await click(screen, 'Repetir mesmo pedido')(None)
        self.assertEqual(app.posts[1], original)
        self.assertEqual(len([call for call in app.api.request.call_args_list if call.args[1].startswith('stations/')]), calls)

    async def test_direct_budget_intention_matches_shared_estimate_and_survives_back(self):
        app = WizardApp()
        screen = await charging.build(app, public_code='CG-ONE', point_context=CONTEXT,
                                      planning_intent={'mode': 'value', 'max_cost': '1.50'})
        draft = app.charging_draft
        self.assertEqual((draft['mode'], draft['max_cost'], draft['safety_minutes']), ('value', '1.50', '10'))
        self.assertEqual(charging._estimate(draft), estimate_text(CONTEXT['connector'], 10, '1.50'))
        fields(screen)['Código temporário do posto'].value = '12345'
        await next_screen(app, screen)
        await charging.build(app, step=1, planning_intent={'mode': 'value', 'max_cost': '99'})
        self.assertEqual(app.charging_draft['max_cost'], '1.50')

    async def test_reservation_intention_applies_only_to_its_point(self):
        app = WizardApp()
        app.planning_intent = {'connector_id': 'another-point', 'intent': {'mode': 'time', 'minutes': 3}}
        await charging.build(app, public_code='CG-ONE', point_context=CONTEXT)
        self.assertEqual(app.charging_draft['duration_minutes'], '10')
        app.charging_draft = None
        app.planning_intent['connector_id'] = 'point'
        await charging.build(app, public_code='CG-ONE', point_context=CONTEXT)
        self.assertEqual(app.charging_draft['duration_minutes'], '3')
        self.assertIsNone(app.planning_intent)

    async def test_new_limit_and_free_tariff_are_respected_during_handoff(self):
        context = deepcopy(CONTEXT)
        context['connector']['price_per_kwh'] = '0'
        context['connector']['max_duration_minutes'] = 4
        app = WizardApp()
        await charging.build(app, public_code='CG-ONE', point_context=context,
                             planning_intent={'mode': 'value', 'max_cost': '10'})
        self.assertEqual(app.charging_draft['mode'], 'time')
        self.assertEqual(app.charging_draft['duration_minutes'], '4')
