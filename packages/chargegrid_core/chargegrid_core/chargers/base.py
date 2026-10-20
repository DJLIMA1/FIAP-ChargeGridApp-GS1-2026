"""Contrato dos adaptadores de carregador usados na borda (simulador/gateway local).

A API decide a potência em W e manda ``SET_POWER``; quem fala com o equipamento é a
borda, porque a API serverless não alcança Modbus numa rede local. O adaptador é puro:
traduz W em escritas de registradores e confirma pela releitura. O transporte (simulado
ou real) é injetado; este módulo não abre conexões.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

# Grau de confiança de cada informação do mapa de registradores.
VENDOR_DOC_UNPUBLISHED = 'vendor_doc_unpublished'  # documento do fabricante, não publicado
COMMUNITY_OBSERVED = 'community_observed'  # observado por integrações de terceiros
UNVERIFIED = 'unverified'  # inferência, sem confirmação


@dataclass(frozen=True)
class Register:
    address: int
    name: str
    access: str  # 'RO' | 'RW'
    kind: str  # 'U16' | 'U32' | 'STR'
    scale: str  # ex.: '0.1 kW'
    flash: bool | None
    confidence: str
    note: str = ''


@dataclass(frozen=True)
class RegisterWrite:
    address: int
    value: int
    note: str


@dataclass(frozen=True)
class ChargerLimits:
    min_power_w: int
    max_power_w: int
    step_w: int
    phases: int


class Transport(Protocol):
    """Leitura e escrita de holding registers (FC03/FC06)."""

    simulated: bool

    def read(self, address: int, count: int = 1) -> list[int]: ...

    def write(self, address: int, value: int) -> None: ...


class ChargerDriver(Protocol):
    model: str

    def limits(self) -> ChargerLimits: ...

    def expected_power_w(self, power_w: int) -> int: ...

    def plan_set_power(self, power_w: int, registers: Mapping[int, int]) -> list[RegisterWrite]: ...

    def applied_power_w(self, registers: Mapping[int, int]) -> int | None: ...

    def capability(self) -> dict: ...


def apply_power(driver: ChargerDriver, transport: Transport, power_w: int, watched: tuple[int, ...]) -> dict:
    """Escreve o limite pelo transporte e confirma pela releitura.

    Devolve ``{applied_power_w, expected_power_w, writes, confirmed}``. ``confirmed`` só é
    verdadeiro quando os registradores relidos dão exatamente o valor esperado; o ACK
    ``applied`` do protocolo depende disso.
    """
    before = {address: transport.read(address)[0] for address in watched}
    writes = driver.plan_set_power(power_w, before)
    for item in writes:
        transport.write(item.address, item.value)
    after = {address: transport.read(address)[0] for address in watched}
    applied = driver.applied_power_w(after)
    expected = driver.expected_power_w(power_w)
    return {'applied_power_w': applied, 'expected_power_w': expected, 'writes': writes,
            'confirmed': applied is not None and applied == expected}
