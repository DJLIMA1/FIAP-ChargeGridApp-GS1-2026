from datetime import datetime
from decimal import Decimal

from chargegrid_app.services import tariffs as svc

RULES = svc.DEFAULT_RULES
SAT_EVENING = datetime(2026, 10, 17, 19, 0)   # sábado
NOON = datetime(2026, 10, 14, 12, 0)


def test_effective_price_base_only_when_quiet():
    assert svc.effective_price('1.89', RULES, NOON, occupancy=1) == Decimal('1.89')


def test_effective_price_demand_and_peak_stack():
    assert svc.effective_price('1.89', RULES, NOON, occupancy=2) == Decimal('2.19')
    assert svc.effective_price('1.89', RULES, SAT_EVENING, occupancy=0) == Decimal('2.14')
    assert svc.effective_price('1.89', RULES, SAT_EVENING, occupancy=3) == Decimal('2.44')


def test_peak_window_edges_days_and_overnight():
    peak = {'enabled': True, 'start': '18:00', 'end': '21:00', 'extra': '0.25', 'days': [0]}
    assert svc.in_peak(peak, datetime(2026, 10, 12, 18, 0))
    assert not svc.in_peak(peak, datetime(2026, 10, 12, 21, 0))
    assert not svc.in_peak(peak, datetime(2026, 10, 13, 19, 0))
    night = {**peak, 'start': '22:00', 'end': '06:00', 'days': [0]}
    assert svc.in_peak(night, datetime(2026, 10, 12, 23, 0)) and svc.in_peak(night, datetime(2026, 10, 12, 5, 0))


def test_inactive_rules_add_nothing():
    off = {key: {**rule, 'enabled': False} for key, rule in RULES.items()}
    assert svc.effective_price('1.89', off, SAT_EVENING, occupancy=9) == Decimal('1.89')
    assert svc.rotation_fee(off, 120) == Decimal('0')


def test_rotation_example_from_reference():
    assert svc.rotation_intervals(RULES['rotation'], 50) == 2
    assert svc.rotation_fee(RULES, 50) == Decimal('0.40')
    assert svc.rotation_fee(RULES, 30) == Decimal('0') and svc.rotation_fee(RULES, 39) == Decimal('0')


def test_parsers_ptbr():
    assert svc.parse_decimal('R$ 0,20') == Decimal('0.20')
    assert svc.parse_decimal('+ R$ 0,30 por kWh') == Decimal('0.30')
    assert svc.parse_decimal('1.234,50') == Decimal('1234.50')
    assert svc.parse_decimal('abc') is None
    assert svc.parse_decimal('R$ 99999') is None
    assert svc.parse_minutes('30 minutos') == 30 and svc.parse_minutes('0') is None
    assert svc.parse_minutes('1,5') is None and svc.parse_minutes('') is None
    assert svc.parse_time('18:00') == '18:00' and svc.parse_time('7') == '07:00' and svc.parse_time('25:00') is None
    assert svc.fmt_money('0.2') == 'R$ 0,20'
    assert svc.days_label(range(7)) == 'Seg, Ter, Qua, Qui, Sex, Sáb e Dom'


def test_base_price_uses_cheapest_active_connector():
    connectors = [{'price_per_kwh': '1.8900'}, {'price_per_kwh': '2.5000'}, {'price_per_kwh': '0.5', 'retired': True}]
    assert svc.base_price(connectors) == Decimal('1.8900') and svc.base_price([]) is None


def test_store_demo_memory_and_json(tmp_path):
    svc.reset_demo()
    demo = svc.TariffStore(demo=True)
    rule = {**RULES['demand'], 'extra': '0.50'}
    assert demo.save_rule('s1', 'demand', rule)
    assert svc.TariffStore(demo=True).load('s1')['demand']['extra'] == '0.50'
    real = svc.TariffStore(path=tmp_path / 't.json')
    assert real.load('s1')['demand']['extra'] == '0.30'
    assert real.save_rule('s1', 'rotation', {**RULES['rotation'], 'enabled': False})
    assert svc.TariffStore(path=tmp_path / 't.json').load('s1')['rotation']['enabled'] is False
    (tmp_path / 't.json').write_text('lixo')
    assert real.load('s1') == RULES
    svc.reset_demo()


def test_screens_build_in_demo():
    import asyncio

    from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
    from chargegrid_app.screens import tariffs

    class App:
        def __init__(self, api):
            self.api = api

        def link(self, *a, **k):
            return lambda e: None

        async def go(self, *a, **k):
            pass

        async def back(self, e=None):
            pass

        def notice(self, m):
            pass

    async def run():
        api = DemoApi()
        await api.login(DEMO_EMAIL, DEMO_PASSWORD)
        app = App(api)
        for page in (None, 'rotation', 'demand', 'peak'):
            assert await tariffs.build(app, station_id='demo-station-1', page=page) is not None
    asyncio.run(run())
