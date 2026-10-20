"""Transporte Modbus SIMULADO para o adaptador GoodWe HCA G2 (nenhum equipamento real).

Banco de holding registers em memória com as faixas do mapa V1.0.15 (não publicado pela
GoodWe; ver ``chargegrid_core.chargers.goodwe_hca_g2``). Serve para o simulador de
dispositivo e para os testes: escrita fora da faixa é recusada como o carregador faria
(Illegal Data Value) e falhas podem ser injetadas para provar que o ACK só sai depois da
releitura. O transporte real fica desabilitado até o mapa ser validado em hardware.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from chargegrid_core.chargers import goodwe_hca_g2 as hca
except ImportError:  # Execução direta a partir de tools/.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "chargegrid_core"))
    from chargegrid_core.chargers import goodwe_hca_g2 as hca

LABEL = "[SIMULADO]"
# Holding registers graváveis segundo o mapa (10000, 10019–10039, 10060).
WRITABLE = frozenset({hca.EMS_DISPATCH, *range(10019, 10040), hca.START_STOP})


class ModbusError(Exception):
    """Exceção Modbus simulada (código 02 endereço ilegal / 03 valor ilegal)."""


class SimulatedModbusTransport:
    simulated = True

    def __init__(self, variant="GW7K-HCA-20", unit_id=hca.DEFAULT_UNIT_ID, fail_writes=0, echo=None):
        spec = hca.MODELS[variant]
        self.variant = variant
        self.unit_id = unit_id
        self.spec = spec
        self.fail_writes = fail_writes
        self.echo = echo
        self.log = []
        self.registers = {
            hca.MAX_CHARGING_POWER: spec["max"],
            hca.START_STOP: hca.START_VALUE,
            hca.CHARGE_MODE: 1,
            hca.STATUS: 1,
            hca.CHARGING_POWER: 0,
            hca.POWER_SPEC: spec["spec"],
            hca.CHARGER_TYPE: 1 if spec["phases"] == 1 else 0,
            hca.KEEP_MIN_POWER: 0,
            hca.DYNAMIC_LOAD: 0,
            hca.HOUSE_BREAKER: 0,
        }

    def _say(self, line):
        line = f"{LABEL} {line}"
        self.log.append(line)
        if self.echo:
            self.echo(line)

    def read(self, address, count=1):
        return [self.registers.get(address + offset, 0) for offset in range(count)]

    def write(self, address, value):
        if address not in WRITABLE:
            raise ModbusError(f"02 endereço ilegal para escrita: {address}")
        if address == hca.MAX_CHARGING_POWER and not self.spec["min"] <= value <= self.spec["max"]:
            raise ModbusError(f"03 valor ilegal para {address}: {value}")
        if address == hca.START_STOP and value not in (hca.STOP_VALUE, hca.START_VALUE):
            raise ModbusError(f"03 valor ilegal para {address}: {value}")
        if self.fail_writes > 0:
            self.fail_writes -= 1
            self._say(f"FC06 unit {self.unit_id} reg {address} <- {value} PERDIDA (falha injetada)")
            return
        self.registers[address] = value
        self._say(f"FC06 unit {self.unit_id} reg {address} <- {value}")
        self._update_status()

    def _update_status(self):
        charging = self.registers[hca.START_STOP] == hca.START_VALUE
        self.registers[hca.STATUS] = 3 if charging else 1
        self.registers[hca.CHARGING_POWER] = self.registers[hca.MAX_CHARGING_POWER] if charging else 0


class ModbusTcpTransport:
    """Transporte real: desabilitado de propósito (mapa sem validação em hardware)."""

    simulated = False

    def __init__(self, *args, **kwargs):
        raise RuntimeError("Transporte Modbus real desabilitado: o mapa V1.0.15 do HCA G2 não foi validado "
                           "em hardware. Use o transporte simulado.")
