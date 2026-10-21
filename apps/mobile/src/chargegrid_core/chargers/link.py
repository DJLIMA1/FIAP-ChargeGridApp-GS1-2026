"""Ligação "carregador ↔ ponto/tela": endereço do carregador externo de cada ponto.

A tela (painel ESP32) é o mestre Modbus TCP na rede Wi-Fi local; o carregador GoodWe HCA G2
(hoje o simulador em ESP32 DevKit, firmware/goodwe-hca-sim) é o escravo com unit id igual ao
endereço e anuncia ``cg-hca-<endereço>.local`` por mDNS. O dono escolhe o endereço por ponto
(``connectors.charger_address``, 1–247, nulo = sem carregador externo).

Puro: usado pela API (resposta do sync e payloads do dono) e pelo app (texto do status).
"""

from __future__ import annotations

from typing import Mapping

MODEL = 'goodwe_hca_g2'
TRANSPORT = 'modbus_tcp'
MIN_ADDRESS, MAX_ADDRESS = 1, 247  # unit id Modbus válido
SUGGESTED_ADDRESS = 1
LABEL = 'GoodWe HCA G2'
# O único HCA ligado hoje é o simulador (ESP32 DevKit + relé); a etiqueta diz isso.
SIMULATED = True
LINK_STATES = ('online', 'offline', 'pending')
LINK_TEXT = {'online': 'online', 'offline': 'offline', 'pending': 'aguardando a tela'}


def validate_address(value) -> int | None:
    """Endereço inteiro 1–247 ou ``None`` (remove). Recusa bool, texto e fração."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError('Endereço do carregador deve ser um número inteiro de 1 a 247')
    if not MIN_ADDRESS <= value <= MAX_ADDRESS:
        raise ValueError('Endereço do carregador deve estar entre 1 e 247')
    return value


def host_for(address: int) -> str:
    return f'cg-hca-{int(address)}.local'


def sync_link(address) -> dict | None:
    """Bloco ``connector.charger_link`` da resposta do sync (ou ``None`` sem carregador externo)."""
    if address is None:
        return None
    address = int(address)
    return {'model': MODEL, 'transport': TRANSPORT, 'address': address, 'host': host_for(address)}


def reported_link(reported: Mapping | None) -> dict | None:
    """Campos do carregador externo no último sync da tela (``devices.charger``), ou ``None``."""
    if not reported or reported.get('model') != MODEL or reported.get('transport') != TRANSPORT:
        return None
    address = reported.get('address')
    if address is None:
        return None
    link = reported.get('link')
    return {'model': MODEL, 'transport': TRANSPORT, 'address': address,
            'link': link if link in ('online', 'offline') else 'offline'}


def link_state(address, reported: Mapping | None, screen_online: bool) -> str | None:
    """``online``/``offline`` pelo último sync da tela; ``pending`` = a tela (online) ainda não
    confirmou este endereço (firmware antigo ou próximo sync). Tela offline → ``offline``."""
    if address is None:
        return None
    if not screen_online:
        return 'offline'
    seen = reported_link(reported)
    if seen is None or seen['address'] != int(address):
        return 'pending'
    return seen['link']


def owner_block(address, reported: Mapping | None, screen_online: bool) -> dict | None:
    """``charger_link`` do dono: endereço configurado, host, estado do link e o que a tela reportou."""
    block = sync_link(address)
    if block is None:
        return None
    return {**block, 'label': LABEL, 'simulated': SIMULATED,
            'link': link_state(address, reported, screen_online), 'reported': reported_link(reported)}


def status_text(block: Mapping | None) -> str:
    """``Carregador 1 · GoodWe HCA G2 (simulado) · online`` (vazio sem carregador)."""
    if not block or block.get('address') is None:
        return ''
    label = block.get('label') or LABEL
    if block.get('simulated', SIMULATED):
        label += ' (simulado)'
    link = LINK_TEXT.get(block.get('link') or 'pending', 'aguardando a tela')
    return f"Carregador {block['address']} · {label} · {link}"
