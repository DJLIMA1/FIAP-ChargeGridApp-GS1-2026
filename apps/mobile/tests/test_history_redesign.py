"""Histórico redesenhado: consumidor (por data) e vendedor (receita, energia, gráfico, página de consumo)."""

import unittest

import flet as ft

from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import history, history_owner
from test_behavior import HandlerApp, descendants


def texts(screen):
    return '\n'.join(str(c.value) for c in descendants(screen) if isinstance(c, ft.Text))


class HistoryRedesignTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = HandlerApp()
        self.app.api = DemoApi()
        await self.app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.app.profile = await self.app.api.request('GET', 'me')
        self.app.profile['operator_enabled'] = True

    async def test_consumer_rows_are_grouped_by_date(self):
        text = texts(await history.build(self.app))
        self.assertRegex(text, r'DATA: \d{2}/\d{2}/\d{4}')
        self.assertRegex(text, r'\d{2}:\d{2}')

    async def test_vendor_dashboard_uses_real_numbers_in_pt_br(self):
        text = texts(await history.build(self.app, manage=True))
        for expected in ('Receita total', 'Energia vendida', 'Consumo de Energia', 'Recargas', 'Ticket médio',
                         'Estações ativas', 'Últimos 7 dias', 'Fale com o ChatBot'):
            self.assertIn(expected, text)
        self.assertRegex(text, r'R\$ [\d.]+\n')
        self.assertRegex(text, r'\d+ de \d+')

    async def test_chart_can_be_collapsed(self):
        def has_canvas(screen):
            return any(type(c).__name__ == 'Canvas' for c in descendants(screen))
        self.assertTrue(has_canvas(await history.build(self.app, manage=True)))
        self.assertFalse(has_canvas(await history.build(self.app, manage=True, chart=False)))

    async def test_energy_page_shows_total_peak_and_chart(self):
        screen = await history.build(self.app, manage=True, page='energy')
        text = texts(screen)
        for expected in ('Consumo de energia', 'Últimos 7 dias', 'Energia total', 'Pico de consumo',
                         'Energia entregue - kWh', 'Fale com o ChatBot'):
            self.assertIn(expected, text)
        self.assertRegex(text, r'\d[\d.]* kWh')
        self.assertTrue(any(type(c).__name__ == 'Canvas' for c in descendants(screen)))

    def test_number_formatting(self):
        self.assertEqual(history_owner.money_short('8420.4'), 'R$ 8.420')
        self.assertEqual(history_owner.kwh_short('2184.2'), '2.184 kWh')


if __name__ == '__main__':
    unittest.main()
