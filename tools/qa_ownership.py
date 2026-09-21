"""Opt-in live QR ownership/reboot test using explicit private QA artifacts.

Does not create accounts or replace existing owners. Requires a fresh, inactive
factory point and QA accounts. Leaves the test point owned, inactive and idle.
"""
import argparse
import json
from pathlib import Path
from uuid import uuid4

from device_simulator import Device
from qa_live import Acceptance


def run(api, state, factory_path):
    factory = json.loads(factory_path.read_text())
    qa = Acceptance(api, state)
    headers = {'Authorization': 'Device ' + factory['device_key']}
    device = Device()

    def sync():
        result = qa.call('POST', 'devices/sync', headers=headers, body=device.payload())
        device.response(result)
        return result

    qa.login('consumer')
    assert qa.call('GET', 'reservations/current') is None, 'QA account already has a reservation'
    assert qa.call('GET', 'charging-sessions/current') is None, 'QA account already has a session'
    qa.call('POST', 'ownership/claim', body={'token': factory['claim_token']}, status=403)
    qa.checked('consumer cannot claim ownership')
    assert sync()['connector']['owned'] is False, 'Use a fresh factory artifact'
    qa.login('vendor')
    claim = qa.call('POST', 'ownership/claim', body={'token': factory['claim_token']})
    retry = qa.call('POST', 'ownership/claim', body={'token': factory['claim_token']})
    assert retry['already_claimed'] and retry['connector_id'] == claim['connector_id']
    assert sync()['connector']['owned'] is True
    station_id = claim['station_id']
    connector_id = claim['connector_id']
    station = qa.call('GET', 'stations/' + station_id)
    assert not station['active']
    assert not next(p for p in station['connectors'] if p['id'] == connector_id)['available']
    qa.checked('factory claim, idempotent retry, owned sync and inactive first setup')
    qa.call('PATCH', 'stations/' + station_id, body={
        'name': 'QA QR — bancada simulada', 'address': 'Equipamento de teste de vinculação',
        'latitude': -23.5505, 'longitude': -46.6333, 'active': True,
    })
    qa.call('PATCH', 'connectors/' + connector_id, body={'active': True})
    qa.login('consumer')
    reservation = None
    try:
        reservation = qa.call('POST', 'reservations', body={'connector_id': connector_id},
                              key=str(uuid4()), status=202)
        sync()
        sync()
        before = qa.call('GET', 'reservations/current')
        assert before['status'] == 'confirmed'
        # Real HTTP/backend, fresh boot with no local reservation (same as power cycle).
        device = Device()
        restore = sync()
        assert any(c['type'] == 'RESERVE' for c in restore['commands'])
        sync()
        after = qa.call('GET', 'reservations/current')
        assert after['id'] == before['id'] and after['expires_at'] == before['expires_at']
        point = next(p for p in qa.call('GET', 'stations/' + station_id)['connectors'] if p['id'] == connector_id)
        assert point['availability_status'] == 'reserved' and not point['available']
        qa.checked('HTTP reboot restores reserved state without changing reservation deadline')
    finally:
        if reservation:
            qa.call('POST', 'reservations/' + reservation['id'] + '/cancel', status=202)
            sync()
            sync()
            assert qa.call('GET', 'reservations/current') is None
        qa.login('vendor')
        qa.call('PATCH', 'connectors/' + connector_id, body={'active': False})
        qa.call('PATCH', 'stations/' + station_id, body={'active': False})
    qa.checked('cancellation reconciles and QA point left inactive with ownership retained')
    qa.client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--factory', type=Path, required=True)
    args = parser.parse_args()
    run(args.api, args.state, args.factory)
