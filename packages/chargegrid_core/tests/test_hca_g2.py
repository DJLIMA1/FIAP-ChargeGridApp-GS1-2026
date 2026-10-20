import pytest

from chargegrid_core.chargers import DRIVERS, apply_power
from chargegrid_core.chargers import goodwe_hca_g2 as hca


class Bank:
    """Banco de registradores mínimo para o teste (o simulado completo fica em tools/edge)."""

    simulated = True

    def __init__(self, values=None, fail=False):
        self.values = {hca.MAX_CHARGING_POWER: 70, hca.START_STOP: hca.START_VALUE, **(values or {})}
        self.fail = fail
        self.writes = []

    def read(self, address, count=1):
        return [self.values.get(address + offset, 0) for offset in range(count)]

    def write(self, address, value):
        self.writes.append((address, value))
        if not self.fail:
            self.values[address] = value


def test_watts_to_register_10029_rounds_down_inside_model_range():
    mono = hca.GoodWeHcaG2('GW7K-HCA-20')
    assert mono.register_value(6000) == 60
    assert mono.register_value(6099) == 60
    assert mono.register_value(7200) == 70  # bancada de 7,2 kW → máximo do modelo
    assert mono.register_value(1400) == 14
    assert mono.register_value(1399) is None
    tri = hca.GoodWeHcaG2('GW22K-HCA-20')
    assert tri.register_value(4100) is None
    assert tri.register_value(30000) == 220
    assert tri.limits().min_power_w == 4200 and tri.limits().phases == 3


def test_below_minimum_pauses_with_10060_and_resume_restores():
    driver = hca.GoodWeHcaG2()
    pause = driver.plan_set_power(1000, {hca.MAX_CHARGING_POWER: 70, hca.START_STOP: 2})
    assert [(w.address, w.value) for w in pause] == [(hca.START_STOP, 1)]
    resume = driver.plan_set_power(2000, {hca.MAX_CHARGING_POWER: 70, hca.START_STOP: 1})
    assert [(w.address, w.value) for w in resume] == [(hca.MAX_CHARGING_POWER, 20), (hca.START_STOP, 2)]
    assert driver.applied_power_w({hca.MAX_CHARGING_POWER: 70, hca.START_STOP: 1}) == 0


def test_writes_only_on_change_to_spare_flash():
    driver = hca.GoodWeHcaG2()
    assert driver.plan_set_power(6000, {hca.MAX_CHARGING_POWER: 60, hca.START_STOP: 2}) == []


def test_never_writes_site_or_dlm_registers():
    driver = hca.GoodWeHcaG2()
    addresses = {w.address for power in range(0, 9000, 50)
                 for w in driver.plan_set_power(power, {hca.MAX_CHARGING_POWER: 33, hca.START_STOP: 2})}
    assert addresses <= hca.WRITABLE
    assert not addresses & {hca.KEEP_MIN_POWER, hca.DYNAMIC_LOAD, hca.HOUSE_BREAKER}


def test_apply_confirms_only_by_readback():
    driver = hca.GoodWeHcaG2()
    ok = apply_power(driver, Bank(), 2000, hca.WATCHED)
    assert ok['confirmed'] and ok['applied_power_w'] == 2000
    broken = apply_power(driver, Bank(fail=True), 2000, hca.WATCHED)
    assert not broken['confirmed'] and broken['applied_power_w'] == 7000


def test_map_provenance_is_explicit():
    assert hca.HARDWARE_VALIDATED is False
    assert 'V1.0.15' in hca.MAP_VERSION
    assert hca.REGISTERS[hca.MAX_CHARGING_POWER].scale == '0.1 kW'
    assert hca.REGISTERS[hca.HOUSE_BREAKER].note.startswith('limite do local')
    assert DRIVERS['goodwe-hca-g2'] is hca.GoodWeHcaG2
    with pytest.raises(ValueError):
        hca.GoodWeHcaG2('GW99K')


def test_capability_payload_for_sync():
    assert hca.GoodWeHcaG2().capability() == {
        'model': 'goodwe_hca_g2', 'variant': 'GW7K-HCA-20', 'min_power_w': 1400, 'max_power_w': 7000,
        'step_w': 100, 'phases': 1}
