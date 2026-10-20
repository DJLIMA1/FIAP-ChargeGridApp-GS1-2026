from datetime import datetime, timedelta, timezone

import pytest

from tools.device_simulator import Device, load_charger
from tools.edge.modbus_sim import (
    ModbusError,
    ModbusTcpTransport,
    SimulatedModbusTransport,
)


def _response(kind, identifier, version, parameters):
    now = datetime.now(timezone.utc)
    return {
        "server_time": now.isoformat(), "control_version": version, "sync_interval_seconds": 1,
        "authorized": {"reservation": None, "session": {"id": "s", "max_duration_minutes": 60, "max_cost": None,
                                                        "price_per_kwh": 2, "discount_percent": 0}},
        "commands": [{"id": identifier, "type": kind, "version": version,
                      "expires_at": (now + timedelta(minutes=1)).isoformat(), "session_id": "s",
                      "reservation_id": None, "parameters": parameters}],
    }


def test_simulated_bank_refuses_out_of_range_and_read_only_writes():
    bank = SimulatedModbusTransport("GW7K-HCA-20")
    with pytest.raises(ModbusError):
        bank.write(10029, 5)  # abaixo de 1,4 kW
    with pytest.raises(ModbusError):
        bank.write(10015, 10)  # potência medida é somente leitura
    bank.write(10029, 36)
    assert bank.read(10029) == [36] and bank.log[-1].startswith("[SIMULADO] FC06 unit 247 reg 10029 <- 36")


def test_real_transport_is_disabled():
    with pytest.raises(RuntimeError, match="não foi validado"):
        ModbusTcpTransport("192.168.0.10")


def test_hca_device_translates_set_power_to_registers_and_acks_after_readback():
    lines = []
    charger, bank = load_charger("goodwe-hca-g2", echo=lines.append)
    device = Device(clock=lambda: 0, charger=charger, transport=bank)
    device.response(_response("START", "start", 1, {"power_limit_w": 7200}))
    assert device.power_w == 7000  # GW7K: máximo de 7 kW no 10029
    device.response(_response("SET_POWER", "p", 2, {"power_limit_w": 2050}))
    assert device.acks[-1] == {"command_id": "p", "status": "applied", "error": None, "applied_power_w": 2000}
    assert bank.read(10029) == [20]
    assert device.payload()["charger"] == {"model": "goodwe_hca_g2", "variant": "GW7K-HCA-20", "min_power_w": 1400,
                                           "max_power_w": 7000, "step_w": 100, "phases": 1, "transport": "simulated"}
    device.response(_response("SET_POWER", "pause", 3, {"power_limit_w": 0}))
    assert bank.read(10060) == [1] and device.power_w == 0
    assert any("reg 10032 <- 0" in line for line in lines)


def test_lost_modbus_write_is_not_acknowledged():
    charger, bank = load_charger("goodwe-hca-g2")
    device = Device(clock=lambda: 0, charger=charger, transport=bank)
    device.response(_response("START", "start", 1, {"power_limit_w": 7000}))
    bank.fail_writes = 1
    device.response(_response("SET_POWER", "p", 2, {"power_limit_w": 3000}))
    assert device.acks[-1]["status"] == "failed" and device.acks[-1]["error"] == "readback_mismatch"
    assert device.acks[-1]["applied_power_w"] == 7000


def test_modbus_exception_keeps_previous_power_and_reports_error():
    charger, bank = load_charger("goodwe-hca-g2")
    device = Device(clock=lambda: 0, charger=charger, transport=bank)
    device.response(_response("START", "start", 1, {"power_limit_w": 7000}))

    def refuse(address, value):
        raise ModbusError(f"03 valor ilegal para {address}: {value}")

    bank.write = refuse
    assert device.install_power(3000) == (7000, "modbus_error: 03 valor ilegal para 10029: 30")
    with pytest.raises(RuntimeError):  # erro inesperado não é engolido como falha Modbus
        bank.write = lambda address, value: (_ for _ in ()).throw(RuntimeError("bug"))
        device.install_power(3000)
