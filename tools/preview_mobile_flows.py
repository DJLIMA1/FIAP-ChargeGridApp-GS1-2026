"""Open the normal app UI; choose 'Entrar na conta demo' for local simulation.

PYTHONPATH=apps/mobile/src .venv/bin/python tools/preview_mobile_flows.py
http://127.0.0.1:8855 — no scenario dropdown or privileged preview shortcuts.
The explicit demo account uses its isolated in-memory client, never Supabase/ESP.
"""

import os
from pathlib import Path

import flet as ft

from chargegrid_app.app import ASSETS_DIR, main

if __name__ == '__main__':
    client = Path(__file__).resolve().parents[1] / 'apps/mobile/.flet/vector-client/build/web'
    if not client.is_dir():
        raise SystemExit('Primeiro compile o cliente com: .venv/bin/python tools/build_mobile_web_client.py')
    os.environ.setdefault('FLET_WEB_PATH', str(client))
    os.environ['CHARGEGRID_ENABLE_DEMO'] = '1'
    os.environ['FLET_FORCE_WEB_SERVER'] = '1'
    ft.run(main, view=None, host='127.0.0.1', port=8855, assets_dir=ASSETS_DIR)
