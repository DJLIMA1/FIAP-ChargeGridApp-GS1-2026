"""Lançador temporário para a estrutura anterior do projeto."""

from pathlib import Path
import sys


MOBILE_SRC = Path(__file__).resolve().parents[1] / "apps" / "mobile" / "src"
sys.path.insert(0, str(MOBILE_SRC))

from chargegrid_app.main import run


if __name__ == "__main__":
    run()
