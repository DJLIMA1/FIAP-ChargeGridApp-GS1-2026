import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft
import msgpack
from flet.controls.base_control import BaseControl
from flet.messaging.connection import Connection
from flet.messaging.protocol import configure_encode_object_for_msgpack
from flet.messaging.session import Session as FletSession
from flet.pubsub.pubsub_hub import PubSubHub

from chargegrid_app.api_client import ApiError
from chargegrid_app.app import ChargeGridApp
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DEMO_PRESENCE_CODE, DemoApi
from chargegrid_app.screens import chat


def descendants(item):
    yield item
    content = getattr(item, 'content', None)
    if content is not None and not isinstance(content, str):
        yield from descendants(content)
    for child in getattr(item, 'controls', []) or []:
        yield from descendants(child)


def texts(screen):
    return '\n'.join(str(c.value) for c in descendants(screen) if isinstance(c, ft.Text))


def message_texts(screen):
    return [c for c in descendants(screen) if isinstance(c, ft.Text) and c.semantics_label]


def composer(screen):
    return next(c for c in descendants(screen) if isinstance(c, ft.TextField))


def send_button(screen):
    return next(c for c in descendants(screen) if isinstance(c, ft.IconButton) and c.tooltip == 'Enviar mensagem')


def click(screen, label):
    return next(c.on_click for c in descendants(screen) if getattr(c, 'on_click', None)
                and isinstance(getattr(c, 'content', None), ft.Text) and c.content.value == label)


async def ask_guide(app, question, topic=None):
    screen = await chat.build(app, question=question, topic=topic)
    await click(screen, 'Perguntar: ' + question)(None)
    return screen


class ChatApp:
    def __init__(self):
        self.profile = {'id': 'account-a', 'name': 'Ana', 'account_type': 'consumer', 'operator_enabled': False}
        self.api = SimpleNamespace(is_demo=False, request=AsyncMock(),
                                   session=SimpleNamespace(user={'id': 'account-a'}, access_token='session'))
        self.page = SimpleNamespace(update=Mock())
        self.chat_messages = []
        self.chat_draft = ''
        self._chat_account_id = None
        self.browsing_mode = 'consumer'
        self.go = AsyncMock()
        self.prepare_navigation = AsyncMock(return_value=True)

    def action(self, operation):
        async def handler(event=None):
            await operation()
        return handler

    def link(self, route, **data):
        async def handler(event=None):
            if await self.prepare_navigation():
                await self.go(route, **data)
        return handler


def session_record(**changes):
    record = {'id': 'session-real', 'status': 'completed', 'station_name': 'Posto Leste',
              'station_address': 'Rua real', 'connector': {'public_code': 'CG-REAL', 'price_per_kwh': '9'},
              'energy_wh': '1250.000', 'cost_estimate': '3.1250', 'price_per_kwh': '2.5000',
              'max_duration_minutes': 20, 'max_cost': '6', 'source': 'measured', 'soc_percent': '41',
              'last_measurement_at': '2026-09-27T12:00:00+00:00', 'online': True}
    return {**record, **changes}


class ChatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = ChatApp()

    async def test_conversation_bubbles_fixed_composer_and_local_guidance_persist(self):
        with patch('httpx.AsyncClient', side_effect=AssertionError('No extra client')):
            screen = await chat.build(self.app)
            self.assertTrue(screen.expand)
            listing = next(c for c in screen.controls if isinstance(c, ft.ListView))
            self.assertTrue(listing.expand)
            self.assertTrue(listing.auto_scroll)
            self.assertEqual(listing.auto_scroll_animation, 0)
            self.assertFalse(listing.build_controls_on_demand)
            self.assertNotIn(composer(screen), list(descendants(listing)))
            self.assertIsNone(composer(screen).label)
            self.assertEqual(composer(screen).hint_text, 'Digite sua mensagem')
            self.assertEqual(composer(screen).counter, '')
            composer(screen).value = 'Como iniciar uma recarga com #F?'
            await send_button(screen).on_click(None)
            self.assertEqual([m['role'] for m in self.app.chat_messages], ['assistant', 'user', 'assistant'])
            self.assertIn('Confirmar ponto', texts(screen))
            self.assertIn('Definir limites', texts(screen))
            self.assertIn('Revisar recarga', texts(screen))
            self.assertEqual(composer(screen).value, '')
            self.assertEqual(listing.controls[1].controls[1].bgcolor, '#D72B32')
            self.assertEqual(listing.controls[2].controls[0].bgcolor, chat.ASSISTANT_BACKGROUND)
            again = await chat.build(self.app)
            self.assertEqual(len(self.app.chat_messages), 3)
            self.assertIn('Como iniciar uma recarga com #F?', texts(again))
            self.app.api.request.assert_not_called()
            await click(again, 'Encontrar um ponto')(None)
            self.assertNotIn('Tenho o código #F', texts(again))
            self.app.prepare_navigation.assert_awaited_once_with()
            self.app.go.assert_awaited_once_with('stations')

    async def test_bubble_semantics_include_speaker_without_hiding_navigation_actions(self):
        screen = await ask_guide(self.app, 'Como iniciar uma recarga?')
        messages = message_texts(screen)
        self.assertEqual([c.semantics_label for c in messages], [
            ('Você: ' if message['role'] == 'user' else 'Assistente: ') + message['content']
            for message in self.app.chat_messages
        ])
        for message in messages:
            self.assertFalse(message.selectable)
            self.assertFalse(any(getattr(c, 'on_click', None) for c in descendants(message)))
        await click(screen, 'Encontrar um ponto')(None)
        self.app.go.assert_awaited_once_with('stations')

    async def test_context_question_only_sends_after_click_and_reentry_follows_natively(self):
        self.app.api.request.return_value = {'items': [session_record()]}
        screen = await chat.build(self.app, question='Resumo da última recarga', topic='charging')
        self.app.api.request.assert_not_awaited()
        self.assertEqual(len(self.app.chat_messages), 1)
        await click(screen, 'Perguntar: Resumo da última recarga')(None)
        count = len(self.app.chat_messages)
        reopened = await chat.build(self.app, question='Resumo da última recarga', topic='charging')
        self.assertEqual(len(self.app.chat_messages), count)
        listing = next(c for c in descendants(reopened) if isinstance(c, ft.ListView))
        self.assertTrue(listing.auto_scroll)
        self.assertEqual(listing.auto_scroll_animation, 0)
        self.assertFalse(any(isinstance(c, ft.Container) and c.on_size_change for c in descendants(reopened)))
        self.app.api.request.assert_awaited_once()

    async def test_context_question_is_a_suggestion_and_never_updates_unmounted_conversation(self):
        self.app.api.request.return_value = {'items': [session_record()]}
        first = await chat.build(self.app)
        await click(first, 'Resumo da última recarga')(None)
        self.assertEqual(len(self.app.chat_messages), 3)
        self.app.page.update.reset_mock()
        self.app.page.update.side_effect = AssertionError('Cannot publish a partial unmounted chat')
        question = 'Como escolho um ponto e inicio uma recarga?'
        screen = await chat.build(self.app, question=question, topic='getting_started')
        self.app.page.update.assert_not_called()
        labels = [c.semantics_label for c in message_texts(screen)]
        self.assertEqual(len(labels), 3)
        self.assertIn('Perguntar: ' + question, texts(screen))
        self.assertFalse(any(isinstance(c, ft.Container) and c.on_size_change for c in descendants(screen)))
        self.assertIsNone(self.app._chat_pending)

    async def test_real_navigation_from_summary_via_home_guide_adds_context_question(self):
        page = SimpleNamespace(width=360, window=SimpleNamespace(), views=[SimpleNamespace()],
                               add=Mock(), update=Mock(), show_dialog=Mock(), pop_dialog=Mock())
        demo = DemoApi()
        with patch('chargegrid_app.app.ApiClient', return_value=demo), \
                patch('chargegrid_app.app.Preferences') as preferences:
            preferences.return_value.load.return_value = True
            app = ChargeGridApp(page)
        try:
            await demo.login(DEMO_EMAIL, DEMO_PASSWORD)
            await app.signed_in()
            await app.link('chat')(None)
            await click(app.scene.content, 'Resumo da última recarga')(None)
            self.assertEqual(len(app.chat_messages), 3)
            await app.link('home')(None)
            guide = next(c for c in descendants(app.scene.content)
                         if isinstance(c, ft.Container) and c.on_click and isinstance(c.content, ft.Row)
                         and any(isinstance(t, ft.Text) and t.value == 'Guia de recarga' for t in descendants(c)))
            await guide.on_click(None)
            self.assertEqual(app.route, 'chat')
            self.assertEqual(app.data['topic'], 'getting_started')
            question = app.data['question']
            self.assertEqual(len(app.chat_messages), 3)
            await click(app.scene.content, 'Perguntar: ' + question)(None)
            self.assertEqual([m['content'] for m in app.chat_messages if m['role'] == 'user'],
                             ['Resumo da última recarga', question])
            self.assertIn('Você: ' + question, [c.semantics_label for c in message_texts(app.scene.content)])
            self.assertTrue(next(c for c in descendants(app.scene.content) if isinstance(c, ft.ListView)).auto_scroll)
            self.assertIsNone(app._chat_pending)
        finally:
            app.cancel_screen()
            await demo.close()

    async def test_three_questions_append_rows_and_real_wire_never_resends_old_messages(self):
        """Use Flet's actual diff + MessagePack encoder, not a mocked Page.update."""
        encoder = configure_encode_object_for_msgpack(BaseControl)

        def encode(value):
            return msgpack.unpackb(msgpack.packb(value, default=encoder), strict_map_key=False)

        class CaptureConnection(Connection):
            def __init__(self):
                super().__init__()
                self.pubsubhub = PubSubHub()
                self.loop = asyncio.get_running_loop()
                self.messages = []

            def send_message(self, message):
                self.messages.append(encode([message.action, message.body]))

        def wire_labels(value):
            if isinstance(value, dict):
                if value.get('semantics_label'):
                    yield value['semantics_label']
                for child in value.values():
                    yield from wire_labels(child)
            elif isinstance(value, list):
                for child in value:
                    yield from wire_labels(child)

        connection = CaptureConnection()
        session = FletSession(connection)
        session.attach_connection(connection)
        page = session.page
        page.width, page.height = 360, 800
        encode(session.get_page_patch())  # initial registration captures diff snapshots
        demo = DemoApi()
        with patch('chargegrid_app.app.ApiClient', return_value=demo), \
                patch('chargegrid_app.app.Preferences') as preferences:
            preferences.return_value.load.return_value = True
            app = ChargeGridApp(page)
        try:
            await demo.login(DEMO_EMAIL, DEMO_PASSWORD)
            await app.signed_in()
            await app.link('chat')(None)
            listing = next(c for c in descendants(app.scene.content) if isinstance(c, ft.ListView))
            for turn, label in enumerate(('Resumo da última recarga', 'Ajuda com limites', 'Reservar'), start=1):
                with self.subTest(question=label):
                    old_rows = list(listing.controls)
                    old_ids = [c._i for c in old_rows]
                    connection.messages.clear()
                    await click(app.scene.content, label)(None)
                    self.assertEqual(len(listing.controls), 1 + turn * 2)
                    self.assertEqual([c._i for c in listing.controls[:len(old_rows)]], old_ids)
                    self.assertTrue(all(a is b for a, b in zip(old_rows, listing.controls)))
                    self.assertTrue(all(session.index.get(c._i) is c for c in listing.controls))
                    labels = list(wire_labels(connection.messages))
                    self.assertEqual(len(labels), 2)
                    self.assertEqual(labels[0], 'Você: ' + label)
                    self.assertTrue(labels[1].startswith('Assistente: '))
            self.assertEqual(len(message_texts(app.scene.content)), 7)
        finally:
            app.cancel_screen()
            await demo.close()
            session.close()
            await asyncio.sleep(0)

    async def test_quick_chips_have_real_local_guidance_and_preserve_unsent_draft(self):
        screen = await chat.build(self.app)
        composer(screen).value = 'Uma dúvida que ainda não enviei'
        composer(screen).on_change(None)
        await click(screen, 'Ajuda com limites')(None)
        self.assertIn('Por tempo', self.app.chat_messages[-1]['content'])
        self.assertIn('teto de custo estimado', self.app.chat_messages[-1]['content'])
        self.assertEqual(composer(screen).value, 'Uma dúvida que ainda não enviei')
        reopened = await chat.build(self.app)
        self.assertEqual(composer(reopened).value, 'Uma dúvida que ainda não enviei')
        self.app.api.request.assert_not_called()

    async def test_empty_and_oversized_questions_keep_draft_and_do_not_query(self):
        screen = await chat.build(self.app)
        for value in ('   ', 'a' * (chat.MAX_QUESTION_LENGTH + 1)):
            composer(screen).value = value
            composer(screen).on_change(None)
            await composer(screen).on_submit(None)
            self.assertEqual(len(self.app.chat_messages), 1)
            self.assertTrue(composer(screen).error_text)
            self.assertEqual(composer(screen).value, value)
            self.assertEqual(self.app.chat_draft, value)
        self.app.api.request.assert_not_called()

    async def test_guide_reentry_does_not_send_without_click_or_discard_draft(self):
        original = await chat.build(self.app)
        composer(original).value = 'Rascunho pessoal'
        composer(original).on_change(None)
        await chat.build(self.app, question='Como faço uma reserva?', topic='reservations')
        count = len(self.app.chat_messages)
        second = await chat.build(self.app, question='Como faço uma reserva?', topic='reservations')
        self.assertEqual(len(self.app.chat_messages), count)
        self.assertEqual(composer(second).value, 'Rascunho pessoal')
        self.assertIn('Minha reserva', texts(second))
        await click(second, 'Perguntar: Como faço uma reserva?')(None)
        self.assertEqual(composer(second).value, 'Rascunho pessoal')
        self.assertEqual(len(self.app.chat_messages), count + 2)
        self.app.api.request.assert_not_called()

    async def test_account_and_demo_boundaries_discard_previous_conversation_and_draft(self):
        screen = await ask_guide(self.app, 'Limites da recarga')
        composer(screen).value = 'Mensagem privada da conta A'
        composer(screen).on_change(None)
        self.app.profile['id'] = 'account-b'
        second = await chat.build(self.app)
        self.assertEqual(len(self.app.chat_messages), 1)
        self.assertNotIn('Limites da recarga', texts(second))
        self.assertEqual(composer(second).value, '')
        self.app.api.is_demo = True
        demo = await chat.build(self.app)
        self.assertIn('demonstrações', texts(demo))
        self.assertEqual(len(self.app.chat_messages), 1)

    async def test_last_session_reads_real_history_and_snapshot_price_without_paid_claims(self):
        self.app.api.request.return_value = {'items': [session_record()]}
        screen = await chat.build(self.app)
        await click(screen, 'Resumo da última recarga')(None)
        self.app.api.request.assert_awaited_once_with('GET', 'me/charging-sessions', params={'limit': 1, 'offset': 0})
        response = self.app.chat_messages[-1]['content']
        for expected in ('Sua última recarga como consumidor', 'Posto Leste', 'CG-REAL', '1.250 kWh', 'R$ 3,12', 'Tarifa da sessão: R$ 2,50/kWh', 'medida pelo equipamento'):
            self.assertIn(expected, response)
        self.assertNotIn('R$ 9,00', response)
        self.assertNotIn('Pago', response)
        self.assertIn('não comprovantes de pagamento', response)
        await click(screen, 'Ver detalhes da recarga')(None)
        self.app.go.assert_awaited_once_with('charging', session_id='session-real')

    async def test_vendor_summary_scopes_history_and_honors_explicit_personal_intent(self):
        self.app.profile.update(account_type='vendor', operator_enabled=True)
        self.app.browsing_mode = 'vendor'
        self.app.api.request.return_value = {'items': [session_record()]}
        screen = await chat.build(self.app)
        await click(screen, 'Última recarga dos meus postos')(None)
        self.app.api.request.assert_awaited_with('GET', 'operator/charging-sessions', params={'limit': 1, 'offset': 0})
        self.assertIn('dos seus postos', self.app.chat_messages[-1]['content'])
        await click(screen, 'Ver histórico dos postos')(None)
        self.app.go.assert_awaited_with('history', manage=True)
        composer(screen).value = 'Minha última recarga como consumidor'
        await composer(screen).on_submit(None)
        self.app.api.request.assert_awaited_with('GET', 'me/charging-sessions', params={'limit': 1, 'offset': 0})
        self.assertIn('como consumidor', self.app.chat_messages[-1]['content'])

    async def test_unapproved_vendor_history_has_no_privilege_bypass(self):
        self.app.browsing_mode = 'vendor'
        self.app.profile.update(account_type='vendor', operator_enabled=False)
        screen = await ask_guide(self.app, 'Última recarga dos meus postos')
        self.assertIn('após vincular seu primeiro equipamento', texts(screen))
        self.app.api.request.assert_not_called()

    async def test_current_session_and_reservation_show_api_status_and_offline_limits(self):
        async def query(method, path, **kwargs):
            if path == 'charging-sessions/current':
                return session_record(status='stopping', online=False, cost_estimate=None, energy_wh=None)
            return {'status': 'pending_device', 'station_name': 'Posto reservado', 'connector': {'public_code': 'CG-R'}, 'expires_at': None}
        self.app.api.request.side_effect = query
        screen = await chat.build(self.app, topic='charging')
        composer(screen).value = 'Como está minha recarga?'
        await composer(screen).on_submit(None)
        response = self.app.chat_messages[-1]['content']
        self.assertIn('Parada pendente', response)
        self.assertIn('Equipamento offline', response)
        self.assertIn('Energia: não informada', response)
        self.assertIn('Custo estimado: não informado', response)
        self.assertNotIn('R$ 0,00', response)
        composer(screen).value = 'Minha reserva'
        await composer(screen).on_submit(None)
        self.assertIn('Posto reservado', self.app.chat_messages[-1]['content'])
        self.assertIn('depois da confirmação', self.app.chat_messages[-1]['content'])
        self.assertEqual([call.args[:2] for call in self.app.api.request.await_args_list],
                         [('GET', 'charging-sessions/current'), ('GET', 'reservations/current')])

    async def test_empty_history_and_no_current_operations_are_not_fabricated(self):
        self.app.api.request.return_value = {'items': []}
        response = await chat.answer(self.app, 'Resumo da última recarga')
        self.assertIn('Ainda não há registros', response['content'])
        self.assertNotIn('R$', response['content'])
        self.app.api.request.return_value = None
        self.assertIn('não tem uma recarga ativa', (await chat.answer(self.app, 'Minha recarga'))['content'])
        self.assertIn('não tem uma reserva ativa', (await chat.answer(self.app, 'Minha reserva'))['content'])

    async def test_query_failure_keeps_messages_and_form_and_local_guidance_available(self):
        screen = await ask_guide(self.app, 'Como iniciar uma recarga?')
        before = list(self.app.chat_messages)
        self.app.api.request.side_effect = ApiError('network error with details', 503)
        composer(screen).value = 'Resumo da última recarga'
        await composer(screen).on_submit(None)
        self.assertEqual(self.app.chat_messages[:len(before)], before)
        self.assertIn('Não consegui consultar', self.app.chat_messages[-1]['content'])
        self.assertNotIn('network error with details', texts(screen))
        self.assertEqual(composer(screen).value, 'Resumo da última recarga')
        self.assertEqual(self.app.chat_draft, 'Resumo da última recarga')
        await click(screen, 'Ajuda com limites')(None)
        self.assertIn('Por tempo', self.app.chat_messages[-1]['content'])
        self.assertEqual(self.app.api.request.await_count, 1)

    async def test_double_submit_has_one_inflight_query(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        async def slow(*args, **kwargs):
            entered.set()
            await finish.wait()
            return {'items': [session_record()]}
        self.app.api.request.side_effect = slow
        screen = await chat.build(self.app)
        composer(screen).value = 'Resumo da última recarga'
        pending = asyncio.create_task(send_button(screen).on_click(None))
        await entered.wait()
        await composer(screen).on_submit(None)
        self.assertEqual(self.app.api.request.await_count, 1)
        self.assertTrue(send_button(screen).disabled)
        finish.set()
        await pending
        self.assertEqual([m['role'] for m in self.app.chat_messages], ['assistant', 'user', 'assistant'])
        self.assertFalse(send_button(screen).disabled)

    async def test_slow_response_cannot_leak_into_another_account(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        async def slow(*args, **kwargs):
            entered.set()
            await finish.wait()
            return {'items': [session_record(station_name='Private station from A')]}
        self.app.api.request.side_effect = slow
        first = await chat.build(self.app)
        composer(first).value = 'Resumo da última recarga'
        pending = asyncio.create_task(composer(first).on_submit(None))
        await entered.wait()
        self.app.profile['id'] = 'account-b'
        second = await chat.build(self.app)
        finish.set()
        await pending
        self.assertEqual(len(self.app.chat_messages), 1)
        self.assertNotIn('Private station from A', texts(second))
        self.assertIsNone(self.app._chat_pending)

    async def test_changed_draft_during_query_is_preserved(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        async def slow(*args, **kwargs):
            entered.set()
            await finish.wait()
            return {'items': []}
        self.app.api.request.side_effect = slow
        screen = await chat.build(self.app)
        composer(screen).value = 'Resumo da última recarga'
        pending = asyncio.create_task(composer(screen).on_submit(None))
        await entered.wait()
        composer(screen).value = 'Próxima pergunta'
        composer(screen).on_change(None)
        finish.set()
        await pending
        self.assertEqual(self.app.chat_draft, 'Próxima pergunta')
        self.assertEqual(composer(screen).value, 'Próxima pergunta')

    async def test_demo_summary_reports_live_demo_result_and_demo_guidance(self):
        instant = [0.0]
        with patch('httpx.AsyncClient', side_effect=AssertionError('No network in demo chat')):
            demo = DemoApi(clock=lambda: instant[0])
            await demo.login(DEMO_EMAIL, DEMO_PASSWORD)
            self.app.api = demo
            self.app.profile = await demo.request('GET', 'me')
            point = next(p for p in (await demo.request('GET', 'stations'))['items'][0]['connectors'] if p['available'])
            created = await demo.request('POST', 'charging-sessions', {'public_code': point['public_code'], 'presence_code': DEMO_PRESENCE_CODE, 'max_duration_minutes': 1}, key='chat-demo')
            instant[0] += 100
            completed = await demo.request('GET', f"charging-sessions/{created['id']}")
            screen = await ask_guide(self.app, 'Resumo da última recarga')
            self.assertIn('0.120 kWh', self.app.chat_messages[-1]['content'])
            self.assertIn('R$ 0,18', self.app.chat_messages[-1]['content'])
            self.assertEqual(completed['energy_wh'], '120.000')
            self.assertIn('Dados da demonstração', self.app.chat_messages[-1]['content'])
            await click(screen, 'Iniciar uma recarga')(None)
            self.assertIn('#F12345', self.app.chat_messages[-1]['content'])
            self.assertIn('nenhum ESP32', self.app.chat_messages[-1]['content'])
            await demo.close()


if __name__ == '__main__':
    unittest.main()
