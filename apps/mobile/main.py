"""Ponto de entrada do Flet para executar e empacotar o aplicativo mobile."""

import sys
from pathlib import Path


def run():
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

    from chargegrid_app.main import run as chargegrid_run

    chargegrid_run()


if __name__ == "__main__":
    run()
