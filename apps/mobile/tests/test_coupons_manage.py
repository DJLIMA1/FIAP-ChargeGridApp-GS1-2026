"""Gestão de cupons do vendedor: atalho visível na lista de estações, lista com status/uso e formulário."""
import unittest
from datetime import datetime, timedelta, timezone

import flet as ft

from chargegrid_app.screens import coupons, operator
from chargegrid_app.services import station_settings
from test_behavior import HandlerApp, click, descendants
from test_seller_flow_fixes import fields
from test_station_admin import demo_app, press


def texts(screen):
    return [str(c.value) for c in descendants(screen) if isinstance(c, ft.Text)]


def _iso(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def coupon(identifier, code, *, days=10, active=True, uses=None, last=None, granted=None, station_id=None):
    item = {'id': identifier, 'code': code, 'description': f'Desconto {code}', 'discount_percent': 10,
            'valid_until': _iso(days), 'active': active, 'station_id': station_id}
    if uses is not None:
        item.update(uses=uses, last_used_at=last, discount_total_approx=granted or '0.00')
    return item


def manage_app(items):
    app = HandlerApp()
    app.profile = {'operator_enabled': True}
    app.api.request.side_effect = [{'items': items, 'total': len(items)},
                                   {'items': [{'id': 'st', 'name': 'Posto Central'}], 'total': 1}]
    return app


class OperatorShortcutTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        station_settings.reset_demo()

    async def test_manage_coupons_sits_right_after_add_station_before_the_chatbot(self):
        app = await demo_app()
        screen = await operator.build(app)
        copy = texts(screen)
        add, manage, chat = (copy.index(operator.ADD_STATION), copy.index(operator.MANAGE_COUPONS),
                             copy.index('Fale com o ChatBot'))
        self.assertLess(add, manage)
        self.assertLess(manage, chat)
        self.assertEqual(copy[manage + 1], operator.MANAGE_COUPONS_HINT)
        if 'Mais opções' in copy:  # só os insights de IA continuam abaixo da 1ª tela
            self.assertGreater(copy.index('Mais opções'), chat)
            self.assertEqual(copy.count(operator.MANAGE_COUPONS), 1)
        await press(screen, operator.MANAGE_COUPONS)(None)
        app.go.assert_awaited_with('coupons', manage=True)
        await app.api.close()

    async def test_first_station_screen_also_offers_coupons(self):
        app = HandlerApp()
        app.api.request.side_effect = [{'account_type': 'vendor', 'operator_enabled': True},
                                       {'items': [], 'total': 0}]
        screen = await operator.build(app)
        self.assertIn(operator.MANAGE_COUPONS, texts(screen))


class CouponListTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_shows_summary_status_usage_and_approximate_discount(self):
        app = manage_app([coupon('a', 'ATIVO', uses=3, last='2026-10-20T12:00:00+00:00', granted='12.34'),
                          coupon('e', 'VENCIDO', days=-1, uses=0),
                          coupon('i', 'PAUSADO', active=False, uses=1, last='2026-10-01T12:00:00+00:00',
                                 station_id='st')])
        screen = await coupons.build(app, manage=True)
        copy = texts(screen)
        joined = ' '.join(copy)
        for label in ('Ativo', 'Expirado', 'Inativo', 'Ativos', 'Expirados', 'Inativos', 'Usos'):
            self.assertIn(label, copy)
        summary = next(c for c in descendants(screen) if getattr(c, 'data', None) == 'coupon-summary')
        self.assertEqual([str(c.value) for c in descendants(summary) if isinstance(c, ft.Text)][:8],
                         ['1', 'Ativos', '1', 'Expirados', '1', 'Inativos', '4', 'Usos'])
        self.assertIn('3 usos · último em 20/10/2026', joined)
        self.assertIn('Nenhum uso ainda', joined)
        self.assertIn('1 uso · último em', joined)
        self.assertIn('Desconto concedido (aprox.): R$ 12,34', joined)
        self.assertIn('Válido em: Posto Central', joined)
        self.assertIn('Expirou em', joined)
        self.assertIn('Reativar', copy)

    async def test_old_api_without_usage_hides_usage_lines(self):
        app = manage_app([coupon('a', 'ATIVO')])
        joined = ' '.join(texts(await coupons.build(app, manage=True)))
        self.assertNotIn('uso', joined.replace('Usos', ''))
        self.assertNotIn('Usos', joined)

    async def test_status_filter_keeps_only_matching_coupons_and_navigates(self):
        items = [coupon('a', 'ATIVO', uses=0), coupon('e', 'VENCIDO', days=-1, uses=0)]
        screen = await coupons.build(manage_app(items), manage=True, status='expired')
        cards = [c.data for c in descendants(screen) if str(getattr(c, 'data', '')).startswith('coupon:')]
        self.assertEqual(cards, ['coupon:e'])
        app = manage_app(items)
        screen = await coupons.build(app, manage=True)
        await click(screen, 'Expirados')(None)
        app.go.assert_awaited_with('coupons', manage=True, status='expired')
        await click(screen, 'Todos')(None)
        app.go.assert_awaited_with('coupons', manage=True)

    async def test_deactivate_and_reactivate_use_patch_active(self):
        app = manage_app([coupon('a', 'ATIVO', uses=0)])
        screen = await coupons.build(app, manage=True)
        app.api.request.side_effect = None
        await click(screen, 'Desativar')(None)
        self.assertEqual(app.api.request.await_args.args, ('PATCH', 'coupons/a', {'active': False}))
        app.go.assert_awaited_with('coupons', manage=True)
        app = manage_app([coupon('i', 'PAUSADO', active=False, uses=0)])
        screen = await coupons.build(app, manage=True)
        app.api.request.side_effect = None
        await click(screen, 'Reativar')(None)
        self.assertEqual(app.api.request.await_args.args, ('PATCH', 'coupons/i', {'active': True}))

    async def test_reactivating_an_expired_coupon_opens_the_editor_instead_of_failing(self):
        expired = coupon('x', 'VELHO', days=-2, active=False, uses=0)
        app = manage_app([expired])
        screen = await coupons.build(app, manage=True)
        calls = app.api.request.await_count
        await click(screen, 'Reativar')(None)
        self.assertEqual(app.api.request.await_count, calls)  # nenhum PATCH que a API recusaria
        app.go.assert_awaited_with('coupons', manage=True, coupon=expired)
        self.assertIn('nova validade', app.notices[-1])

    async def test_empty_manage_list_offers_creation(self):
        app = manage_app([])
        screen = await coupons.build(app, manage=True)
        self.assertIn('Nenhum cupom criado', texts(screen))
        await click(screen, 'Criar cupom')(None)
        app.go.assert_awaited_with('coupons', manage=True, create=True)


class CouponFormTests(unittest.IsolatedAsyncioTestCase):
    async def test_discount_and_expiry_shortcuts_fill_the_same_body_as_typing(self):
        app = HandlerApp()
        screen = coupons.form(app, stations=[])
        fields(screen)['Código'].value = ' verao '
        await click(screen, '15%')(None)
        self.assertEqual(fields(screen)['Desconto %'].value, '15')
        await click(screen, '7 dias')(None)
        await click(screen, 'Salvar cupom')(None)
        method, path, body = app.api.request.await_args.args
        self.assertEqual((method, path, body['code'], body['discount_percent']), ('POST', 'coupons', 'VERAO', 15))
        expiry = datetime.fromisoformat(body['valid_until'])
        self.assertGreater(expiry, datetime.now(timezone.utc) + timedelta(days=6))
        self.assertLess(expiry, datetime.now(timezone.utc) + timedelta(days=8))

    async def test_preview_follows_code_and_discount(self):
        app = HandlerApp()
        screen = coupons.form(app, stations=[])
        preview = next(c for c in descendants(screen) if getattr(c, 'data', None) == 'coupon-preview')
        fields(screen)['Código'].value = 'bemvindo'
        fields(screen)['Código'].on_change(None)
        self.assertEqual(preview.value, 'BEMVINDO · 10% OFF')
        await click(screen, '20%')(None)
        self.assertEqual(preview.value, 'BEMVINDO · 20% OFF')

    async def test_editing_shows_status_and_usage_without_changing_code(self):
        app = HandlerApp()
        item = coupon('a', 'ATIVO', uses=2, last='2026-10-20T12:00:00+00:00')
        screen = coupons.form(app, item, [])
        copy = ' '.join(texts(screen))
        self.assertIn('Editar cupom', copy)
        self.assertIn('2 usos · último em 20/10/2026', copy)
        self.assertNotIn('Código', fields(screen))  # código não é editável depois de criado
        await click(screen, 'Salvar cupom')(None)
        self.assertEqual(app.api.request.await_args.args,
                         ('PATCH', 'coupons/a', {'description': 'Desconto ATIVO', 'discount_percent': 10}))


class DemoUsageTests(unittest.IsolatedAsyncioTestCase):
    async def test_demo_owner_list_reports_usage_like_the_api(self):
        app = await demo_app()
        mine = await app.api.request('GET', 'coupons', params={'mine': 'true'})
        self.assertTrue(mine['items'])
        self.assertTrue(all({'uses', 'last_used_at', 'discount_total_approx'} <= set(item) for item in mine['items']))
        public = await app.api.request('GET', 'coupons')
        self.assertTrue(all('uses' not in item for item in public['items']))
        await app.api.close()
