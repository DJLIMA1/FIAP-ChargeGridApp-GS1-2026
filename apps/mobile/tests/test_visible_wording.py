"""Nenhum texto visível fala em simulação, demonstração, "demo" ou pagamento de teste.

Duas camadas: (1) as telas renderizadas (detalhe da recarga, PDF do recibo da conta de exemplo,
gestão da estação, recarga ao vivo) e (2) os literais das telas de recarga, reserva, pagamento e
gestão (sem docstrings; identificadores sem espaço, como ``'simulated'``, ficam de fora).
"""
import ast
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

import flet as ft

from chargegrid_app import demo_receipt_pdf
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DEMO_PRESENCE_CODE, DemoApi
from chargegrid_app.screens import charging, history, operator, ownership, station_admin
from chargegrid_app.ui.wording import FORBIDDEN, clean_receipt, visible
from test_behavior import HandlerApp, descendants

APP = Path(__file__).resolve().parents[1] / 'src' / 'chargegrid_app'
SCANNED = ('screens/charge_detail.py', 'screens/charging.py', 'screens/booking.py', 'screens/reservations.py',
           'screens/central_admin.py', 'screens/station_admin.py', 'screens/operator.py', 'screens/ownership.py',
           'screens/onboarding.py', 'screens/home.py', 'screens/history.py', 'screens/history_export.py',
           'screens/chat.py', 'screens/wallet.py', 'screens/station_ops.py', 'screens/station_power.py',
           'demo_receipt.py', 'demo_receipt_pdf.py', 'demo_payments.py', 'services/payments.py',
           'services/owner_sessions.py', 'services/account_mode.py', 'ui/point_summary.py')
# Valores de contrato com o totem (nunca desenhados), o nome antigo do perfil de exemplo (só comparado, para
# não saudar "Olá, Conta") e o nome do controle "Modo apresentação" da Conta.
ALLOWED = {'SIMULADO', 'TESTE', 'Conta demonstração',
           'Não foi possível salvar o Modo apresentação na sua conta. Nada mudou; o totem continua no modo anterior.'}


def texts(control):
    return '\n'.join(str(item.value) for item in descendants(control) if isinstance(item, ft.Text) and item.value)


def literals(path):
    tree = ast.parse(path.read_text())
    docs = {id(node.body[0].value) for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body
            and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            yield node.lineno, node.value


async def demo_app(clock=None):
    app = HandlerApp()
    app.back = lambda event=None: None
    app.api = DemoApi(clock=clock, start_at=datetime(2026, 10, 20, 15, tzinfo=timezone.utc)) if clock else DemoApi()
    await app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
    app.profile = await app.api.request('GET', 'me')
    app.api.is_demo = True
    return app


class SourceLiteralTests(unittest.TestCase):
    def test_screen_and_payment_literals_never_mention_simulation_demo_or_test(self):
        found = []
        for name in SCANNED:
            for line, value in literals(APP / name):
                if value in ALLOWED or not re.search(r'\s', value):
                    continue  # identificadores, chaves e rotas
                if FORBIDDEN.search(value):
                    found.append(f'{name}:{line}: {value[:90]!r}')
        self.assertEqual(found, [])

    def test_old_core_labels_are_neutralised(self):
        self.assertEqual(visible('Pago (teste) · em uso'), 'Pago · em uso')
        self.assertEqual(visible('Cobrado R$ 5,00 (simulado) · Devolvido R$ 1,00'), 'Cobrado R$ 5,00 · Devolvido R$ 1,00')
        self.assertEqual(visible('Energia simulada pelo equipamento (não é medição de medidor)'),
                         'Energia calculada pelo equipamento')
        cleaned = clean_receipt({'labels': {'notes': ['Conta demo: dados de exemplo.', 'SIMULADO: energia.',
                                                       'Documento sem valor fiscal.'], 'demo': True}})
        self.assertEqual(cleaned['labels'], {'notes': ['Documento sem valor fiscal.'], 'demo': True})


class RenderedTextTests(unittest.IsolatedAsyncioTestCase):
    async def test_charge_detail_and_receipt_pdf_of_the_example_account(self):
        clock = [0.0]
        app = await demo_app(clock=lambda: clock[0])
        station = (await app.api.request('GET', 'operator/stations'))['items'][0]
        point = next(p for p in station['connectors'] if p['connector_type'] == 'Tipo 2')
        session = await app.api.request('POST', 'charging-sessions', {
            'public_code': point['public_code'], 'presence_code': DEMO_PRESENCE_CODE,
            'max_duration_minutes': 5}, key='wording')
        clock[0] = 400
        self.assertEqual((await app.api.request('GET', f"charging-sessions/{session['id']}"))['status'], 'completed')
        screen = await history.build(app, session=session['id'])
        self.assertIn('Detalhes da recarga', texts(screen))
        self.assertNotRegex(texts(screen), FORBIDDEN)
        receipt = await app.api.request('GET', f"charging-sessions/{session['id']}/receipt")
        flat = ' '.join(f'{label} {value}' for _, rows in demo_receipt_pdf.rows(receipt) for label, value in rows)
        notes = ' '.join(clean_receipt(receipt)['labels']['notes'])
        self.assertNotRegex(f'{demo_receipt_pdf.MARK} {flat} {notes} {receipt.get("number")}', FORBIDDEN)
        self.assertEqual(demo_receipt_pdf.MARK, 'Documento sem valor fiscal')
        self.assertTrue(demo_receipt_pdf.receipt_pdf(receipt).startswith(b'%PDF'))
        await app.api.close()

    async def test_station_admin_operator_and_claim_screens(self):
        app = await demo_app()
        sid = (await app.api.request('GET', 'operator/stations'))['items'][0]['id']
        for page in (None, 'data', 'connectors'):
            with self.subTest(page=page):
                self.assertNotRegex(texts(await station_admin.build(app, station_id=sid, page=page)), FORBIDDEN)
        self.assertNotRegex(texts(await operator.build(app)), FORBIDDEN)
        claim = await ownership.build(app)
        self.assertIn('Adicionar central', texts(claim))
        self.assertNotRegex(texts(claim), FORBIDDEN)
        await app.api.close()

    async def test_live_charging_and_reservation_notices(self):
        clock = [0.0]
        app = await demo_app(clock=lambda: clock[0])
        station = (await app.api.request('GET', 'operator/stations'))['items'][0]
        point = next(p for p in station['connectors'] if p['connector_type'] == 'Tipo 2')
        confirm = await charging.build(app, public_code=point['public_code'])
        self.assertNotRegex(texts(confirm), FORBIDDEN)
        session = await app.api.request('POST', 'charging-sessions', {
            'public_code': point['public_code'], 'presence_code': DEMO_PRESENCE_CODE,
            'max_duration_minutes': 30}, key='wording-live')
        clock[0] = 60
        live = await charging.build(app, session_id=session['id'])
        self.assertNotRegex(texts(live), FORBIDDEN)
        await app.api.close()


if __name__ == '__main__':
    unittest.main()
