import pytest

from chargegrid_core.chargers import link


def test_address_accepts_1_to_247_and_never_empty():
    with pytest.raises(ValueError, match='não pode ficar vazio'):
        link.validate_address(None)
    assert link.validate_address(1) == 1
    assert link.validate_address(247) == 247
    for bad in (0, 248, -1):
        with pytest.raises(ValueError, match='entre 1 e 247'):
            link.validate_address(bad)
    for bad in (True, '1', 1.0):
        with pytest.raises(ValueError, match='inteiro'):
            link.validate_address(bad)


def test_next_free_address_follows_the_station_order():
    assert link.next_free_address([]) == 1
    assert link.next_free_address([1, 2, None]) == 3
    assert link.next_free_address([2, 5]) == 1  # preenche o primeiro buraco
    assert link.next_free_address([1, 3]) == 2
    with pytest.raises(ValueError, match='livre'):
        link.next_free_address(range(1, 248))


def test_sync_link_block_follows_the_contract():
    assert link.sync_link(None) is None
    assert link.sync_link(1) == {'model': 'goodwe_hca_g2', 'transport': 'modbus_tcp', 'address': 1,
                                 'host': 'cg-hca-1.local'}
    assert link.host_for(12) == 'cg-hca-12.local'


def _reported(address=1, state='online', **extra):
    return {'model': 'goodwe_hca_g2', 'transport': 'modbus_tcp', 'address': address, 'link': state,
            'min_power_w': 1400, 'max_power_w': 7000, 'step_w': 100, **extra}


def test_link_state_comes_from_the_last_screen_sync():
    assert link.link_state(None, _reported(), True) is None
    assert link.link_state(1, _reported(), True) == 'online'
    assert link.link_state(1, _reported(state='offline'), True) == 'offline'
    assert link.link_state(1, _reported(), False) == 'offline'  # tela offline: não dá para saber
    assert link.link_state(1, _reported(address=2), True) == 'pending'  # tela ainda no endereço antigo
    bench = {'model': 'esp32_bench', 'transport': 'simulated', 'min_power_w': 1400, 'max_power_w': 7200}
    assert link.link_state(1, bench, True) == 'pending'  # firmware antigo: sem address/link
    # Firmware novo sem carregador respondendo: limites de sempre com address/link offline.
    simulated = {**bench, 'address': 1, 'link': 'offline'}
    assert link.link_state(1, simulated, True) == 'offline'
    assert link.reported_link(simulated) == {'model': 'esp32_bench', 'transport': 'simulated', 'address': 1,
                                             'link': 'offline'}
    assert link.link_state(1, None, True) == 'pending'
    assert link.link_state(1, _reported(state=None), True) == 'offline'


def test_owner_block_and_status_text():
    block = link.owner_block(1, _reported(last_online_at='2026-10-21T16:00:00+00:00', measured_power_w=3600), True)
    assert block['host'] == 'cg-hca-1.local' and block['link'] == 'online' and block['simulated'] is True
    assert block['reported'] == {'model': 'goodwe_hca_g2', 'transport': 'modbus_tcp', 'address': 1, 'link': 'online'}
    assert block['last_online_at'] == '2026-10-21T16:00:00+00:00' and block['measured_power_w'] == 3600
    assert link.status_text(block) == 'Carregador 1 · GoodWe HCA G2 · online'
    assert link.status_text(link.owner_block(3, None, False)) == 'Carregador 3 · GoodWe HCA G2 · offline'
    waiting = 'Carregador 3 · GoodWe HCA G2 · aguardando a central'
    assert link.status_text(link.owner_block(3, None, True)) == waiting  # tela não confirmou
    offline = link.owner_block(3, _reported(address=3, state='offline'), True)
    assert link.status_text(offline) == 'Carregador 3 · GoodWe HCA G2 · offline'
    assert offline['last_online_at'] is None and offline['measured_power_w'] is None
    assert link.owner_block(None, _reported(), True) is None
    assert link.status_text(None) == ''
    assert 'simulação' not in ''.join(link.LINK_TEXT.values())


def test_availability_reason_is_per_charger():
    assert link.availability_reason(1, _reported(), True) is None
    assert link.availability_reason(1, _reported(), False) == 'screen_offline'  # a tela (estação) caiu
    assert link.availability_reason(1, _reported(state='offline'), True) == 'charger_offline'
    assert link.availability_reason(1, _reported(address=2), True) == 'charger_offline'  # endereço não confirmado
    assert link.availability_reason(1, _reported(state=None), True) == 'charger_offline'
    # Firmware antigo (sem address) ou sem bloco: comportamento de antes (simulação da tela).
    bench = {'model': 'esp32_bench', 'transport': 'simulated', 'min_power_w': 1400, 'max_power_w': 7200}
    assert link.availability_reason(1, bench, True) is None
    assert link.availability_reason(1, None, True) is None
    assert link.availability_reason(None, _reported(state='offline'), True) is None
    assert link.CHARGER_OFFLINE_MESSAGE == 'Carregador offline — use outro ponto desta estação'
