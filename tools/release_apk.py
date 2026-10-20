"""Publica uma nova versão do app Android com um comando.

    .venv/bin/python tools/release_apk.py 0.6.4 "Autocomplete de endereço e correções"

1. sobe ``version`` e ``build_number`` em apps/mobile/pyproject.toml e grava o config empacotado;
2. ``flet build apk`` → ``builds/chargegrid-<versão>.apk`` (e apaga apps/mobile/build, ~2,5 GB);
3. registra a versão e o SHA-256 em docs/setup.md, faz commit e push na branch atual;
4. cria a release pública ``app-v<versão>`` no GitHub com o APK.

Os apps instalados (0.6.4 em diante) consultam essa release ao abrir e oferecem o download.
``--skip-build`` reaproveita um APK já gerado em builds/; ``--dry-run`` só mostra o que faria.
"""
import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
MOBILE = ROOT / "apps" / "mobile"
PYPROJECT = MOBILE / "pyproject.toml"
SETUP_DOC = ROOT / "docs" / "setup.md"
BUILDS = ROOT / "builds"
PYTHON = ROOT / ".venv" / "bin" / "python"
FLET = ROOT / ".venv" / "bin" / "flet"
MIN_FREE_GB = 4


def parse(version):
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise SystemExit(f"Versão inválida: {version!r} (use X.Y.Z)")
    return tuple(int(part) for part in match.groups())


def current(text):
    version = re.search(r'^version = "([^"]+)"', text, re.MULTILINE).group(1)
    build = int(re.search(r"^build_number = (\d+)", text, re.MULTILINE).group(1))
    return version, build


def bumped(text, version, build):
    text = re.sub(r'^version = "[^"]+"', f'version = "{version}"', text, count=1, flags=re.MULTILINE)
    return re.sub(r"^build_number = \d+", f"build_number = {build}", text, count=1, flags=re.MULTILINE)


def setup_note(version, build, sha, notes):
    line = (f"O APK {version} (build {build}) está em `builds/chargegrid-{version}.apk` (SHA-256 `{sha}`). "
            f"Publicado em {datetime.now(ZoneInfo("America/Sao_Paulo")):%d/%m/%Y} na release `app-v{version}` do GitHub; os apps instalados "
            f"oferecem a atualização ao abrir.")
    return line + (f" {notes.strip()}" if notes.strip() else "") + "\n\n"


def with_note(doc, note):
    anchor = re.search(r"^O APK \d+\.\d+\.\d+ \(build", doc, re.MULTILINE)
    return doc[:anchor.start()] + note + doc[anchor.start():] if anchor else doc.rstrip() + "\n\n" + note


def run(command, dry_run, cwd=ROOT):
    print("$", " ".join(str(part) for part in command), flush=True)
    if not dry_run:
        subprocess.run([str(part) for part in command], cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version", help="nova versão X.Y.Z (maior que a atual)")
    parser.add_argument("notes", nargs="?", default="", help="o que mudou (aparece no aviso do app)")
    parser.add_argument("--skip-build", action="store_true", help="usar builds/chargegrid-<versão>.apk já gerado")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    text = PYPROJECT.read_text(encoding="utf-8")
    old_version, old_build = current(text)
    if parse(args.version) <= parse(old_version) and not args.skip_build:
        raise SystemExit(f"A versão nova ({args.version}) precisa ser maior que a atual ({old_version}).")
    build = old_build if args.skip_build and args.version == old_version else old_build + 1
    apk = BUILDS / f"chargegrid-{args.version}.apk"
    if shutil.which("gh") is None:
        raise SystemExit("Instale e autentique o GitHub CLI (gh auth login) para publicar a release.")
    if not args.skip_build and shutil.disk_usage(ROOT).free < MIN_FREE_GB * 1024 ** 3:
        raise SystemExit(f"Libere espaço: o build precisa de pelo menos {MIN_FREE_GB} GB livres.")

    print(f"Versão {old_version} (build {old_build}) -> {args.version} (build {build})", flush=True)
    if not args.dry_run:
        PYPROJECT.write_text(bumped(text, args.version, build), encoding="utf-8")
    run([PYTHON, ROOT / "tools" / "configure_mobile.py"], args.dry_run)
    if not args.skip_build:
        run([FLET, "build", "apk", ".", "--yes"], args.dry_run, cwd=MOBILE)
        if not args.dry_run:
            BUILDS.mkdir(exist_ok=True)
            shutil.copyfile(MOBILE / "build" / "apk" / "chargegrid.apk", apk)
            shutil.rmtree(MOBILE / "build", ignore_errors=True)
    if args.dry_run:
        print(f"(dry-run) geraria {apk.relative_to(ROOT)}, docs/setup.md, commit, push e release app-v{args.version}")
        return
    if not apk.exists():
        raise SystemExit(f"APK não encontrado: {apk}")
    sha = hashlib.sha256(apk.read_bytes()).hexdigest()
    SETUP_DOC.write_text(with_note(SETUP_DOC.read_text(encoding="utf-8"),
                                   setup_note(args.version, build, sha, args.notes)), encoding="utf-8")
    run(["git", "add", PYPROJECT, SETUP_DOC], False)
    run(["git", "commit", "-m", f"Release app {args.version} (build {build})"], False)
    run(["git", "push"], False)
    run(["gh", "release", "create", f"app-v{args.version}", apk, "--title", f"ChargeGrid {args.version}",
         "--notes", args.notes or f"ChargeGrid {args.version} (build {build}).", "--latest"], False)
    print(f"\nPublicado: app-v{args.version} · {apk.stat().st_size / 1_048_576:.0f} MB · SHA-256 {sha}")


if __name__ == "__main__":
    sys.exit(main())
