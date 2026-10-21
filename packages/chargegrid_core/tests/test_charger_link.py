import pytest

from chargegrid_core.chargers import link


def test_address_accepts_1_to_247_or_none():
    assert link.validate_address(None) is None
    assert link.validate_address(1) == 1
    assert link.validate_address(247) == 247
    for bad in (0, 248, -1):
        with pytest.raises(ValueError, match='entre 1 e 247'):
            link.validate_address(bad)
    for bad in (True, '1', 1.0):
        with pytest.raises(ValueError, match='inteiro'):
            link.validate_address(bad)


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
    assert link.link_state(1, bench, True) == 'pending'  # firmware antigo/sem carregador externo
    assert link.link_state(1, None, True) == 'pending'
    assert link.link_state(1, _reported(state=None), True) == 'offline'


def test_owner_block_and_status_text():
    block = link.owner_block(1, _reported(), True)
    assert block['host'] == 'cg-hca-1.local' and block['link'] == 'online' and block['simulated'] is True
    assert block['reported'] == {'model': 'goodwe_hca_g2', 'transport': 'modbus_tcp', 'address': 1, 'link': 'online'}
    assert link.status_text(block) == 'Carregador 1 · GoodWe HCA G2 (simulado) · online'
    assert link.status_text(link.owner_block(3, None, False)) == 'Carregador 3 · GoodWe HCA G2 (simulado) · offline'
    assert link.status_text(link.owner_block(3, None, True)).endswith('· aguardando a tela')
    assert link.owner_block(None, _reported(), True) is None
    assert link.status_text(None) == ''
