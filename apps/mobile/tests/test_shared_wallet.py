"""The app uses the same simulated wallet as the panel, including retry-safe credits."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace

from chargegrid_app.api_client import ApiError
from chargegrid_app.services import wallet


class WalletApi:
    is_demo = False

    def __init__(self):
        self.balance = Decimal('0')
        self.imported = False
        self.keys = {}
        self.lose_response = False

    def view(self):
        return {'simulated': True, 'legacy_imported': self.imported,
                'balance': str(self.balance), 'transactions': []}

    async def request(self, method, path, body=None, key=None):
        if method == 'GET':
            return self.view()
        if key not in self.keys:
            amount = Decimal(body['amount'])
            if body['kind'] == 'import':
                if not self.imported:
                    self.balance += amount
                    self.imported = True
            else:
                self.balance += amount if body['kind'] == 'credit' else -amount
            self.keys[key] = body
        if self.lose_response:
            self.lose_response = False
            raise ApiError('Sem resposta', 0)
        return self.view()


def test_shared_wallet_import_cross_device_and_retry(tmp_path, monkeypatch):
    monkeypatch.setenv('FLET_APP_STORAGE_DATA', str(tmp_path))

    async def scenario():
        api = WalletApi()
        phone = SimpleNamespace(api=api, profile={'id': 'u'})
        wallet.credit(phone, '70.00', 'Saldo antigo (simulado)')
        assert await wallet.refresh(phone)
        assert wallet.balance(phone) == Decimal('70.00')
        await wallet.refresh(phone)
        assert api.balance == Decimal('70.00')
        # A kiosk purchase changes the authoritative ledger.
        api.balance -= Decimal('20')
        await wallet.refresh(phone)
        assert wallet.balance(phone) == Decimal('50.00')
        await wallet.shared_debit(phone, '5', 'Recarga')
        assert api.balance == Decimal('45')
        api.lose_response = True
        try:
            await wallet.shared_credit(phone, '3', 'Sobra', operation_key='refund-session-1')
        except ApiError:
            pass
        else:
            raise AssertionError('Expected a lost HTTP response')
        assert phone.wallet_pending['key'] == 'refund-session-1'
        await wallet.shared_credit(phone, '3', 'Sobra', operation_key='refund-session-1')
        assert api.balance == Decimal('48')
        assert phone.wallet_pending is None
    asyncio.run(scenario())


def test_shared_refund_is_idempotent_after_lost_response(tmp_path, monkeypatch):
    monkeypatch.setenv('FLET_APP_STORAGE_DATA', str(tmp_path))
    from chargegrid_app.services import prepaid

    async def scenario():
        api = WalletApi()
        app = SimpleNamespace(api=api, profile={'id': 'u'}, presentation_override=True)
        await wallet.refresh(app)
        prepaid.record(app, amount='10', energy_amount='10', method='balance', session_id='session-1')
        session = {'id': 'session-1', 'status': 'completed', 'cost_estimate': '4', 'end_reason': 'battery_full'}
        api.lose_response = True
        try:
            await prepaid.settle_shared(app, session)
        except ApiError:
            pass
        assert api.balance == Decimal('6')
        assert await prepaid.settle_shared(app, session) == Decimal('6')
        assert await prepaid.settle_shared(app, session) == Decimal('6')
        assert api.balance == Decimal('6')
    asyncio.run(scenario())
