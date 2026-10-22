"""Tarifas do vendedor: tarifa base por conector + tarifa dinâmica (cálculo chargegrid_core.pricing)."""
import unittest
from decimal import Decimal
from types import SimpleNamespace

import flet as ft

from chargegrid_app.screens import tariffs
from chargegrid_app.services import station_settings
from chargegrid_app.services import tariffs as svc
from test_behavior import descendants
from test_station_admin import demo_app, texts


def test_parsers_and_formatting():
    assert svc.parse_decimal('1,89') == Decimal('1.89') and svc.parse_decimal('1.234,50') == Decimal('1234.50')
    assert svc.parse_decimal('') is None and svc.parse_decimal('200', maximum=Decimal(100)) is None
    assert svc.parse_int('30') == 30 and svc.parse_int('1,5') is None and svc.parse_int('0') is None
    assert svc.parse_int('0', minimum=0) == 0
    assert svc.parse_time('18:00') == '18:00' and svc.parse_time('7') == '07:00' and svc.parse_time('25:00') is None
    assert svc.input_number('1.8900') == '1,89' and svc.fmt_money('0.2') == 'R$ 0,20'
    assert svc.multiplier_label('1.30') == '1,3×'


def test_rotation_example():
    rule = {'enabled': True, 'start_after_min': 30, 'interval_min': 10, 'amount': '0.20'}
    assert svc.rotation_intervals(rule, 50) == 2 and svc.rotation_fee({'rotation': rule}, 50) == Decimal('0.40')
    assert svc.rotation_fee({'rotation': {**rule, 'enabled': False}}, 120) == 0


def number_fields(screen):
    return [c for c in descendants(screen) if isinstance(c, ft.TextField) and c.keyboard_type == ft.KeyboardType.NUMBER]


def button(screen, label):
    return next(c for c in descendants(screen) if isinstance(c, ft.Container) and c.on_click
                and isinstance(c.content, (ft.Text, ft.Row)) and label in texts(c))


class TariffScreenTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        station_settings.reset_demo()

    async def asyncSetUp(self):
        self.app = await demo_app()
        self.app.set_poll = lambda callback, interval: setattr(self.app, 'poll', (callback, interval))
        self.app.page = SimpleNamespace(update=lambda: None, show_dialog=lambda d: setattr(self.app, 'dialog', d))
        self.sid = (await self.app.api.request('GET', 'operator/stations'))['items'][0]['id']

    async def asyncTearDown(self):
        await self.app.api.close()

    async def test_overview_shows_current_and_base_tariff_with_reason_and_hides_the_math(self):
        screen = await tariffs.build(self.app, station_id=self.sid)
        copy = texts(screen)
        for label in ('Tarifa', 'Tarifa atual', 'R$ 1,89/kWh', 'Tarifa base: R$ 1,89/kWh', 'Preço normal', 'Detalhes',
                      'Tarifa base', 'Tarifação por horário', 'Nenhum horário', 'Tarifa por demanda', 'Até +50%',
                      'Taxa de permanência'):
            self.assertIn(label, copy)
        for hidden in ('Ocupação agora', 'Recargas na última hora', 'Pressão de demanda', 'Horário de pico'):
            self.assertNotIn(hidden, copy)
        self.assertEqual(number_fields(screen), [])  # sem campos na visão geral
        self.assertEqual(self.app.poll[1], tariffs.REFRESH_SECONDS)
        toggle = next(c for c in descendants(screen) if getattr(c, 'data', None) == 'tariff-details')
        toggle.on_click(None)
        copy = texts(screen)
        for label in ('Como chegamos a este valor', 'Tarifa base R$ 1,89 × demanda 1× = R$ 1,89 por kWh',
                      'Ocupação agora', 'Pressão de demanda', 'Tarifação por horário Nenhum horário'):
            self.assertIn(label, copy)
        await self.app.poll[0]()  # a atualização de 30 s mantém os detalhes abertos
        self.assertIn('Como chegamos a este valor', texts(screen))
        opened = await tariffs.build(self.app, station_id=self.sid, details=True)
        self.assertIn('Ocupação agora', texts(opened))
        legacy = await tariffs.build(self.app, station_id=self.sid, page='peak')  # link antigo
        self.assertIn('Tarifa atual', texts(legacy))

    async def test_base_tariff_subpage_uses_numeric_fields(self):
        screen = await tariffs.build(self.app, station_id=self.sid, page='base')
        field = number_fields(screen)[0]
        self.assertEqual((field.value, field.prefix.value.strip(), field.suffix.value.strip()), ('1,89', 'R$', '/kWh'))
        field.value = '2,10'
        await button(screen, 'Salvar tarifa base').on_click(None)
        station = await self.app.api.request('GET', f'stations/{self.sid}')
        self.assertEqual(station['connectors'][0]['speed_prices']['max'], '2.1000')
        self.assertEqual(station['connectors'][0]['speed_prices']['reduced'], '1.5120')

    async def test_owner_customizes_both_speeds_in_existing_base_menu(self):
        screen = await tariffs.build(self.app, station_id=self.sid, page='base')
        fields = number_fields(screen)
        fields[0].value, fields[1].value = '2,50', '1,35'
        await button(screen, 'Salvar tarifa base').on_click(None)
        data = await self.app.api.request('GET', f'stations/{self.sid}/pricing')
        point = data['connectors'][0]
        self.assertEqual(data['rules']['speed']['prices'][point['id']], {'max':'2.5000','reduced':'1.3500'})
        self.assertEqual(point['speed_prices'], {'max':'2.5000','reduced':'1.3500'})
        reopened = await tariffs.build(self.app, station_id=self.sid, page='base')
        self.assertEqual([f.value for f in number_fields(reopened)][:2], ['2,50','1,35'])
        overview = await tariffs.build(self.app, station_id=self.sid)
        self.assertIn('Máxima R$ 2,50/kWh · Reduzida R$ 1,35/kWh', texts(overview))

    async def test_reduced_cannot_be_equal_or_more_expensive_than_maximum(self):
        for maximum, reduced in [('2','2'),('2','2,1'),('0','1')]:
            screen = await tariffs.build(self.app, station_id=self.sid, page='base')
            fields = number_fields(screen)
            fields[0].value, fields[1].value = maximum, reduced
            await button(screen, 'Salvar tarifa base').on_click(None)
            self.assertIn('deve custar menos', texts(screen))

    async def test_demand_rule_uses_numbers_simulates_and_saves(self):
        screen = await tariffs.build(self.app, station_id=self.sid, page='demand')
        field = number_fields(screen)[0]
        self.assertEqual((field.value, field.prefix.value.strip(), field.suffix.value.strip()), ('50', 'até +', '%'))
        self.assertIn('Simulação (4 carregadores)', texts(screen))
        self.assertIn('1,4×  R$ 2,65/kWh', texts(screen))  # lotado com procura em alta, teto de 50%
        self.assertNotIn('pico', texts(screen))
        field.value = '20'
        field.on_change(None)
        self.assertNotIn('1,4×', texts(screen))
        await button(screen, 'Salvar regra').on_click(None)
        saved = await self.app.api.request('GET', f'stations/{self.sid}/pricing')
        self.assertEqual(saved['rules']['demand']['max_increase_percent'], 20)
        field.value = '150'
        await button(screen, 'Salvar regra').on_click(None)
        self.assertIn('0% a 100%', texts(screen))

    async def _pick(self, screen, label, value):
        box = next(c for c in descendants(screen) if getattr(c, 'data', None) == f'time-{label}')
        await box.on_click(None)
        self.app.dialog.on_change(SimpleNamespace(control=SimpleNamespace(value=value)))

    async def test_schedule_interval_is_added_edited_validated_and_removed(self):
        from datetime import time
        listing = await tariffs.build(self.app, station_id=self.sid, page='schedule')
        self.assertIn('Nenhum horário cadastrado', texts(listing))
        self.assertNotIn('Status', texts(listing))
        self.assertNotIn('Salvar regra', texts(listing))
        editor = await tariffs.build(self.app, station_id=self.sid, page='schedule', interval='new')
        self.assertIn('Novo horário', texts(editor))
        await self._pick(editor, 'Início', time(22, 0))
        await self._pick(editor, 'Fim', time(6, 0))
        for chip in [c for c in descendants(editor) if getattr(c, 'data', None) in ('day-5', 'day-6')]:
            chip.on_click(None)  # Seg a Sex já vêm marcados; marca Sáb e Dom
        prices = number_fields(editor)  # um campo por conector, já com a tarifa base
        self.assertEqual([(f.value, f.prefix.value.strip(), f.suffix.value.strip()) for f in prices][0],
                         ('1,89', 'R$', '/kWh'))
        for field in prices:
            field.value = '1,20'
        await button(editor, 'Salvar horário').on_click(None)
        saved = await self.app.api.request('GET', f'stations/{self.sid}/pricing')
        self.assertEqual(saved['rules']['schedule']['intervals'],
                         [{'start': '22:00', 'end': '06:00', 'days': [0, 1, 2, 3, 4, 5, 6],
                           'prices': {p['id']: '1.2000' for p in saved['connectors']}, 'enabled': True}])
        listing = await tariffs.build(self.app, station_id=self.sid, page='schedule')
        self.assertIn('22:00–06:00', texts(listing))
        self.assertIn('Todos os dias · R$ 1,20/kWh', texts(listing))
        overview = await tariffs.build(self.app, station_id=self.sid)
        self.assertIn('1 horário', texts(overview))
        # Um segundo horário que se sobrepõe: a mensagem da API aparece no editor.
        second = await tariffs.build(self.app, station_id=self.sid, page='schedule', interval='new')
        await self._pick(second, 'Início', time(5, 0))
        await self._pick(second, 'Fim', time(8, 0))
        await button(second, 'Salvar horário').on_click(None)
        self.assertIn('se sobrepõem', texts(second))
        await self._pick(second, 'Fim', time(5, 0))
        await button(second, 'Salvar horário').on_click(None)
        self.assertIn('devem ser diferentes', texts(second))
        edit = await tariffs.build(self.app, station_id=self.sid, page='schedule', interval=0)
        self.assertEqual(number_fields(edit)[0].value, '1,20')
        await button(edit, 'Remover horário').on_click(None)
        saved = await self.app.api.request('GET', f'stations/{self.sid}/pricing')
        self.assertEqual(saved['rules']['schedule']['intervals'], [])

    async def test_active_interval_and_demand_show_in_the_reason_and_details(self):
        point = (await self.app.api.request('GET', f'stations/{self.sid}/pricing'))['connectors'][0]
        whole_week = [{'start': start, 'end': end, 'days': [0, 1, 2, 3, 4, 5, 6], 'prices': {point['id']: '1.20'}}
                      for start, end in (('00:00', '12:00'), ('12:00', '00:00'))]
        await self.app.api.request('PUT', f'stations/{self.sid}/pricing', {'schedule': {'intervals': whole_week}})
        screen = await tariffs.build(self.app, station_id=self.sid, details=True)
        copy = texts(screen)
        self.assertIn('R$ 1,20/kWh', copy)
        self.assertIn('Tarifa base: R$ 1,89/kWh', copy)
        self.assertRegex(copy, r'Horário (00:00–12:00|12:00–00:00)')
        self.assertRegex(copy, r'Tarifa do horário \S+ R\$ 1,20 × demanda 1× = R\$ 1,20 por kWh')
        real = self.app.api._demand
        self.app.api._demand = lambda station: {**real(station), 'multiplier': '1.30', 'level': 'high',
                                                'level_label': 'Alta', 'increase_percent': 30,
                                                'reason': 'demand_schedule',
                                                'reason_label': 'Alta demanda · Horário 12:00–00:00'}
        screen = await tariffs.build(self.app, station_id=self.sid)
        self.assertIn('Alta demanda · Horário 12:00–00:00', texts(screen))
        self.assertIn('R$ 1,56/kWh', texts(screen))  # 1,20 × 1,3
        # Cada intervalo tem seu status; desligar um preserva o outro.
        listing = await tariffs.build(self.app, station_id=self.sid, page='schedule')
        self.assertNotIn('Status', texts(listing))
        for index in range(2):
            editor = await tariffs.build(self.app, station_id=self.sid, page='schedule', interval=index)
            self.assertIn('Status', texts(editor))
            await button(editor, 'Inativa').on_click(None)
            await button(editor, 'Salvar horário').on_click(None)
            saved = await self.app.api.request('GET', f'stations/{self.sid}/pricing')
            self.assertEqual([item['enabled'] for item in saved['rules']['schedule']['intervals']],
                             [False, index == 0])
        self.app.api._demand = real
        saved = await self.app.api.request('GET', f'stations/{self.sid}/pricing')
        self.assertTrue(saved['rules']['schedule']['enabled'])
        self.assertEqual(saved['connectors'][0]['current_price_per_kwh'], '1.8900')
        listing = await tariffs.build(self.app, station_id=self.sid, page='schedule')
        self.assertEqual(texts(listing).count('Inativa'), 2)

    async def test_legacy_disabled_schedule_moves_status_without_reactivating_other_intervals(self):
        point = (await self.app.api.request('GET', f'stations/{self.sid}/pricing'))['connectors'][0]
        intervals = [{'start': start, 'end': end, 'days': [0], 'prices': {point['id']: '1.20'}}
                     for start, end in (('08:00', '10:00'), ('10:00', '12:00'))]
        await self.app.api.request('PUT', f'stations/{self.sid}/pricing',
                                   {'schedule': {'enabled': False, 'intervals': intervals}})
        editor = await tariffs.build(self.app, station_id=self.sid, page='schedule', interval=0)
        await button(editor, 'Ativa').on_click(None)
        await button(editor, 'Salvar horário').on_click(None)
        saved = await self.app.api.request('GET', f'stations/{self.sid}/pricing')
        self.assertTrue(saved['rules']['schedule']['enabled'])
        self.assertEqual([item['enabled'] for item in saved['rules']['schedule']['intervals']], [True, False])

    async def test_rotation_fields(self):
        rotation = await tariffs.build(self.app, station_id=self.sid, page='rotation')
        after, every, amount = number_fields(rotation)[:3]  # + Teto quando a API devolve max_amount
        self.assertEqual([after.suffix.value.strip(), every.suffix.value.strip(), amount.prefix.value.strip()],
                         ['min', 'min', 'R$'])
        self.assertIn('2 intervalos × R$ 1,00 = R$ 2,00', texts(rotation))


class DriverDynamicPriceTests(unittest.IsolatedAsyncioTestCase):
    async def test_driver_sees_the_dynamic_price_and_the_session_locks_it(self):
        from chargegrid_app.screens import booking
        from chargegrid_app.services import booking as rules
        from chargegrid_app.ui.point_summary import point_context, point_summary

        app = await demo_app()
        real = app.api._demand
        app.api._demand = lambda station: {**real(station), 'multiplier': '1.30', 'level_label': 'Alta',
                                           'level': 'high', 'increase_percent': 30}
        station = (await app.api.request('GET', 'stations', params={'limit': 5, 'offset': 0}))['items'][0]
        point = station['connectors'][0]
        self.assertEqual(point['dynamic_price_per_kwh'], str((Decimal(point['price_per_kwh']) * Decimal('1.30'))
                                                                .quantize(Decimal('0.0001'))))
        group = rules.group_connectors(station)[0]
        self.assertEqual(group['price'], Decimal(point['dynamic_price_per_kwh']))
        context = point_context(station, point)
        self.assertEqual((context['connector']['price_per_kwh'], context['connector']['base_price_per_kwh'],
                          context['demand_multiplier']), (point['dynamic_price_per_kwh'], point['price_per_kwh'], '1.30'))
        screen = await booking.build(app, step=1, station_id=station['id'])
        # O acréscimo por demanda é do vendedor: o motorista vê só o preço final (etapa de potência).
        self.assertNotIn('demanda', texts(screen).lower())
        self.assertNotIn('1,3×', texts(screen))
        self.assertNotIn('demand-note', [getattr(item, 'data', None) for item in descendants(screen)])
        summary = texts(point_summary(context))
        self.assertIn('/kWh', summary)
        self.assertNotIn('demanda', summary)
        self.assertNotIn('1,3', summary)
        session = await app.api.request('POST', 'charging-sessions', {
            'presence_code': '#F12345', 'public_code': point['public_code'], 'max_duration_minutes': 30}, key='surge')
        self.assertEqual((session['demand_multiplier'], session['price_per_kwh'], session['base_price_per_kwh']),
                         ('1.30', point['dynamic_price_per_kwh'], point['price_per_kwh']))
        await app.api.close()

    async def test_schedule_price_without_demand_is_not_labelled_as_demand(self):
        from chargegrid_app.ui.point_summary import point_context, point_summary

        station_settings.reset_demo()
        app = await demo_app()
        sid = (await app.api.request('GET', 'operator/stations'))['items'][0]['id']
        points = (await app.api.request('GET', f'stations/{sid}/pricing'))['connectors']
        whole_week = [{'start': start, 'end': end, 'days': [0, 1, 2, 3, 4, 5, 6],
                       'prices': {p['id']: '1.20' for p in points}} for start, end in (('00:00', '12:00'), ('12:00', '00:00'))]
        await app.api.request('PUT', f'stations/{sid}/pricing', {'schedule': {'intervals': whole_week}})
        station = await app.api.request('GET', f'stations/{sid}')
        point = station['connectors'][0]
        self.assertEqual((point['current_base_price_per_kwh'], point['dynamic_price_per_kwh']), ('1.2000', '1.2000'))
        self.assertEqual(station['demand']['reason'], 'schedule')
        context = point_context(station, point)
        self.assertNotIn('demand_multiplier', context)
        copy = texts(point_summary(context))
        self.assertIn('(tarifa do horário)', copy)
        self.assertNotIn('demanda 1×', copy)
        # Recarga sem reserva trava a base do horário.
        session = await app.api.request('POST', 'charging-sessions', {
            'presence_code': '#F12345', 'public_code': point['public_code'], 'max_duration_minutes': 30}, key='night')
        self.assertEqual((session['base_price_per_kwh'], session['price_per_kwh'], session['demand_multiplier']),
                         ('1.2000', '1.2000', '1.00'))
        await app.api.close()
