"""Opt-in physical simulated-panel reserve/reboot/cancel acceptance test.

Requires explicit QA state and serial port. Never starts charging, changes an
owner, or changes Wi-Fi. Resets the ESP32 only while our QA reservation is held.
"""
import argparse
import time
from pathlib import Path
from uuid import uuid4

import serial
from qa_live import Acceptance


def run(api, state, serial_path):
    qa = Acceptance(api, state)
    qa.login('consumer')
    assert qa.call('GET', 'reservations/current') is None, 'QA account already busy'
    assert qa.call('GET', 'charging-sessions/current') is None, 'QA account already charging'

    def point():
        return next(p for p in qa.call('GET', 'stations/' + qa.state['station'])['connectors']
                    if p['id'] == qa.state['panel']['connector_id'])

    assert point()['available'], 'Panel not available; do not reset'
    port = serial.Serial(baudrate=115200, timeout=0.15)
    port.dtr = False
    port.rts = False
    port.port = serial_path
    reservation = None
    try:
        port.open()

        def status_wait(expected, timeout=65, require_boot=False):
            deadline = time.monotonic() + timeout
            last_request = 0
            boot_seen = not require_boot
            while time.monotonic() < deadline:
                if time.monotonic() - last_request >= 1:
                    port.write(b'CG_STATUS\n')
                    last_request = time.monotonic()
                line = port.readline().decode(errors='replace').strip()
                if line.startswith('ESP-ROM:esp32s3'):
                    boot_seen = True
                if (boot_seen and line.startswith('[status]') and 'firmware=0.3.0' in line
                        and f'state={expected} ' in line and 'http=200' in line
                        and 'wifi=connected' in line and 'synced=yes' in line):
                    print('PASS physical panel', expected, 'firmware 0.3.0, HTTP 200, Wi-Fi connected', flush=True)
                    return
            raise AssertionError('Panel failed to reach expected synchronized state: ' + expected)

        def wait_reservation(expected, timeout=40):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                current = qa.call('GET', 'reservations/current')
                if (current or {}).get('status') == expected:
                    return current
                time.sleep(1)
            raise AssertionError('Reservation did not reconcile: ' + str(expected))

        status_wait('idle')
        reservation = qa.call('POST', 'reservations', body={'connector_id': qa.state['panel']['connector_id']},
                              key=str(uuid4()), status=202)
        status_wait('reserved')
        before = wait_reservation('confirmed')
        assert point()['availability_status'] == 'reserved'
        # Reset through EN/RTS: firmware boots afresh from its real NVS journal.
        port.reset_input_buffer()
        port.rts = True
        time.sleep(0.15)
        port.rts = False
        status_wait('reserved', require_boot=True)
        after = wait_reservation('confirmed')
        assert after['id'] == before['id'] and after['expires_at'] == before['expires_at']
        assert point()['availability_status'] == 'reserved'
        qa.checked('physical ESP32 reboot restores reservation with identical deadline')
    finally:
        if reservation:
            qa.call('POST', 'reservations/' + reservation['id'] + '/cancel', status=202)
            status_wait('idle')
            wait_reservation(None)
            assert point()['available']
            qa.checked('physical cancellation returns panel and API to available')
        port.close()
        qa.client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--port', required=True)
    args = parser.parse_args()
    run(args.api, args.state, args.port)
