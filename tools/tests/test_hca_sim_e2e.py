"""Ponta a ponta no host: Modbus TCP de verdade contra a lógica do carregador simulado.

Compila firmware/goodwe-hca-sim/host/hca_sim_host.cpp (mesma lib/hca_sim_core e mesmo Modbus TCP
do firmware) como servidor local em 127.0.0.1 e fala com ele por socket, como a tela, o mbpoll ou o
pymodbus fariam. Também roda o plano de escritas do adaptador Python (chargegrid_core GoodWeHcaG2)
contra o servidor. Nunca abre porta serial nem toca em hardware. Sem clang++: o teste é pulado.
"""

from __future__ import annotations

import shutil
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "chargegrid_core"))
from chargegrid_core.chargers import goodwe_hca_g2 as hca

STATUS_PLUGGED, STATUS_CHARGING, STATUS_ALARM = 1, 3, 5
EXT_ENERGY_HIGH, EXT_RELAY, EXT_FAULT, EXT_ADDRESS, EXT_SIMULATED = 19001, 19003, 19004, 19005, 19006


class ModbusException(Exception):
    def __init__(self, code):
        super().__init__(f"exceção Modbus {code:02X}")
        self.code = code


class Client:
    """Cliente Modbus TCP mínimo (FC03/FC06/FC16), só para o teste."""

    def __init__(self, port, unit=1):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=2)
        self.unit = unit
        self.transaction = 0

    def close(self):
        self.sock.close()

    def _call(self, pdu):
        self.transaction = (self.transaction + 1) & 0xFFFF
        self.sock.sendall(struct.pack(">HHHB", self.transaction, 0, len(pdu) + 1, self.unit) + pdu)
        header = self._exact(7)
        transaction, protocol, length, unit = struct.unpack(">HHHB", header)
        assert (transaction, protocol, unit) == (self.transaction, 0, self.unit)
        body = self._exact(length - 1)
        if body[0] & 0x80:
            raise ModbusException(body[1])
        assert body[0] == pdu[0]
        return body

    def _exact(self, size):
        data = b""
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError("servidor fechou a conexão")
            data += chunk
        return data

    def read(self, address, count=1):
        body = self._call(struct.pack(">BHH", 3, address, count))
        assert body[1] == count * 2
        return list(struct.unpack(f">{count}H", body[2:]))

    def write(self, address, value):
        body = self._call(struct.pack(">BHH", 6, address, value))
        assert struct.unpack(">HH", body[1:5]) == (address, value)

    def write_many(self, address, values):
        pdu = struct.pack(f">BHHB{len(values)}H", 16, address, len(values), len(values) * 2, *values)
        body = self._call(pdu)
        assert struct.unpack(">HH", body[1:5]) == (address, len(values))


@pytest.fixture(scope="module")
def server_binary(tmp_path_factory):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("clang++/g++ ausente")
    out = tmp_path_factory.mktemp("hca") / "hca_sim_host"
    shared = ROOT / "firmware/shared/hca_g2/src"
    core = ROOT / "firmware/goodwe-hca-sim/lib/hca_sim_core/src"
    subprocess.run([compiler, "-std=c++17", "-O1", f"-I{shared}", f"-I{core}",
                    str(ROOT / "firmware/goodwe-hca-sim/host/hca_sim_host.cpp"),
                    str(core / "hca_sim_core.cpp"), str(shared / "modbus_tcp.cpp"), "-o", str(out)], check=True)
    return out


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def start_server(server_binary):
    processes = []

    def start(address=1, speed=1):
        port = _free_port()
        process = subprocess.Popen([str(server_binary), "--port", str(port), "--address", str(address),
                                    "--speed", str(speed)], stdout=subprocess.PIPE, text=True)
        processes.append(process)
        assert process.stdout.readline().startswith(f"LISTENING {port}")
        return port, process

    yield start
    for process in processes:
        process.kill()
        process.wait()


def test_boot_is_safe_and_reports_the_simulated_model(start_server):
    port, _ = start_server()
    client = Client(port)
    assert client.read(hca.START_STOP) == [hca.STOP_VALUE]
    assert client.read(hca.CHARGING_POWER, 3) == [0, 0, STATUS_PLUGGED]
    assert client.read(hca.POWER_SPEC, 3) == [0, 1, hca.STOP_VALUE]  # 10058 7 kW, 10059 mono, 10060 desliga
    assert client.read(hca.MAX_CHARGING_POWER) == [hca.MODELS["GW7K-HCA-20"]["max"]]
    assert client.read(EXT_RELAY, 4) == [0, 0, 1, 1]  # relé aberto, sem falha, endereço 1, SIMULADO
    client.close()


def test_start_pause_stop_and_exceptions_over_tcp(start_server):
    port, process = start_server()
    client = Client(port)
    client.write(hca.CHARGE_MODE, hca.FAST_MODE)
    client.write(hca.MAX_CHARGING_POWER, 20)
    client.write(hca.START_STOP, hca.START_VALUE)
    assert process.stdout.readline().startswith("RELAY CLOSED 10029=20 10060=2")
    assert client.read(hca.CHARGING_POWER, 3) == [20, 0, STATUS_CHARGING]  # 10015 SIMULADO = 10029
    assert client.read(EXT_RELAY) == [1]
    # Abaixo do mínimo (1,3 kW): pausa com 10060 ainda = 2.
    client.write(hca.MAX_CHARGING_POWER, 13)
    assert process.stdout.readline().startswith("RELAY OPEN 10029=13 10060=2")
    assert client.read(hca.CHARGING_POWER, 3) == [0, 0, STATUS_PLUGGED]
    client.write_many(hca.MAX_CHARGING_POWER, [70])
    assert process.stdout.readline().startswith("RELAY CLOSED 10029=70")
    with pytest.raises(ModbusException) as error:
        client.write(hca.MAX_CHARGING_POWER, 71)  # acima de 7,0 kW
    assert error.value.code == 3
    with pytest.raises(ModbusException) as error:
        client.write(hca.CHARGING_POWER, 1)  # somente leitura
    assert error.value.code == 2
    with pytest.raises(ModbusException) as error:
        client.read(10061)
    assert error.value.code == 2
    other = Client(port, unit=2)
    with pytest.raises(ModbusException) as error:
        other.write(hca.START_STOP, hca.STOP_VALUE)  # unit id != endereço
    assert error.value.code == 0x0B
    client.write(hca.START_STOP, hca.STOP_VALUE)
    assert process.stdout.readline().startswith("RELAY OPEN 10029=70 10060=1")
    assert client.read(hca.CHARGING_POWER) == [0]
    client.close()
    other.close()


def test_address_is_the_unit_id(start_server):
    port, _ = start_server(address=7)
    assert Client(port, unit=7).read(EXT_ADDRESS) == [7]
    with pytest.raises(ModbusException):
        Client(port, unit=1).read(EXT_ADDRESS)


def test_watchdog_opens_the_relay_when_the_master_disappears(start_server):
    port, process = start_server(speed=200)  # 15 s simulados = 75 ms
    client = Client(port)
    client.write(hca.START_STOP, hca.START_VALUE)
    assert process.stdout.readline().startswith("RELAY CLOSED")
    for _ in range(10):  # mestre lendo: continua fechado
        time.sleep(0.02)
        assert client.read(EXT_RELAY) == [1]
    time.sleep(0.3)
    assert process.stdout.readline().startswith("RELAY OPEN 10029=70 10060=1 status=5 fault=1")
    assert client.read(hca.STATUS) == [STATUS_ALARM] and client.read(EXT_FAULT) == [1]
    client.write(hca.START_STOP, hca.START_VALUE)  # escrita limpa a falha e religa por comando
    assert process.stdout.readline().startswith("RELAY CLOSED")
    energy_high, energy_low = client.read(EXT_ENERGY_HIGH, 2)
    assert energy_high * 65536 + energy_low > 0  # energia SIMULADA integrou a 7 kW
    client.close()


def test_python_adapter_plan_drives_the_firmware_simulator(start_server):
    """O plano de escritas do adaptador do chargegrid_core funciona contra o firmware simulado."""
    port, _ = start_server()
    client = Client(port)
    adapter = hca.GoodWeHcaG2("GW7K-HCA-20")
    for item in adapter.setup_writes():
        client.write(item.address, item.value)
    for power_w, expected in ((3650, 3600), (1000, 0), (7200, 7000)):
        registers = {hca.MAX_CHARGING_POWER: client.read(hca.MAX_CHARGING_POWER)[0],
                     hca.START_STOP: client.read(hca.START_STOP)[0]}
        for item in adapter.plan_set_power(power_w, registers):
            client.write(item.address, item.value)
        readback = {hca.MAX_CHARGING_POWER: client.read(hca.MAX_CHARGING_POWER)[0],
                    hca.START_STOP: client.read(hca.START_STOP)[0]}
        assert adapter.applied_power_w(readback) == expected
        assert client.read(hca.CHARGING_POWER)[0] * 100 == expected
    client.close()
