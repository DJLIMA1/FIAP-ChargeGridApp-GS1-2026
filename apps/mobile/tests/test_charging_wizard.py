"""One-step-at-a-time charging, session drafts and ambiguous request recovery."""

import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.navigation import parent_route
from chargegrid_app.screens import charging
from test_behavior import HandlerApp, click, descendants

CONTEXT = {'station_id':'station','station_name':'Posto Central','station_address':'Rua Um',
           'connector':{'id':'point','public_code':'CG-ONE','connector_type':'Tipo 2','power_kw':'6',
                        'price_per_kwh':'2','max_duration_minutes':10}}


def texts(screen):
    return ' '.join(str(item.value) for item in descendants(screen) if isinstance(item,ft.Text))


def fields(screen):
    return {item.label:item for item in descendants(screen) if isinstance(item,ft.TextField)}


def visible_fields(control):
    if not getattr(control,'visible',True):
        return []
    result = [control] if isinstance(control,ft.TextField) else []
    content = getattr(control,'content',None)
    if content and not isinstance(content,str):
        result += visible_fields(content)
    for child in getattr(control,'controls',[]) or []:
        result += visible_fields(child)
    return result


class WizardApp(HandlerApp):
    def __init__(self):
        super().__init__()
        self.profile = {'id':'user-one'}
        self.current = self.reservation = None
        self.outcomes = []
        self.posts = []
        self.sessions = {}
        self.station = {'id': 'station', 'name': 'Posto Central', 'address': 'Rua Um',
                        'connectors': [deepcopy(CONTEXT['connector'])]}
        self.sequence = 0
        self.api.request = AsyncMock(side_effect=self.request)
        self.api.new_key = self.new_key
        self.sync_back = Mock()

    def new_key(self):
        self.sequence += 1
        return f'key-{self.sequence}'

    async def request(self,method,path,body=None,**kwargs):
        if method == 'GET':
            if path == 'charging-sessions/current':
                return deepcopy(self.current)
            if path == 'reservations/current':
                return deepcopy(self.reservation)
            if path.startswith('stations/'):
                return deepcopy(self.station)
            return deepcopy(self.sessions[path.split('/')[-1]])
        self.posts.append((deepcopy(body),kwargs.get('key')))
        outcome = self.outcomes.pop(0) if self.outcomes else {'id':'new-session'}
        if isinstance(outcome,Exception):
            raise outcome
        return deepcopy(outcome)


async def next_screen(app,screen):
    await click(screen,'Continuar')(None)
    return await charging.build(app,**app.go.call_args.kwargs)


async def limits_screen(app,**kwargs):
    screen = await charging.build(app,**({'public_code':'CG-ONE','point_context':CONTEXT}|kwargs))
    fields(screen)['Código temporário do posto'].value = '12345'
    return await next_screen(app,screen)


async def review_screen(app,**kwargs):
    return await next_screen(app,await limits_screen(app,**kwargs))


class ChargingWizardTests(unittest.IsolatedAsyncioTestCase):
    async def test_optional_field_cards_expand_full_width_keep_values_and_restore_state(self):
        app = WizardApp()
        app.page.update = Mock()
        screen = await limits_screen(app)
        await click(screen,'Por valor')(None)
        self.assertFalse(any(isinstance(item,ft.ExpansionTile) for item in descendants(screen)))
        def section(label):
            return next(item for item in descendants(screen) if isinstance(item,ft.Container)
                        and isinstance(item.content,ft.Column)
                        and isinstance(item.content.controls[0],ft.Semantics)
                        and label in texts(item.content.controls[0]))
        for label,field_label,key in [('Ajustar tempo máximo','Tempo máximo de segurança (min)','safety_expanded'),
                                      ('Cupom de desconto','Cupom (opcional)','coupon_expanded')]:
            with self.subTest(label=label):
                card = section(label)
                semantic,body = card.content.controls
                self.assertFalse(body.visible)
                self.assertEqual(body.horizontal_alignment,ft.CrossAxisAlignment.STRETCH)
                await semantic.content.on_click(None)
                self.assertTrue(body.visible)
                self.assertTrue(semantic.expanded)
                icon = next(item for item in descendants(semantic) if isinstance(item,ft.Icon))
                self.assertEqual(icon.icon,ft.Icons.EXPAND_LESS)
                field = fields(screen)[field_label]
                field.value = '8' if key == 'safety_expanded' else 'PROMO'
                await field.on_change(None)
                await semantic.content.on_click(None)
                self.assertFalse(body.visible)
                self.assertEqual(icon.icon,ft.Icons.EXPAND_MORE)
                await semantic.content.on_click(None)
                self.assertTrue(app.charging_draft[key])
                self.assertEqual(field.value,'8' if key == 'safety_expanded' else 'PROMO')
        resumed = await charging.build(app)
        self.assertIn('8 min',texts(resumed))
        self.assertEqual(fields(resumed)['Cupom (opcional)'].value,'PROMO')
        self.assertIn('Código informado · validação no início',texts(resumed))
        self.assertEqual(app.posts,[])

    async def test_three_steps_show_only_current_form_and_only_review_posts(self):
        app = WizardApp()
        first = await charging.build(app,public_code='CG-ONE',point_context=CONTEXT)
        self.assertEqual(list(fields(first)),['Código temporário do posto'])
        self.assertEqual(fields(first)['Código temporário do posto'].counter,'')
        self.assertIsNone(fields(first)['Código temporário do posto'].width)
        self.assertNotIn('Solicitar início',texts(first))
        fields(first)['Código temporário do posto'].value = '12345'
        second = await next_screen(app,first)
        self.assertEqual(app.data['step'],2)
        self.assertNotIn('Código temporário do posto',fields(second))
        self.assertFalse(any(isinstance(item,ft.Dropdown) for item in descendants(second)))
        self.assertTrue(all(item.width is None for item in fields(second).values()))
        self.assertNotIn('Limite de custo estimado (R$)',[item.label for item in visible_fields(second)])
        third = await next_screen(app,second)
        self.assertEqual(app.data['step'],3)
        self.assertFalse(fields(third))
        self.assertIn('RESUMO DA RECARGA',texts(third))
        self.assertEqual(app.posts,[])
        await click(third,'Solicitar início')(None)
        self.assertEqual(len(app.posts),1)
        self.assertEqual(app.posts[0][0],{'presence_code':'#F12345','public_code':'CG-ONE','max_duration_minutes':10})
        self.assertIsNone(app.charging_draft)

    async def test_invalid_code_cannot_advance_or_post(self):
        app = WizardApp()
        screen = await charging.build(app)
        for value in ('','1234','１２３４５','abcde'):
            fields(screen)['Código temporário do posto'].value = value
            with self.assertRaises(ApiError):
                await click(screen,'Continuar')(None)
        app.go.assert_not_called()
        self.assertEqual(app.posts,[])
        self.assertEqual(app.data['step'],1)

    async def test_direct_review_route_cannot_bypass_steps(self):
        app = WizardApp()
        screen = await charging.build(app,step=3)
        self.assertEqual(app.data['step'],1)
        self.assertIn('Confirmar ponto',texts(screen))

    async def test_back_and_resume_keep_code_limits_coupon_and_route_context(self):
        app = WizardApp()
        screen = await limits_screen(app)
        duration,coupon = fields(screen)['Duração máxima (min)'],fields(screen)['Cupom (opcional)']
        duration.value,coupon.value = '7','PROMO'
        await duration.on_change(None)
        await coupon.on_change(None)
        resumed = await charging.build(app)
        self.assertEqual(app.data['step'],2)
        self.assertEqual(fields(resumed)['Duração máxima (min)'].value,'7')
        self.assertEqual(fields(resumed)['Cupom (opcional)'].value,'PROMO')
        await click(resumed,'Voltar')(None)
        back = await charging.build(app,**app.go.call_args.kwargs)
        self.assertEqual(fields(back)['Código temporário do posto'].value,'12345')
        self.assertEqual(app.charging_draft['duration_minutes'],'7')
        self.assertEqual(app.data['point_context']['station_id'],'station')
        app.sync_back.assert_called()

    async def test_native_parent_moves_back_one_wizard_step(self):
        app = WizardApp()
        await review_screen(app)
        route,data = parent_route('charging',app.data)
        self.assertEqual((route,data['step']),('charging',2))
        self.assertEqual(data['point_context'],CONTEXT)

    async def test_owner_change_never_reuses_draft_from_previous_account(self):
        app = WizardApp()
        await limits_screen(app)
        app.profile = {'id':'user-two'}
        screen = await charging.build(app)
        self.assertEqual(app.data['step'],1)
        self.assertEqual(fields(screen)['Código temporário do posto'].value,'')

    async def test_viewing_old_history_preserves_draft_and_explicit_resume(self):
        app = WizardApp()
        second = await limits_screen(app)
        fields(second)['Duração máxima (min)'].value = '7'
        fields(second)['Cupom (opcional)'].value = 'PROMO'
        await fields(second)['Cupom (opcional)'].on_change(None)
        app.sessions['old'] = {'id':'old','status':'completed','max_duration_minutes':5}
        history = await charging.build(app,session_id='old')
        self.assertEqual(app.charging_draft['duration_minutes'],'7')
        await click(history,'Retomar preparação da recarga')(None)
        resumed = await charging.build(app,**app.go.call_args.kwargs)
        self.assertEqual(app.data['step'],2)
        self.assertEqual(fields(resumed)['Cupom (opcional)'].value,'PROMO')

    async def test_value_mode_keeps_safety_limit_and_time_mode_ignores_hidden_cost(self):
        app = WizardApp()
        second = await limits_screen(app)
        await click(second,'Por valor')(None)
        self.assertNotIn('Duração máxima (min)',[item.label for item in visible_fields(second)])
        fields(second)['Limite de custo estimado (R$)'].value = '1,50'
        fields(second)['Tempo máximo de segurança (min)'].value = '8'
        await fields(second)['Limite de custo estimado (R$)'].on_change(None)
        third = await next_screen(app,second)
        self.assertIn('0,75 kWh',texts(third))
        await click(third,'Solicitar início')(None)
        self.assertEqual(app.posts[0][0]['max_cost'],'1.50')
        self.assertEqual(app.posts[0][0]['max_duration_minutes'],8)
        app = WizardApp()
        second = await limits_screen(app)
        await click(second,'Por valor')(None)
        fields(second)['Limite de custo estimado (R$)'].value = 'bad-input'
        await click(second,'Por tempo')(None)
        third = await next_screen(app,second)
        await click(third,'Solicitar início')(None)
        self.assertNotIn('max_cost',app.posts[0][0])

    async def test_unknown_point_value_mode_uses_30_minute_safety_not_1440(self):
        app = WizardApp()
        second = await limits_screen(app,public_code='',point_context=None)
        await click(second,'Por valor')(None)
        self.assertEqual(fields(second)['Tempo máximo de segurança (min)'].value,'30')
        fields(second)['Limite de custo estimado (R$)'].value = '5'
        third = await next_screen(app,second)
        await click(third,'Solicitar início')(None)
        self.assertEqual(app.posts[0][0]['max_duration_minutes'],30)

    async def test_bad_limits_and_free_tariff_cannot_advance_to_post(self):
        for mode,value in (('time','11'),('time','1.5'),('value',''),('value','NaN'),('value','-1')):
            app = WizardApp()
            second = await limits_screen(app)
            await click(second,'Por tempo' if mode=='time' else 'Por valor')(None)
            label = 'Duração máxima (min)' if mode=='time' else 'Limite de custo estimado (R$)'
            fields(second)[label].value = value
            with self.assertRaises(ApiError):
                await click(second,'Continuar')(None)
            self.assertEqual(app.posts,[])
        app = WizardApp()
        free = {**CONTEXT,'connector':{**CONTEXT['connector'],'price_per_kwh':'0'}}
        second = await limits_screen(app,point_context=free)
        await click(second,'Por valor')(None)
        fields(second)['Limite de custo estimado (R$)'].value = '5'
        with self.assertRaisesRegex(ApiError,'tarifa gratuita'):
            await click(second,'Continuar')(None)

    async def test_reservation_expiring_on_review_prevents_post(self):
        app = WizardApp()
        app.reservation = {**CONTEXT,'id':'reservation','status':'confirmed','connector_id':'point'}
        third = await review_screen(app)
        app.reservation = None
        with self.assertRaisesRegex(ApiError,'expirou'):
            await click(third,'Solicitar início')(None)
        self.assertEqual(app.posts,[])

    async def test_finished_reservation_releases_draft_for_same_point_with_fresh_code(self):
        for status in (None,'expired','cancelled'):
            with self.subTest(status=status):
                app = WizardApp()
                app.reservation = {**CONTEXT,'id':'reservation','status':'confirmed','connector_id':'point'}
                second = await limits_screen(app)
                fields(second)['Duração máxima (min)'].value = '7'
                fields(second)['Cupom (opcional)'].value = 'PROMO'
                await next_screen(app,second)
                app.reservation = None if status is None else {**app.reservation,'status':status}
                expired = await charging.build(app)
                self.assertIn('Reserva não está mais ativa',texts(expired))
                self.assertIsNone(app.charging_draft['reservation_id'])
                self.assertEqual(app.charging_draft['duration_minutes'],'7')
                self.assertEqual(app.charging_draft['public_code'],'CG-ONE')
                await click(expired,'Continuar sem reserva')(None)
                first = await charging.build(app,**app.go.call_args.kwargs)
                self.assertEqual(app.data['step'],1)
                self.assertEqual(fields(first)['Código temporário do posto'].value,'')
                fields(first)['Código temporário do posto'].value = '54321'
                second = await next_screen(app,first)
                self.assertEqual(fields(second)['Cupom (opcional)'].value,'PROMO')
                third = await next_screen(app,second)
                await click(third,'Solicitar início')(None)
                self.assertEqual(app.posts[0][0],{'presence_code':'#F54321','max_duration_minutes':7,
                                                'coupon_code':'PROMO','public_code':'CG-ONE'})

    async def test_missing_reservation_does_not_unlock_uncertain_post_or_change_identity(self):
        app = WizardApp()
        app.reservation = {**CONTEXT,'id':'reservation','status':'confirmed','connector_id':'point'}
        app.outcomes = [ApiError('Resposta incerta')]
        third = await review_screen(app)
        with self.assertRaises(ApiError):
            await click(third,'Solicitar início')(None)
        original = deepcopy(app.charging_draft['pending_body'])
        app.reservation = None
        resumed = await charging.build(app,step=1)
        self.assertTrue(app.data['pending_start'])
        self.assertEqual(app.data['step'],3)
        self.assertNotIn('Continuar sem reserva',texts(resumed))
        self.assertEqual(app.charging_draft['reservation_id'],'reservation')
        self.assertEqual(app.charging_draft['pending_body'],original)

    async def test_new_conflicting_reservation_prevents_post(self):
        app = WizardApp()
        third = await review_screen(app)
        app.reservation = {'id':'other','status':'confirmed'}
        with self.assertRaisesRegex(ApiError,'reserva ativa'):
            await click(third,'Solicitar início')(None)
        self.assertEqual(app.posts,[])

    async def test_timeout_locks_draft_and_retries_same_body_and_key_after_current_check(self):
        app = WizardApp()
        app.outcomes = [ApiError('Resposta incerta'),{'id':'accepted'}]
        third = await review_screen(app)
        with self.assertRaises(ApiError):
            await click(third,'Solicitar início')(None)
        self.assertTrue(app.charging_draft['uncertain'])
        self.assertTrue(app.data['pending_start'])
        first_body,first_key = app.posts[0]
        # Even a different route or attempted draft mutation cannot create a
        # different operation while the first response is unresolved.
        app.charging_draft['duration_minutes'] = '3'
        recovered_review = await charging.build(app,public_code='CG-OTHER',step=1)
        self.assertEqual(app.data['step'],3)
        self.assertEqual(app.data['public_code'],'CG-ONE')
        app.api.request.reset_mock()
        await click(recovered_review,'Repetir mesmo pedido')(None)
        self.assertEqual(app.posts,[(first_body,first_key),(first_body,first_key)])
        self.assertEqual(app.api.request.call_args_list[0].args,('GET','charging-sessions/current'))
        self.assertIsNone(app.charging_draft)

    async def test_null_current_does_not_unlock_or_discard_uncertain_request(self):
        app = WizardApp()
        app.outcomes = [ApiError('Resposta incerta')]
        third = await review_screen(app)
        with self.assertRaises(ApiError):
            await click(third,'Solicitar início')(None)
        await click(third,'Verificar estado')(None)
        self.assertTrue(app.charging_draft['uncertain'])
        self.assertEqual(len(app.posts),1)

    async def test_auth_or_rate_limit_on_retry_does_not_prove_original_post_failed(self):
        for status in (401,403,429,500):
            with self.subTest(status=status):
                app = WizardApp()
                app.outcomes = [ApiError('Resposta incerta'),ApiError('Tente depois',status)]
                third = await review_screen(app)
                with self.assertRaises(ApiError):
                    await click(third,'Solicitar início')(None)
                with self.assertRaises(ApiError):
                    await click(third,'Repetir mesmo pedido')(None)
                self.assertTrue(app.charging_draft['uncertain'])
                self.assertEqual(app.posts[0],app.posts[1])

    async def test_recovered_active_session_prevents_duplicate_post(self):
        app = WizardApp()
        app.outcomes = [ApiError('Resposta incerta')]
        third = await review_screen(app)
        with self.assertRaises(ApiError):
            await click(third,'Solicitar início')(None)
        app.current = {'id':'accepted','status':'starting'}
        await click(third,'Repetir mesmo pedido')(None)
        self.assertEqual(len(app.posts),1)
        app.go.assert_awaited_with('charging',session_id='accepted')

    async def test_expired_code_returns_to_step_one_without_losing_limits(self):
        app = WizardApp()
        app.outcomes = [ApiError('Código expirou',422,'invalid_presence_code')]
        second = await limits_screen(app)
        fields(second)['Duração máxima (min)'].value = '7'
        third = await next_screen(app,second)
        await click(third,'Solicitar início')(None)
        self.assertFalse(app.charging_draft['uncertain'])
        self.assertFalse(app.data['pending_start'])
        self.assertEqual(app.go.call_args.kwargs['step'],1)
        self.assertEqual(app.charging_draft['duration_minutes'],'7')
        first = await charging.build(app,**app.go.call_args.kwargs)
        fields(first)['Código temporário do posto'].value = '54321'
        second = await next_screen(app,first)
        third = await next_screen(app,second)
        await click(third,'Solicitar início')(None)
        self.assertNotEqual(app.posts[0][1],app.posts[1][1])

    async def test_malformed_post_result_stays_uncertain(self):
        app = WizardApp()
        app.outcomes = [None]
        third = await review_screen(app)
        with self.assertRaises(ApiError):
            await click(third,'Solicitar início')(None)
        self.assertTrue(app.charging_draft['uncertain'])


class SessionProgressTests(unittest.TestCase):
    def test_soc_uses_received_battery_and_timestamps_never_overwrite_it(self):
        self.assertEqual(charging._progress({'soc_percent':42,'max_duration_minutes':30}),(0.42,'Bateria: 42%'))

    def test_time_progress_requires_two_received_timestamps_and_is_labeled_estimate(self):
        session = {'soc_percent':None,'max_duration_minutes':30,'started_at':'2026-09-27T12:00:00Z',
                   'last_measurement_at':'2026-09-27T12:15:00Z'}
        self.assertEqual(charging._progress(session),(0.5,'Tempo estimado: 15 de 30 min'))
        session['last_measurement_at'] = None
        self.assertEqual(charging._progress(session),(None,'Bateria: não disponível'))

    def test_starting_without_measurements_has_no_invented_progress_bar(self):
        card = charging.session_card({'status':'starting','max_duration_minutes':30,'online':True})
        self.assertFalse(any(isinstance(control,ft.ProgressBar) for control in descendants(card)))
        self.assertNotIn('restam',texts(card).lower())
        unavailable = next(control for control in descendants(card)
                           if isinstance(control,ft.Text) and control.value=='Bateria: não disponível')
        self.assertEqual(unavailable.size,13)
