"""Assistente de recarga (rota ``booking``): regras puras e fluxo completo na conta demo."""

import unittest
from datetime import datetime
from decimal import Decimal

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import booking
from chargegrid_app.services import booking as rules
from chargegrid_app.services import vehicle_state, wallet
from test_behavior import HandlerApp, descendants

STATION = {'id': 's1', 'active': True, 'name': 'Villa Lobos', 'address': 'Av. Prof Fonseca Rodrigues, 4777',
           'connectors': [
               {'id': 'a', 'connector_type': 'CCS2', 'power_kw': '60.000', 'price_per_kwh': '1.89', 'available': True,
                'online': True, 'active': True},
               {'id': 'b', 'connector_type': 'CCS2', 'power_kw': '60.000', 'price_per_kwh': '1.89', 'available': False,
                'online': True, 'active': True},
               {'id': 'c', 'connector_type': 'Tipo 2', 'power_kw': '22.000', 'price_per_kwh': '1.50', 'available': True,
                'online': True, 'active': True},
               {'id': 'd', 'connector_type': 'Tipo 2', 'power_kw': '22.000', 'price_per_kwh': '1.50', 'available': True,
                'online': True, 'active': True}]}


def texts(control):
    return [str(item.value) for item in descendants(control) if isinstance(item, ft.Text)]


def tap(screen, label):
    for item in descendants(screen):
        if getattr(item, 'on_click', None) and any(
                isinstance(sub, ft.Text) and sub.value == label for sub in descendants(item)):
            return item.on_click
    raise AssertionError(f'sem controle {label!r}')


class RulesTests(unittest.TestCase):
    def test_groups_titles_and_free_counts(self):
        groups = rules.group_connectors(STATION)
        self.assertEqual([rules.group_title(g) for g in groups], ['CCS2 - 60 kW', 'Tipo 2 - 22 kW'])
        self.assertEqual([rules.group_subtitle(g) for g in groups], ['1 de 2 conectores livre', '2 conectores livres'])

    def test_price_by_time_matches_reference_total(self):
        result = rules.estimate(60, '1.89', minutes=30)
        self.assertEqual((result['energy_kwh'], result['cost']), (Decimal('30.00'), Decimal('56.70')))
        self.assertEqual(rules.money(rules.total(result['cost'], False)), 'R$56,70')
        self.assertEqual(rules.total(result['cost'], True), Decimal('61.60'))

    def test_price_by_value_derives_minutes(self):
        result = rules.estimate(60, '1.89', value='56,70')
        self.assertEqual(result['minutes'], 30)
        self.assertEqual(result['cost'], Decimal('56.70'))

    def test_parsing_and_formatting(self):
        self.assertEqual(rules.parse_value('249,90'), Decimal('249.90'))
        self.assertEqual(rules.parse_value('1.249,90'), Decimal('1249.90'))
        self.assertEqual(rules.parse_minutes(' 30 '), 30)
        for bad in ('', 'abc', '0', '-5', '2,5'):
            with self.assertRaises(ValueError):
                rules.parse_minutes(bad)
        with self.assertRaises(ValueError):
            rules.parse_value('0')
        self.assertEqual(rules.money('1234.5'), 'R$1.234,50')
        self.assertEqual(rules.fmt_number('7.200'), '7,2')

    def test_power_options_use_effective_and_car_limit(self):
        station = {**STATION, 'connectors': [dict(p) for p in STATION['connectors']]}
        for point in station['connectors'][:2]:
            point['effective_power_kw'] = '40.000'
        ccs, ac = rules.group_connectors(station)
        car = {'max_ac_kw': 6.6, 'max_dc_kw': 60}
        self.assertEqual(rules.power_title(ccs, 'max', car), 'Até 40 kW · limitado pelo posto')
        self.assertEqual(rules.power_options(ccs, car)['reduced'][0], Decimal('20.0'))
        self.assertEqual(rules.power_title(ac, 'max', car), 'Até 6,6 kW · limite do seu carro')
        self.assertEqual(rules.power_title(ac, 'max'), 'Até 22 kW')  # sem carro: o conector
        # A estimativa usa a potência do motorista: 30 min a 40 kW = 20 kWh.
        quote = rules.estimate(rules.power_options(ccs, car)['max'][0], ccs['price'], minutes=30)
        self.assertEqual(quote['energy_kwh'], Decimal('20.00'))

    def test_speed_tariff_uses_explicit_choice_and_owner_values_not_effective_power(self):
        point = {**STATION['connectors'][0], 'effective_power_kw':'15',
                 'speed_prices':{'max':'2.50','reduced':'1.25'}}
        group = rules.group_connectors({**STATION,'connectors':[point]})[0]
        self.assertEqual(rules.group_price(group,'max'),Decimal('2.50'))
        self.assertEqual(rules.group_price(group,'reduced'),Decimal('1.25'))
        energy = Decimal('10')
        self.assertEqual(rules.estimate(15,rules.group_price(group,'max'),energy=energy)['cost'],Decimal('25.00'))
        self.assertEqual(rules.estimate(7.5,rules.group_price(group,'reduced'),energy=energy)['cost'],Decimal('12.50'))
        point['effective_power_kw'] = '5'  # grid sharing cannot award the reduced commercial tariff
        self.assertEqual(rules.tier_price(point,'max'),Decimal('2.50'))
        self.assertEqual(rules.tier_price({'price_per_kwh':'2'},'reduced'),Decimal('1.60'))

    def test_autonomy_helpers_remain_public_after_shared_plan_extraction(self):
        self.assertEqual(rules.parse_km('100 km'),100)
        plan = rules.autonomy_energy(100,14,20,40)
        self.assertEqual(plan['energy_kwh'],Decimal('14.000'))
        self.assertIsNone(rules.autonomy_note(plan))

    def test_time_slots_are_future_half_hours(self):
        self.assertEqual(rules.time_slots(datetime(2026, 10, 18, 12, 5)), ['12:30', '13:00', '13:30'])
        self.assertEqual(rules.time_slots(datetime(2026, 10, 18, 12, 25)), ['13:00', '13:30', '14:00'])
        self.assertEqual(rules.time_slots(datetime(2026, 10, 18, 23, 40))[0], '00:00')

    def test_reservation_code_is_stable(self):
        self.assertEqual(rules.reservation_code('x'), rules.reservation_code('x'))
        self.assertRegex(rules.reservation_code('demo-reservation-9'), r'^CG-\d{4}$')


class AmountLimitsTests(unittest.TestCase):
    """Máximos por modo, atalhos e erros do campo (mostrados antes de enviar)."""

    def group(self, **extra):
        station = {**STATION, 'connectors': [{**point, **extra.get(point['id'], {})} for point in STATION['connectors']]}
        return rules.group_connectors(station)

    def test_selected_connector_limit_is_used_not_the_first_of_the_group(self):
        fast = self.group(a={'max_duration_minutes': 120}, b={'max_duration_minutes': 30})[0]
        self.assertEqual(rules.group_limits(fast, 'max', 'a')['minutes'], 120)
        tipo2 = self.group(c={'max_duration_minutes': 90}, d={'max_duration_minutes': 45})[1]
        self.assertEqual(rules.group_limits(tipo2, 'max', 'd')['minutes'], 45)
        self.assertEqual(rules.group_limits(tipo2, 'max', None)['minutes'], 90)  # sem escolha: o primeiro livre
        self.assertEqual(rules.point_minutes({}), 1440)

    def test_maxima_follow_time_power_price_and_battery(self):
        group = self.group(c={'max_duration_minutes': 60})[1]  # Tipo 2 · 22 kW · R$1,50
        free = rules.group_limits(group, 'max', 'c')
        self.assertEqual((free['minutes'], free['value'], free['bound']), (60, Decimal('33.00'), 'time'))
        self.assertEqual(rules.amount_hint('value', free), 'Máx.: R$ 33,00 · o que cabe em 60 min a 22 kW')
        car = {'consumption': 14.0, 'usable_kwh': 44.9, 'soc': 80}  # 8,98 kWh livres
        full = rules.group_limits(group, 'max', 'c', car=car)
        self.assertEqual((full['value'], full['km'], full['bound']), (Decimal('13.47'), 64, 'battery'))
        self.assertEqual(rules.amount_hint('autonomy', full), 'Máx.: 64 km · o que cabe na bateria do seu carro')
        self.assertEqual(rules.amount_hint('time', full), 'Máx.: 60 min (limite deste carregador)')
        reduced = rules.group_limits(group, 'reduced', 'c')  # metade da potência e tarifa reduzida (80%)
        self.assertEqual(reduced['value'], Decimal('13.20'))

    def test_presets_hide_values_above_the_maximum_and_end_with_max(self):
        limits = rules.amount_limits(22, '1.50', 60, {'consumption': 14.0, 'usable_kwh': 44.9, 'soc': 80})
        self.assertEqual(rules.amount_presets('time', limits),
                         [('15 min', '15'), ('30 min', '30'), ('Máx. 60 min', '60')])
        self.assertEqual(rules.amount_presets('value', limits), [('Máx. R$ 13,47', '13,47')])
        self.assertEqual(rules.amount_presets('autonomy', limits), [('50 km', '50'), ('Máx. 64 km', '64')])
        roomy = rules.amount_limits(60, '1.89', 120)
        self.assertEqual([label for label, _ in rules.amount_presets('value', roomy)],
                         ['R$ 20', 'R$ 50', 'R$ 100', 'Máx. R$ 226,80'])
        self.assertEqual(rules.amount_presets('autonomy', roomy), [])  # sem carro: autonomia sem máximo

    def test_errors_while_typing(self):
        limits = rules.amount_limits(22, '1.50', 60, {'consumption': 14.0, 'usable_kwh': 44.9, 'soc': 80})
        self.assertIsNone(rules.amount_error('time', '', limits))
        self.assertIsNone(rules.amount_error('time', '60', limits))
        self.assertEqual(rules.amount_error('time', '500', limits),
                         'Acima do máximo (60 min). Toque em Máx. ou diminua.')
        self.assertIsNone(rules.amount_error('value', '13,47', limits))
        self.assertIn('Acima do máximo (R$ 13,47)', rules.amount_error('value', '13,48', limits))
        self.assertIn('Acima do máximo (64 km)', rules.amount_error('autonomy', '65', limits))
        self.assertIn('minutos inteiros', rules.amount_error('time', '1,5', limits))
        self.assertEqual(rules.clamp_text('value', '50,00', limits), '13,47')
        self.assertEqual(rules.clamp_text('time', '30', limits), '30')
        full = rules.amount_limits(22, '1.50', 60, {'consumption': 14.0, 'usable_kwh': 44.9, 'soc': 100})
        self.assertIn('bateria do carro já está cheia', rules.amount_error('autonomy', '10', full))
        free = rules.amount_limits(22, '0', 60)
        self.assertEqual(rules.amount_presets('value', free), [])
        self.assertIn('não cobra pela energia', rules.amount_hint('value', free))

    def test_maximum_value_and_km_fit_the_time_limit_in_the_estimate(self):
        for power, price, minutes, soc in ((60, '1.89', 120, 15), (7.4, '2.37', 37, 10), (22, '1.13', 45, 59.9)):
            limits = rules.amount_limits(power, price, minutes, {'consumption': 14.0, 'usable_kwh': 44.9, 'soc': soc})
            by_value = rules.estimate(power, price, value=limits['value'])
            self.assertLessEqual(by_value['minutes'], minutes)
            km = rules.autonomy_energy(limits['km'], 14.0, soc, 44.9)
            self.assertFalse(km['capped'])
            self.assertLessEqual(rules.estimate(power, price, energy=km['energy_kwh'])['minutes'], minutes)


class BookingFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        wallet.reset_demo()
        self.app = HandlerApp()
        self.app.api = DemoApi(clock=lambda: 0.0)
        await self.app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.app.profile = await self.app.api.request('GET', 'me')
        self.app.back = lambda event=None: None
        self.sid = 'demo-station-1'

    async def screen(self, step, **kwargs):
        return await booking.build(self.app, step=step, station_id=self.sid, **kwargs)

    async def test_booking_reduced_price_and_payment_reservation_keep_the_chosen_tier(self):
        self.sid = (await self.app.api.request('GET','operator/stations'))['items'][0]['id']
        station = await self.app.api.request('GET',f'stations/{self.sid}')
        point = station['connectors'][0]
        await self.app.api.request('PUT',f'stations/{self.sid}/pricing',
                                   {'speed':{'prices':{point['id']:{'max':'3','reduced':'1.50'}}}})
        power = await self.screen(4,kind='now',pick=1,power='reduced',amount='30')
        self.assertIn('Mais econômica · R$1,50/kWh',' '.join(texts(power)))
        self.assertIn('Mais rápida · R$3,00/kWh',' '.join(texts(power)))
        review = await self.screen(6)
        self.assertIn('Mais econômica · R$1,50/kWh',texts(review))
        await tap(review,'Confirmar e iniciar no ponto')()
        intent = self.app.go.await_args.kwargs['planning_intent']
        self.assertEqual(intent['power_tier'],'reduced')
        reduced = await self.app.api.request('POST','payments',
            {'connector_id':point['id'],'mode':'energy','energy_kwh':'10','power_tier':'reduced'},key='reduced')
        maximum = await self.app.api.request('POST','payments',
            {'connector_id':point['id'],'mode':'energy','energy_kwh':'10','power_tier':'max'},key='maximum')
        self.assertEqual((reduced['energy_cap'],maximum['energy_cap']),('15.00','30.00'))
        self.assertEqual(reduced['power_tier'],'reduced')
        self.assertEqual(maximum['power_tier'],'max')
        reservation = await self.app.api.request('POST','reservations',
            {'connector_id':point['id'],'power_tier':'reduced'},key='reserve-reduced')
        await self.app.api.request('PUT',f'stations/{self.sid}/pricing',
                                   {'speed':{'prices':{point['id']:{'max':'5','reduced':'2'}}}})
        current = await self.app.api.request('GET','reservations/current')
        self.assertEqual(current['id'],reservation['id'])
        self.assertEqual(current['power_tier'],'reduced')
        self.assertEqual(Decimal(current['connector']['price_per_kwh']),Decimal('1.50'))

    async def test_without_station_offers_search(self):
        screen = await booking.build(self.app, step=1)
        self.assertIn('Buscar estação', texts(screen))

    async def test_step_one_requires_a_connector(self):
        screen = await self.screen(1)
        self.assertIn('Qual conector deseja reservar?', texts(screen))  # padrão: Reservar estação
        with self.assertRaises(AssertionError):  # desabilitado: sem ação até escolher um conector
            tap(screen, 'Continuar')

    async def test_two_flows_reserve_holds_fifteen_minutes_and_now_skips_the_reservation_step(self):
        reserve = await self.screen(2, kind='reserve')
        copy = ' '.join(texts(reserve))
        self.assertIn('Reservar estação', copy)
        self.assertIn('Ponto reservado por 15 minutos', copy)
        spans = [span.text for item in descendants(reserve) if isinstance(item, ft.Text) for span in item.spans or []]
        self.assertEqual(spans, ['Taxa de reserva: ', rules.money(rules.RESERVATION_FEE)])
        for removed in ('Horários disponíveis', 'Agora'):  # sem horários fictícios e sem alternar o fluxo aqui
            self.assertNotIn(removed, texts(reserve))
        now = await self.screen(1, kind='now', pick=1)
        self.assertIn('Qual conector deseja usar?', texts(now))
        await tap(now, 'Continuar')()
        self.assertEqual(self.app.go.await_args.kwargs['step'], 3)  # Carregar agora: direto para a cobrança
        back = await self.screen(2)  # voltar da cobrança não mostra a etapa de reserva
        self.assertIn('Qual conector deseja usar?', texts(back))
        self.app.booking['minutes_text'] = '30'
        review = await self.screen(6)
        self.assertIn('Por tempo | Carregar agora', texts(review))
        self.assertIn('30 minutos | Início no ponto com o código #F', texts(review))
        self.assertIn('Confirmar e iniciar no ponto', texts(review))

    async def test_capture_presets_open_selected_and_unselected_states(self):
        picked = await self.screen(1, pick=1)  # estado da referência «estacao_5»: CCS2 marcado, Continuar ativo
        self.assertTrue(callable(tap(picked, 'Continuar')))
        self.app.booking = None
        none = await self.screen(4, power='none')  # «estacao_10»: nenhuma potência marcada
        self.assertIn('Até 60 kW', texts(none))
        self.assertIsNone(self.app.booking['power'])
        review = await self.screen(6)  # potência sem escolha cai na máxima; pagamento no saldo
        self.assertIn('Revisar Dados', texts(review))
        self.assertIn('Até 60 kW', texts(review))

    async def test_reserve_with_balance_creates_reservation_and_debits(self):
        before = wallet.balance(self.app)
        screen = await self.screen(1)
        await tap(screen, next(t for t in texts(screen) if ' - ' in t))()
        screen = await self.screen(1)
        await tap(screen, 'Continuar')()
        self.assertEqual(self.app.go.await_args.kwargs['step'], 2)
        self.app.booking['minutes_text'] = '30'
        screen = await self.screen(6)
        self.assertIn('Confirmar reserva', texts(screen))
        self.assertFalse(any('taxa de reserva' in t for t in texts(screen)))  # sem linha extra (igual à referência)
        self.assertEqual(wallet.balance(self.app), before)
        await tap(screen, 'Confirmar reserva' if self.app.booking['mode'] == 'reserve' else 'Confirmar e iniciar no ponto')()
        self.assertEqual(self.app.go.await_args.args[0], 'booking')
        self.assertEqual(self.app.go.await_args.kwargs['step'], 8)
        result = self.app.booking['result']
        self.assertRegex(result['code'], r'^CG-\d{4}$')
        current = await self.app.api.request('GET', 'reservations/current')
        self.assertEqual(current['id'], result['id'])
        self.assertEqual(wallet.balance(self.app), before - Decimal(result['paid']))
        self.assertGreater(Decimal(result['paid']), rules.total(0, False))  # total inclui a taxa de reserva
        done = await self.screen(8)
        self.assertIn('Reserva confirmada', texts(done))
        await tap(done, 'Cancelar Recarga')()
        self.assertEqual(wallet.balance(self.app), before)

    async def test_insufficient_balance_blocks_payment(self):
        wallet.debit(self.app, wallet.balance(self.app) - Decimal('1.00'), 'teste')
        await self.screen(1)
        self.app.booking['minutes_text'] = '30'
        screen = await self.screen(5)
        with self.assertRaises(ApiError):
            await tap(screen, 'Continuar')()

    async def test_power_step_shows_station_limit_and_hands_it_to_charging(self):
        for point in self.app.api._points.values():
            if point['station_id'] == self.sid and point['connector_type'] == 'CCS2':
                point['power_limit_kw'] = '40.000'
        await self.screen(1, pick=1)
        screen = await self.screen(4)
        self.assertIn('Até 40 kW · limitado pelo posto', texts(screen))
        self.app.booking.update(mode='now', minutes_text='20', pay='balance')
        await tap(await self.screen(6), 'Confirmar e iniciar no ponto')()
        self.assertEqual(self.app.go.await_args.kwargs['planning_intent']['max_power_kw'], '40.000')

    async def test_now_hands_off_to_charging(self):
        await self.screen(1)
        self.app.booking.update(mode='now', minutes_text='20', pay='balance')
        screen = await self.screen(6)
        await tap(screen, 'Confirmar reserva' if self.app.booking['mode'] == 'reserve' else 'Confirmar e iniciar no ponto')()
        self.assertEqual(self.app.go.await_args.args[0], 'charging')
        self.assertIn('point_context', self.app.go.await_args.kwargs)

    async def test_payment_step_offers_balance_and_stripe_and_never_a_card_form(self):
        await self.screen(1)
        self.app.booking.update(mode='now', minutes_text='20', pay='card')  # atalho antigo vira Stripe
        options = texts(await self.screen(5))
        self.assertIn('Saldo Disponível', options)  # Saldo: só na conta demo
        self.assertIn('Cartão ou Pix · Stripe', options)
        for removed in ('Pix', 'Cartão de Crédito / Débito'):
            self.assertNotIn(removed, options)
        self.assertEqual(self.app.booking['pay'], 'stripe')
        waiting = await self.screen(7)  # sem pagamento criado: volta para a revisão, sem formulário
        self.assertFalse([c for c in descendants(waiting) if isinstance(c, ft.TextField)])
        for removed in ('Número do cartão', 'CVV', 'Validade', 'Efetuar Pagamento'):
            self.assertNotIn(removed, texts(waiting))

    async def amount_screen(self, by):
        self.app.booking = None
        vehicle_state.set_simulated_soc(self.app, 40)  # 60% livres de 44,9 kWh = 26,94 kWh (escondido)
        return await self.screen(3, kind='now', pick=1, by=by)

    async def test_amount_step_shows_maxima_units_and_presets_before_submitting(self):
        time = await self.amount_screen('time')  # CCS2 60 kW · 120 min no ponto demo
        self.assertIn('Máx.: 120 min (limite deste carregador)', texts(time))
        chips = [label for label in texts(time) if label.endswith(' min')]
        self.assertEqual(chips, ['15 min', '30 min', '60 min', 'Máx. 120 min'])
        field = next(c for c in descendants(time) if isinstance(c, ft.TextField))
        self.assertEqual((field.prefix, field.suffix.value), (None, ' min'))
        await tap(time, 'Máx. 120 min')()
        self.assertEqual((field.value, self.app.booking['minutes_text']), ('120', '120'))

        value = await self.amount_screen('value')
        field = next(c for c in descendants(value) if isinstance(c, ft.TextField))
        self.assertEqual((field.prefix.value, field.suffix), ('R$ ', None))
        self.assertIn('Máx.: R$ 50,91 · o que cabe na bateria do seu carro', texts(value))  # 26,94 kWh x R$1,89
        self.assertEqual([label for label in texts(value) if label.startswith(('R$ ', 'Máx. R$'))],
                         ['R$ 20', 'R$ 50', 'Máx. R$ 50,91'])
        self.assertNotIn('40', ' '.join(texts(value)))  # o SoC nunca aparece

        km = await self.amount_screen('autonomy')
        self.assertIn('Máx.: 192 km · o que cabe na bateria do seu carro', texts(km))
        self.assertIn('Máx. 192 km', texts(km))
        self.assertNotIn('200 km', texts(km))  # atalho acima do máximo não aparece

    async def test_value_above_the_maximum_is_flagged_while_typing_and_blocks_next(self):
        screen = await self.amount_screen('value')
        field = next(c for c in descendants(screen) if isinstance(c, ft.TextField))
        error = next(c for c in descendants(screen) if getattr(c, 'data', None) == 'amount-error')
        self.assertFalse(error.visible)
        field.value = '5000'
        field.on_change(type('Event', (), {'control': field})())
        self.assertTrue(error.visible)
        self.assertEqual(error.value, 'Acima do máximo (R$ 50,91). Toque em Máx. ou diminua.')
        with self.assertRaisesRegex(ApiError, 'Acima do máximo'):
            await tap(screen, 'Próximo Passo')()
        self.app.go.assert_not_called()
        field.value = '50,91'
        field.on_change(type('Event', (), {'control': field})())
        self.assertFalse(error.visible)
        await tap(screen, 'Próximo Passo')()
        self.assertEqual(self.app.go.await_args.kwargs['step'], 4)

    async def test_time_above_the_point_limit_never_reaches_the_old_after_click_message(self):
        screen = await self.amount_screen('time')
        field = next(c for c in descendants(screen) if isinstance(c, ft.TextField))
        field.value = '500'
        field.on_change(type('Event', (), {'control': field})())
        self.assertIn('Acima do máximo (120 min). Toque em Máx. ou diminua.', texts(screen))
        with self.assertRaisesRegex(ApiError, r'Acima do máximo \(120 min\)'):
            await tap(screen, 'Próximo Passo')()

    async def test_reduced_speed_rechecks_the_amount_against_its_own_maximum(self):
        await self.amount_screen('value')
        self.app.booking.update(value_text='50,91', power='reduced')
        power = await self.screen(4)  # metade da potência e tarifa menor: o máximo cai
        with self.assertRaisesRegex(ApiError, r'Na velocidade reduzida o máximo é R\$ '):
            await tap(power, 'Continuar')()
        self.app.booking['power'] = 'max'
        await tap(await self.screen(4), 'Continuar')()
        self.assertEqual(self.app.go.await_args.kwargs['step'], 5)

    async def test_deep_link_to_review_clamps_the_amount_to_the_maximum(self):
        await self.amount_screen('time')
        self.app.booking['minutes_text'] = '900'
        review = await self.screen(6)
        self.assertEqual(self.app.booking['minutes_text'], '120')
        self.assertIn('120 minutos | Início no ponto com o código #F', texts(review))

    async def test_step_one_never_shows_the_demand_surcharge(self):
        real = self.app.api._demand
        self.app.api._demand = lambda station: {**real(station), 'multiplier': '1.30', 'level_label': 'Alta'}
        screen = await self.screen(1)
        self.assertFalse([text for text in texts(screen) if 'emanda' in text or '×' in text])
        self.assertNotIn('demand-note', [getattr(item, 'data', None) for item in descendants(screen)])


if __name__ == '__main__':
    unittest.main()
