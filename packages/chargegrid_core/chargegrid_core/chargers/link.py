"""Estação (central) × carregadores: cada conector É um carregador GoodWe HCA G2.

A CENTRAL da estação (painel ESP32) é o mestre Modbus TCP na rede Wi-Fi local e comanda um ou
mais carregadores GoodWe HCA G2 (hoje o simulador em ESP32 DevKit, firmware/goodwe-hca-sim),
cada um com unit id igual ao endereço e anunciado como ``cg-hca-<endereço>.local`` por mDNS.
Todo conector tem endereço (``connectors.charger_address``, 1–247, único por posto): automático
pela ordem do posto (1, 2, 3…, próximo livre) e editável pelo dono.

Carregador sem resposta = **carregador offline**: só aquele ponto fica indisponível (a estação
continua online enquanto a central tiver contato) e a central recusa o START (``charger_offline``) —
não há mais recarga na simulação interna da central quando existe ``charger_link``.

Puro: usado pela API (resposta do sync, disponibilidade e payloads do dono) e pelo app (textos).
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
# pending = a central (online) ainda não confirmou este endereço (próximo sync ou firmware antigo).
WAITING_TEXT = 'aguardando a central'
LINK_TEXT = {'online': 'online', 'offline': 'offline', 'pending': WAITING_TEXT}
# Motivos de indisponibilidade de um ponto ligados ao hardware (``unavailable_reason``).
CHARGER_OFFLINE = 'charger_offline'
SCREEN_OFFLINE = 'screen_offline'
CHARGER_OFFLINE_MESSAGE = 'Carregador offline — use outro ponto desta estação'
CHARGER_OFFLINE_SHORT = 'Carregador offline'
STATUS_LABEL = f'{LABEL} (simulado)' if SIMULATED else LABEL
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
    """Endereço/link do último sync da central (``devices.charger``), ou ``None`` (firmware antigo).

    Carregador online: ``model`` goodwe_hca_g2/modbus_tcp. Offline: a central declara os limites de
    sempre (esp32_bench/simulated) com o mesmo ``address`` e ``link: offline``."""
    if not reported:
        return None
    address = reported.get('address')
    if address is None:
        return None
    link = reported.get('link')
    return {'model': reported.get('model'), 'transport': reported.get('transport'), 'address': address,
            'link': link if link in ('online', 'offline') else 'offline'}


def link_state(address, reported: Mapping | None, screen_online: bool) -> str | None:
    """``online``/``offline`` pelo último sync da central; ``pending`` = a central (online) ainda não
    confirmou este endereço (firmware antigo ou próximo sync). Central offline → ``offline``."""
    if address is None:
        return None
    if not screen_online:
        return 'offline'
    seen = reported_link(reported)
    if seen is None or seen['address'] != int(address):
        return 'pending'
    return seen['link']


def availability_reason(address, reported: Mapping | None, screen_online: bool) -> str | None:
    """Motivo de indisponibilidade ligado ao hardware, ou ``None`` (pode carregar).

    ``screen_offline``: a central da estação está sem contato. ``charger_offline``: a central tem
    contato, mas o carregador do endereço não respondeu na última leitura (ou a central ainda não
    confirmou este endereço). Firmware antigo, que não reporta ``charger.address``, continua
    como antes (a central carrega com a simulação interna dela): ``None``."""
    if not screen_online:
        return SCREEN_OFFLINE
    if address is None or not reported or reported.get('address') is None:
        return None
    seen = reported_link(reported)
    if seen['address'] != int(address) or seen['link'] != 'online':
        return CHARGER_OFFLINE
    return None


def owner_block(address, reported: Mapping | None, screen_online: bool) -> dict | None:
    """``charger_link`` do dono: endereço configurado, host, estado do link, última leitura OK
    (``last_online_at``), potência lida (``measured_power_w``) e o que a central reportou."""
    block = sync_link(address)
    if block is None:
        return None
    reported = reported or {}
    return {**block, 'label': LABEL, 'simulated': SIMULATED,
            'link': link_state(address, reported or None, screen_online),
            'last_online_at': reported.get('last_online_at'),
            'measured_power_w': reported.get('measured_power_w'),
            'reported': reported_link(reported or None)}


def status_text(block: Mapping | None) -> str:
    """``Carregador 1 · GoodWe HCA G2 (simulado) · online`` (``offline``, ``aguardando a central``);
    vazio sem bloco."""
    if not block or block.get('address') is None:
        return ''
    link = LINK_TEXT.get(block.get('link') or 'pending', WAITING_TEXT)
    return f"Carregador {block['address']} · {STATUS_LABEL} · {link}"
