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

    async def test_overview_shows_live_demand_base_tariff_and_rules(self):
        screen = await tariffs.build(self.app, station_id=self.sid)
        copy = texts(screen)
        for label in ('Tarifas', 'Demanda agora', 'Baixa', 'Preço agora: R$ 1,89/kWh', 'Ocupação agora',
                      'Recargas na última hora', 'Tarifa base', 'Tarifa por demanda', 'Até +50%',
                      'Horário de pico', '18:00–21:00 · Todos os dias', 'Taxa de rotatividade'):
            self.assertIn(label, copy)
        self.assertEqual(self.app.poll[1], tariffs.REFRESH_SECONDS)
        # Tarifa base: campo numérico com R$ … /kWh (não um texto livre).
        field = number_fields(screen)[0]
        self.assertEqual((field.value, field.prefix.value.strip(), field.suffix.value.strip()), ('1,89', 'R$', '/kWh'))
        field.value = '2,10'
        await button(screen, 'Salvar tarifa base').on_click(None)
        station = await self.app.api.request('GET', f'stations/{self.sid}')
        self.assertEqual(station['connectors'][0]['price_per_kwh'], '2.1000')

    async def test_demand_rule_uses_numbers_simulates_and_saves(self):
        screen = await tariffs.build(self.app, station_id=self.sid, page='demand')
        field = number_fields(screen)[0]
        self.assertEqual((field.value, field.prefix.value.strip(), field.suffix.value.strip()), ('50', 'até +', '%'))
        self.assertIn('Simulação (4 conectores)', texts(screen))
        self.assertIn('1,4×  R$ 2,65/kWh', texts(screen))  # lotado com procura em alta, teto de 50%
        field.value = '20'
        field.on_change(None)
        self.assertNotIn('1,4×', texts(screen))
        await button(screen, 'Salvar regra').on_click(None)
        saved = await self.app.api.request('GET', f'stations/{self.sid}/pricing')
        self.assertEqual(saved['rules']['demand']['max_increase_percent'], 20)
        field.value = '150'
        await button(screen, 'Salvar regra').on_click(None)
        self.assertIn('0% a 100%', texts(screen))

    async def test_peak_days_toggle_and_rotation_fields(self):
        screen = await tariffs.build(self.app, station_id=self.sid, page='peak')
        chips = [c for c in descendants(screen) if isinstance(c, ft.Container) and c.on_click
                 and isinstance(c.content, ft.Text) and c.content.value in ('Sáb', 'Dom')]
        for chip in chips:
            chip.on_click(None)
        await button(screen, 'Salvar regra').on_click(None)
        saved = await self.app.api.request('GET', f'stations/{self.sid}/pricing')
        self.assertEqual(saved['rules']['peak']['days'], [0, 1, 2, 3, 4])
        rotation = await tariffs.build(self.app, station_id=self.sid, page='rotation')
        after, every, amount = number_fields(rotation)
        self.assertEqual([after.suffix.value.strip(), every.suffix.value.strip(), amount.prefix.value.strip()],
                         ['min', 'min', 'R$'])
        self.assertIn('2 intervalos × R$ 0,20 = R$ 0,40', texts(rotation))


class DriverDynamicPriceTests(unittest.IsolatedAsyncioTestCase):
    async def test_driver_sees_the_dynamic_price_and_the_session_locks_it(self):
        from chargegrid_app.screens import booking
        from chargegrid_app.services import booking as rules
        from chargegrid_app.ui.point_summary import point_context

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
        self.assertIn('Demanda alta agora: tarifa 1,3× a base', texts(screen))
        session = await app.api.request('POST', 'charging-sessions', {
            'presence_code': '#F12345', 'public_code': point['public_code'], 'max_duration_minutes': 30}, key='surge')
        self.assertEqual((session['demand_multiplier'], session['price_per_kwh'], session['base_price_per_kwh']),
                         ('1.30', point['dynamic_price_per_kwh'], point['price_per_kwh']))
        await app.api.close()
