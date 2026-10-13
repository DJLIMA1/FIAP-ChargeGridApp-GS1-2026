"""Copia packages/chargegrid_core para o app Flet e para a API.

Uso: python tools/sync_core.py [--check]
"""
from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packages" / "chargegrid_core" / "chargegrid_core"
TARGETS = (ROOT / "apps" / "mobile" / "src" / "chargegrid_core", ROOT / "apps" / "api" / "chargegrid_core")
HEADER = "# Cópia gerada por tools/sync_core.py — edite packages/chargegrid_core.\n"


def _sources():
    return sorted(p for p in SOURCE.rglob("*.py") if "__pycache__" not in p.parts)


def differences() -> list[str]:
    problems = []
    for target in TARGETS:
        expected = {p.relative_to(SOURCE) for p in _sources()}
        actual = {p.relative_to(target) for p in target.rglob("*.py") if "__pycache__" not in p.parts} \
            if target.exists() else set()
        for rel in sorted(expected | actual):
            src, dst = SOURCE / rel, target / rel
            if not dst.exists() or not src.exists() or not filecmp.cmp(src, dst, shallow=False):
                problems.append(str(dst.relative_to(ROOT)))
    return problems


def sync() -> None:
    for target in TARGETS:
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(SOURCE, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


if __name__ == "__main__":
    if "--check" in sys.argv:
        diff = differences()
        print("\n".join(diff) or "chargegrid_core sincronizado")
        sys.exit(1 if diff else 0)
    sync()
    print("chargegrid_core sincronizado em", ", ".join(str(t.relative_to(ROOT)) for t in TARGETS))
