import unittest

from chargegrid_app.screens import charging
from test_demo_consumer import CONTEXT, HandlerApp, texts

REMOVED = ('JORNADA DA RECARGA', 'Ver eventos da sessão', 'Atualiza a cada', 'Detalhes da recarga',
           'Última medida')


def session(**extra):
    return {**CONTEXT, 'id': 's1', 'status': 'charging', 'max_duration_minutes': 30, 'online': True,
            'source': 'simulated', 'energy_wh': '1234', 'soc_percent': 40, 'cost_estimate': '2.00',
            'price_per_kwh': '1.89', **extra}


async def render(demo=True, **extra):
    app = HandlerApp()
    app.api.is_demo = demo
    app.api.request.side_effect = [session(**extra)]
    screen = await charging.build(app)
    return texts(screen)


class ChargingDetailsTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_session_shows_compact_details_only(self):
        text = await render(max_cost='20.00', demand_multiplier='1.30', discount_percent=10)
        for expected in ('Encerrar recarga', 'Detalhes', 'Energia entregue', '1,234 kWh', 'Tarifa',
                         'demanda 1,3×', '30 min · até R$ 20,00', '10%', 'Dados simulados nesta conta'):
            self.assertIn(expected, text)
        for gone in REMOVED:
            self.assertNotIn(gone, text)
        self.assertNotIn('Encerramento', text)
        self.assertNotIn('offline', text)

    async def test_offline_active_session_shows_alert(self):
        self.assertIn('Equipamento simulado offline', await render(online=False))
        self.assertIn('parada física não confirmada', await render(demo=False, online=False))

    async def test_ended_session_shows_reason(self):
        text = await render(status='completed', end_reason='user_stop', online=False)
        self.assertIn('Encerramento', text)
        self.assertIn('Parada solicitada', text)
        self.assertNotIn('offline', text)
