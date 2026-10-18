from decimal import Decimal
from types import SimpleNamespace

import pytest

from chargegrid_app.api_client import ApiError
from chargegrid_app.screens import wallet as screen
from chargegrid_app.services import wallet


def demo_app():
    return SimpleNamespace(api=SimpleNamespace(is_demo=True), profile={'id': 'demo'})


def real_app(uid='u1'):
    return SimpleNamespace(api=SimpleNamespace(is_demo=False), profile={'id': uid})


def test_demo_starts_with_reference_balance_and_credit_debit():
    wallet.reset_demo()
    app = demo_app()
    assert wallet.balance(app) == Decimal('214.80')
    assert [t['title'] for t in wallet.transactions(app)][-1] == 'Transferência Recebida'
    wallet.credit(app, '260', 'Pix Recebido')
    assert wallet.balance(app) == Decimal('474.80')
    with pytest.raises(ApiError, match='Saldo insuficiente'):
        wallet.debit(app, 1000, 'x')
    wallet.debit(app, 74.80, 'Recarga')
    assert wallet.balance(app) == Decimal('400.00')
    wallet.reset_demo()


def test_real_account_persists_per_user(tmp_path, monkeypatch):
    monkeypatch.setenv('FLET_APP_STORAGE_DATA', str(tmp_path))
    assert wallet.balance(real_app()) == 0
    wallet.credit(real_app(), 50, 'Pix Recebido')
    assert wallet.balance(real_app()) == Decimal('50.00')
    assert wallet.balance(real_app('u2')) == 0


def test_parse_amount():
    assert screen.parse_amount('R$ 1.260,50') == Decimal('1260.50')
    assert screen.parse_amount('260') == Decimal('260.00')
    assert screen.parse_amount('0') is None and screen.parse_amount('abc') is None


def test_invalid_amount_rejected():
    with pytest.raises(ApiError):
        wallet.credit(demo_app(), 0, 'x')
    wallet.reset_demo()
