"""Ponto de entrada do dashboard web do proprietário.

Execute na raiz do repositório:

    CHARGEGRID_ENABLE_DEMO=1 flet run --web -p 8610 apps/dashboard/main.py
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# O dashboard importa o app (tema, componentes, ApiClient, demo) e chargegrid_core
# diretamente de apps/mobile/src. Em um build empacotado, ficam em ./src (veja README).
for path in (HERE, HERE / 'src', HERE.parent / 'mobile' / 'src'):
    if path.is_dir() and str(path) not in sys.path:
        sys.path.insert(0, str(path))


def run():
    import flet as ft

    from chargegrid_dashboard.app import ASSETS_DIR, main

    ft.run(main, assets_dir=ASSETS_DIR)


if __name__ == '__main__':
    run()
