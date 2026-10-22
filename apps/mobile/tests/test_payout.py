import asyncio
from decimal import Decimal
from types import SimpleNamespace

from chargegrid_app.services import payout


def _demo():
    return SimpleNamespace(api=SimpleNamespace(is_demo=True))


def test_demo_balance_and_movements():
    app = _demo()
    assert payout.available(app) == Decimal('2485.90')
    moves = payout.movements(app)
    assert [m['amount'] for m in moves] == [Decimal('486.20'), Decimal('578.30')]
    assert moves[0]['subtitle'] == 'Hoje - 24 transações'


def test_request_now_has_two_percent_fee():
    app = _demo()
    result = payout.request(app, 'now')
    assert result['gross'] == Decimal('2485.90')
    assert result['fee'] == Decimal('49.72')
    assert result['net'] == Decimal('2436.18')
    assert result['destination'] == 'Banco Inter •••• 0378'
    assert result['protocol'] == 'CG-RS-1026' and result['status'] == 'Em processamento'
    assert payout.available(app) == Decimal('0')
    assert payout.movements(app)[0]['amount'] == Decimal('-2485.90')


def test_request_friday_no_fee_and_validation():
    app = _demo()
    result = payout.request(app, 'friday')
    assert result['fee'] == Decimal('0.00') and result['net'] == result['gross']
    try:
        payout.request(app, 'friday')
    except ValueError:
        pass
    else:
        raise AssertionError('second payout without balance must fail')


def test_real_account_derives_from_owner_net(tmp_path, monkeypatch):
    monkeypatch.setenv('FLET_APP_STORAGE_DATA', str(tmp_path))
    app = SimpleNamespace(api=SimpleNamespace(is_demo=False))
    assert payout.available(app) == Decimal('0')
    payout.set_owner_net(app, '100.0000')
    assert payout.available(app) == Decimal('100.00')
    result = payout.request(app, 'now')
    assert result['destination'] == 'Conta cadastrada' and result['net'] == Decimal('98.00')
    assert payout.available(app) == Decimal('0')
    assert (tmp_path / 'payouts.json').exists()


def test_screen_builds_every_step():
    from chargegrid_app.screens import payout as screen
    app = SimpleNamespace(api=SimpleNamespace(is_demo=True), link=lambda *a, **k: None, back=None)
    for params in ({}, {'step': 2}, {'step': 3, 'mode': 'now'}, {'step': 3, 'mode': 'friday'},
                   {'step': 4}, {'step': 4, 'status': 'done'}):
        assert asyncio.run(screen.build(app, **params)) is not None


def test_payouts_are_per_account_and_legacy_list_goes_to_the_first_saver(tmp_path, monkeypatch):
    monkeypatch.setenv('FLET_APP_STORAGE_DATA', str(tmp_path))
    seller_a = SimpleNamespace(api=SimpleNamespace(is_demo=False), profile={'id': 'a'})
    seller_b = SimpleNamespace(api=SimpleNamespace(is_demo=False), profile={'id': 'b'})
    payout.set_owner_net(seller_a, '100.00')
    payout.set_owner_net(seller_b, '80.00')
    payout.request(seller_a, 'friday')
    assert payout.available(seller_a) == Decimal('0')
    assert payout.available(seller_b) == Decimal('80.00')  # o resgate de A não reduz o saldo de B
    (tmp_path / 'payouts.json').write_text('[{"gross": "30.00", "mode": "friday"}]')  # formato antigo
    assert payout.available(seller_a) == Decimal('70.00')
    payout.request(seller_a, 'friday')
    import json
    data = json.loads((tmp_path / 'payouts.json').read_text())
    assert set(data) == {'a'} and len(data['a']) == 2


def test_real_balance_discounts_the_central_rent(tmp_path, monkeypatch):
    monkeypatch.setenv('FLET_APP_STORAGE_DATA', str(tmp_path))
    app = SimpleNamespace(api=SimpleNamespace(is_demo=False), profile={'id': 'a'})
    payout.set_owner_net(app, '500.00', '99.00')
    assert payout.available(app) == Decimal('401.00')
    titles = [(m['title'], m['amount']) for m in payout.movements(app)]
    assert titles == [('Aluguel das centrais', Decimal('-99.00')), ('Repasse das recargas', Decimal('500.00'))]
