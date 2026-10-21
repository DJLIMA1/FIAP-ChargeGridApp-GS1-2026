"""Ligação "carregador ↔ ponto/tela": cada conector É um carregador GoodWe HCA G2.

A tela (painel ESP32) é o mestre Modbus TCP na rede Wi-Fi local; o carregador GoodWe HCA G2
(hoje o simulador em ESP32 DevKit, firmware/goodwe-hca-sim) é o escravo com unit id igual ao
endereço e anuncia ``cg-hca-<endereço>.local`` por mDNS. Todo conector tem endereço
(``connectors.charger_address``, 1–247, único por posto): automático pela ordem do posto
(1, 2, 3…, próximo livre) e editável pelo dono. Enquanto o carregador do endereço não
responde, a tela usa a simulação interna dela (relé/energia simulada) e reporta ``offline``.

Puro: usado pela API (resposta do sync e payloads do dono) e pelo app (texto do status).
"""

from __future__ import annotations

from typing import Mapping

MODEL = 'goodwe_hca_g2'
TRANSPORT = 'modbus_tcp'
MIN_ADDRESS, MAX_ADDRESS = 1, 247  # unit id Modbus válido
SUGGESTED_ADDRESS = 1  # primeiro conector do posto
LABEL = 'GoodWe HCA G2'
# O único HCA ligado hoje é o simulador (ESP32 DevKit + relé); a etiqueta diz isso.
SIMULATED = True
LINK_STATES = ('online', 'offline', 'pending')
# Sem resposta do carregador (offline) ou tela que ainda não confirmou o endereço (pending):
# a tela carrega com a simulação interna dela.
WAITING_TEXT = 'aguardando carregador (simulação da tela)'
LINK_TEXT = {'online': 'online', 'offline': WAITING_TEXT, 'pending': WAITING_TEXT}
EMPTY_ADDRESS_MESSAGE = 'Endereço do carregador não pode ficar vazio: informe um número de 1 a 247'


def validate_address(value) -> int:
    """Endereço inteiro 1–247. Recusa vazio (todo conector é um carregador), bool, texto e fração."""
    if value is None:
        raise ValueError(EMPTY_ADDRESS_MESSAGE)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError('Endereço do carregador deve ser um número inteiro de 1 a 247')
    if not MIN_ADDRESS <= value <= MAX_ADDRESS:
        raise ValueError('Endereço do carregador deve estar entre 1 e 247')
    return value


def next_free_address(used) -> int:
    """Menor endereço livre do posto (1, 2, 3…), ignorando ``None``. Posto cheio: ``ValueError``."""
    taken = {int(value) for value in used if value is not None}
    for address in range(MIN_ADDRESS, MAX_ADDRESS + 1):
        if address not in taken:
            return address
    raise ValueError('Posto sem endereço de carregador livre (1 a 247)')


def host_for(address: int) -> str:
    return f'cg-hca-{int(address)}.local'


def sync_link(address) -> dict | None:
    """Bloco ``connector.charger_link`` da resposta do sync (``None`` só sem endereço — legado)."""
    if address is None:
        return None
    address = int(address)
    return {'model': MODEL, 'transport': TRANSPORT, 'address': address, 'host': host_for(address)}


def reported_link(reported: Mapping | None) -> dict | None:
    """Endereço/link do último sync da tela (``devices.charger``), ou ``None`` (firmware antigo).

    Carregador online: ``model`` goodwe_hca_g2/modbus_tcp. Offline: a tela declara a simulação
    interna dela (esp32_bench/simulated, limites de sempre) com o mesmo ``address`` e ``link``."""
    if not reported:
        return None
    address = reported.get('address')
    if address is None:
        return None
    link = reported.get('link')
    return {'model': reported.get('model'), 'transport': reported.get('transport'), 'address': address,
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
    """``Carregador GoodWe · endereço 1 · online`` ou ``… · aguardando carregador (simulação da
    tela)`` (vazio sem bloco)."""
    if not block or block.get('address') is None:
        return ''
    link = LINK_TEXT.get(block.get('link') or 'pending', WAITING_TEXT)
    return f"Carregador GoodWe · endereço {block['address']} · {link}"
