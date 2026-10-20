"""Adaptador GoodWe HCA G2 (carregador AC de 2ª geração): potência por ponto → Modbus.

SEM VALIDAÇÃO EM HARDWARE. O mapa vem do documento do fabricante "AC EV Charger Gen2
Modbus Protocol" V1.0.15 (12/09/2025), que a GoodWe não publica. Usamos as transcrições
públicas abaixo, que concordam entre si em endereço, tipo e escala:

- STIG4 (desafio GoodWe × FIAP): docs/references/goodwe/hca-g2-modbus-map.md e
  apps/api/app/drivers/modbus_map.py, commit de90b86f2a87d657b7fbaa33c4299680b48865a4
  https://github.com/STIG4-Solutions/chargegrid-challenge
- Integração Home Assistant sems_wallbox: docs/modbus-protocol.md e
  custom_components/sems_wallbox/wallbox_modbus.py, commit beaa176660d0e8ebfc3f6d0131c8d2ec8e26ee3c
  https://github.com/prezervos/goodwe-wallbox-sems-home-assistant
- evcc: charger/goodwe.go, commit 106eda351b8c294020a876d309e0ffb7117ddda1 ("not vendor-verified")
  https://github.com/evcc-io/evcc
- DaviZuolo07/GoodWe_MVP backend/demanda.py (commit 5ed7f652): cita 10024/10025/10026/10029/10032,
  mas trata o 10026 como teto do ponto; pelo documento ele é o disjuntor de entrada da casa.

Parâmetros elétricos e o protocolo "Modbus TCP": datasheet oficial
https://en.goodwe.com/Ftp/EN/Downloads/Datasheet/GW_HCA-G2_Datasheet-EN.pdf (GW7K-HCA-20
monofásico 32 A 7 kW; GW11K-HCA-20 trifásico 16 A 11 kW; GW22K-HCA-20 trifásico 32 A 22 kW).
Mínimo de 6 A por fase (1,4 kW mono / 4,2 kW tri) segundo o manual do usuário G2, seção 3.5.
O HCA G2 não tem OCPP nem API SEMS+ para carregadores.

Controle usado aqui:
- **10029** Maximum Charging Power, U16 em 0,1 kW, faixa por modelo. Não existe setpoint de
  corrente em A. Grava em flash: o adaptador só escreve quando o valor muda.
- **10060** liga/desliga a recarga (1 = desliga, 2 = liga), sem flash: pausa abaixo do mínimo.
- **10032** modo de carga (0 = rápido), escrito uma vez na configuração.
Nunca escrevemos 10024 (manter potência mínima), 10025 (gestão dinâmica do próprio carregador)
nem 10026 (disjuntor da casa, que é limite do local, não do ponto).
Unit ID 247, FC03 para ler e FC06 para escrever vêm de integrações de terceiros e ficam
configuráveis no transporte.
"""

from __future__ import annotations

from typing import Mapping

from .base import (
    COMMUNITY_OBSERVED,
    UNVERIFIED,
    VENDOR_DOC_UNPUBLISHED,
    ChargerLimits,
    Register,
    RegisterWrite,
)

MAP_VERSION = 'AC EV Charger Gen2 Modbus Protocol V1.0.15 (documento do fabricante, não publicado)'
HARDWARE_VALIDATED = False
DEFAULT_UNIT_ID = 247  # COMMUNITY_OBSERVED (evcc, Home Assistant)
DEFAULT_PORT = 502

EMS_DISPATCH = 10000
CHARGING_POWER = 10015
STATUS = 10017
KEEP_MIN_POWER = 10024
DYNAMIC_LOAD = 10025
HOUSE_BREAKER = 10026
MAX_CHARGING_POWER = 10029
CHARGE_MODE = 10032
POWER_SPEC = 10058
CHARGER_TYPE = 10059
START_STOP = 10060

STOP_VALUE, START_VALUE = 1, 2
FAST_MODE = 0

REGISTERS = {
    item.address: item
    for item in (
        Register(EMS_DISPATCH, 'EMS Energy Dispatch', 'RW', 'U16', '1 = reduz ao mínimo', False,
                 VENDOR_DOC_UNPUBLISHED),
        Register(CHARGING_POWER, 'Charging power', 'RO', 'U16', '0.1 kW', None, VENDOR_DOC_UNPUBLISHED),
        Register(STATUS, 'Charging Station Status', 'RO', 'U16', 'enum', None, VENDOR_DOC_UNPUBLISHED,
                 '0 livre, 1 plugado, 2 handshake, 3 carregando, 4 concluído, 5 alarme, 8 falha ao iniciar'),
        Register(KEEP_MIN_POWER, 'Manter potência mínima', 'RW', 'U16', '0/1', True, VENDOR_DOC_UNPUBLISHED,
                 'não usado pelo adaptador'),
        Register(DYNAMIC_LOAD, 'Gestão dinâmica de carga (DLM)', 'RW', 'U16', '0/1', True, VENDOR_DOC_UNPUBLISHED,
                 'não usado pelo adaptador (a divisão é do ChargeGrid)'),
        Register(HOUSE_BREAKER, 'Corrente do disjuntor de entrada da casa', 'RW', 'U16', 'A', True,
                 VENDOR_DOC_UNPUBLISHED, 'limite do local para a DLM do carregador; nunca é teto do ponto'),
        Register(MAX_CHARGING_POWER, 'Maximum Charging Power', 'RW', 'U16', '0.1 kW', True, VENDOR_DOC_UNPUBLISHED,
                 'faixa por modelo: 14–70 (mono 7 kW), 42–110 (tri 11 kW), 42–220 (tri 22 kW)'),
        Register(CHARGE_MODE, 'Modo de carga avançado', 'RW', 'U16', '0 rápido, 1 FV, 2 FV + bateria', True,
                 VENDOR_DOC_UNPUBLISHED),
        Register(POWER_SPEC, 'Power spec', 'RO', 'U16', '0 = 7 kW, 1 = 11 kW, 2 = 22 kW', None,
                 VENDOR_DOC_UNPUBLISHED),
        Register(CHARGER_TYPE, 'Tipo do carregador', 'RO', 'U16', '0 = trifásico, 1 = monofásico', None,
                 VENDOR_DOC_UNPUBLISHED),
        Register(START_STOP, 'Liga/desliga recarga', 'RW', 'U16', '1 = desliga, 2 = liga', False,
                 VENDOR_DOC_UNPUBLISHED),
    )
}
TRANSPORT_FACTS = {'unit_id': COMMUNITY_OBSERVED, 'read_function': COMMUNITY_OBSERVED,
                   'write_function': COMMUNITY_OBSERVED, 'address_offset': COMMUNITY_OBSERVED,
                   'current_from_power': UNVERIFIED}

# Faixa do 10029 por modelo, em décimos de kW (documento V1.0.15, igual ao manual 3.5).
MODELS = {
    'GW7K-HCA-20': {'phases': 1, 'min': 14, 'max': 70, 'spec': 0},
    'GW11K-HCA-20': {'phases': 3, 'min': 42, 'max': 110, 'spec': 1},
    'GW22K-HCA-20': {'phases': 3, 'min': 42, 'max': 220, 'spec': 2},
}
# Únicos registradores que o adaptador escreve.
WRITABLE = frozenset({MAX_CHARGING_POWER, START_STOP, CHARGE_MODE})
WATCHED = (MAX_CHARGING_POWER, START_STOP)


class GoodWeHcaG2:
    model = 'goodwe_hca_g2'

    def __init__(self, variant: str = 'GW7K-HCA-20'):
        if variant not in MODELS:
            raise ValueError(f'Modelo HCA G2 desconhecido: {variant}')
        self.variant = variant
        self.spec = MODELS[variant]

    def limits(self) -> ChargerLimits:
        return ChargerLimits(min_power_w=self.spec['min'] * 100, max_power_w=self.spec['max'] * 100,
                             step_w=100, phases=self.spec['phases'])

    def register_value(self, power_w: int) -> int | None:
        """Valor do 10029 (0,1 kW, arredondado para baixo) ou ``None`` = pausar (abaixo do mínimo)."""
        tenths = int(power_w) // 100
        if tenths < self.spec['min']:
            return None
        return min(tenths, self.spec['max'])

    def expected_power_w(self, power_w: int) -> int:
        value = self.register_value(power_w)
        return 0 if value is None else value * 100

    def setup_writes(self) -> list[RegisterWrite]:
        return [RegisterWrite(CHARGE_MODE, FAST_MODE, 'modo de carga rápido (sem FV/bateria)')]

    def plan_set_power(self, power_w: int, registers: Mapping[int, int]) -> list[RegisterWrite]:
        """Escritas para aplicar ``power_w``; só o que muda (o 10029 grava em flash)."""
        value = self.register_value(power_w)
        writes = []
        if value is None:
            if registers.get(START_STOP) != STOP_VALUE:
                writes.append(RegisterWrite(START_STOP, STOP_VALUE, 'pausa: abaixo do mínimo de 6 A por fase'))
        else:
            if registers.get(MAX_CHARGING_POWER) != value:
                writes.append(RegisterWrite(MAX_CHARGING_POWER, value, f'potência máxima {value / 10:g} kW'))
            if registers.get(START_STOP) != START_VALUE:
                writes.append(RegisterWrite(START_STOP, START_VALUE, 'retoma a recarga'))
        for item in writes:
            if item.address not in WRITABLE:
                raise ValueError(f'Registrador {item.address} não pode ser escrito pelo adaptador')
        return writes

    def applied_power_w(self, registers: Mapping[int, int]) -> int | None:
        if registers.get(START_STOP) == STOP_VALUE:
            return 0
        value = registers.get(MAX_CHARGING_POWER)
        return None if value is None else int(value) * 100

    def capability(self) -> dict:
        limits = self.limits()
        return {'model': self.model, 'variant': self.variant, 'min_power_w': limits.min_power_w,
                'max_power_w': limits.max_power_w, 'step_w': limits.step_w, 'phases': limits.phases}


def current_a(power_w: int, phases: int, voltage: int = 230) -> float:
    """Corrente aproximada por fase só para exibição (UNVERIFIED: o carregador não expõe
    como converte 10029 em corrente)."""
    return round(power_w / (voltage * phases), 1) if phases else 0.0
