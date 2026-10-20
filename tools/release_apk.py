"""Publica uma nova versão do app Android com um comando.

    .venv/bin/python tools/release_apk.py 0.6.4 "Autocomplete de endereço e correções"

1. sobe ``version`` e ``build_number`` em apps/mobile/pyproject.toml e grava o config empacotado;
2. ``flet build apk`` → ``builds/chargegrid-<versão>.apk`` (e apaga apps/mobile/build, ~2,5 GB);
3. envia o APK e o manifesto ``app/latest.json`` ao Vercel Blob público ``chargegrid-apps``
   (token ``BLOB_READ_WRITE_TOKEN`` do ambiente ou de apps/api/.env.local, criado por ``vercel blob``);
4. registra a versão e o SHA-256 em docs/setup.md, faz commit e push na branch atual.

Os apps instalados (0.6.7 em diante) consultam ``GET /v1/app/latest`` (a API lê o manifesto) ao abrir
e ao voltar ao app, e oferecem o download. O repositório do código pode continuar privado.
``--skip-build`` reaproveita um APK já gerado em builds/; ``--dry-run`` só mostra o que faria.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
MOBILE = ROOT / "apps" / "mobile"
PYPROJECT = MOBILE / "pyproject.toml"
SETUP_DOC = ROOT / "docs" / "setup.md"
BUILDS = ROOT / "builds"
API_ENV = ROOT / "apps" / "api" / ".env.local"
BLOB_PREFIX = "app"
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
            f"Publicado em {datetime.now(ZoneInfo('America/Sao_Paulo')):%d/%m/%Y} no Vercel Blob "
            f"(`{BLOB_PREFIX}/chargegrid-{version}.apk`); os apps instalados oferecem a atualização ao abrir.")
    return line + (f" {notes.strip()}" if notes.strip() else "") + "\n\n"


def with_note(doc, note):
    anchor = re.search(r"^O APK \d+\.\d+\.\d+ \(build", doc, re.MULTILINE)
    return doc[:anchor.start()] + note + doc[anchor.start():] if anchor else doc.rstrip() + "\n\n" + note


def blob_token():
    token = os.environ.get("BLOB_READ_WRITE_TOKEN")
    if not token and API_ENV.exists():
        for line in API_ENV.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "BLOB_READ_WRITE_TOKEN":
                token = value.strip().strip('"').strip("'")
    if not token:
        raise SystemExit("Sem BLOB_READ_WRITE_TOKEN: rode `vercel env pull` em apps/api (ou exporte a variável).")
    return token


def blob_put(path, pathname, token, *, content_type, overwrite=False, max_age=None):
    """``vercel blob put`` público; devolve a URL. O token nunca é impresso."""
    command = ["vercel", "blob", "put", str(path), "--access", "public", "--pathname", pathname,
               "--content-type", content_type, "--non-interactive"]
    if overwrite:
        command += ["--allow-overwrite", "true"]
    if max_age is not None:
        command += ["--cache-control-max-age", str(max_age)]
    print("$", " ".join(command), "--rw-token ***", flush=True)
    env = {key: value for key, value in os.environ.items() if key not in ("VERCEL_OIDC_TOKEN", "BLOB_STORE_ID")}
    result = subprocess.run([*command, "--rw-token", token], cwd=ROOT / "apps" / "api", env=env,
                            capture_output=True, text=True, check=False)
    output = (result.stdout + result.stderr).replace(token, "***")
    url = next((word for word in output.split() if word.startswith("https://") and pathname in word), None)
    if result.returncode or not url:
        raise SystemExit(f"Falha ao enviar {pathname} ao Vercel Blob:\n{output}")
    return url


def _blob_cli(args, token):
    env = {key: value for key, value in os.environ.items() if key not in ("VERCEL_OIDC_TOKEN", "BLOB_STORE_ID")}
    result = subprocess.run(["vercel", "blob", *args, "--rw-token", token], cwd=ROOT / "apps" / "api", env=env,
                            capture_output=True, text=True, check=False)
    return result.returncode, (result.stdout + result.stderr).replace(token, "***")


def old_apk_urls(output, keep_pathname):
    """URLs de ``app/chargegrid-*.apk`` na saída do ``vercel blob list``, exceto o APK que fica."""
    pattern = re.compile(rf"https://\S+/{re.escape(BLOB_PREFIX)}/chargegrid-\d+\.\d+\.\d+\.apk")
    return sorted({url for url in pattern.findall(output) if not url.endswith("/" + keep_pathname)})


def delete_old_apks(token, keep_pathname):
    """Apaga do Blob os APKs anteriores: o plano gratuito tem cota pequena e cada APK tem ~170 MB.

    Roda só depois que o APK novo e o manifesto já estão no ar; uma falha aqui só avisa.
    """
    code, output = _blob_cli(["list", "--prefix", f"{BLOB_PREFIX}/chargegrid-", "--limit", "100"], token)
    if code:
        print(f"Aviso: não consegui listar os APKs antigos para apagar:\n{output}", flush=True)
        return []
    removed = []
    for url in old_apk_urls(output, keep_pathname):
        code, output = _blob_cli(["del", url], token)
        print(f"{'Apagado' if code == 0 else 'Aviso: não apaguei'} {url.rsplit('/', 1)[-1]}", flush=True)
        if code == 0:
            removed.append(url)
    return removed


def manifest(version, build, url, apk, sha, notes):
    return {"version": version, "build": build, "url": url, "size_bytes": apk.stat().st_size, "sha256": sha,
            "notes": notes.strip() or f"ChargeGrid {version}.",
            "published_at": datetime.now(ZoneInfo("UTC")).isoformat(timespec="seconds")}


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
    if shutil.which("vercel") is None:
        raise SystemExit("Instale e autentique o Vercel CLI (vercel login) para publicar no Blob.")
    token = None if args.dry_run else blob_token()
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
        print(f"(dry-run) geraria {apk.relative_to(ROOT)}, enviaria ao Blob ({BLOB_PREFIX}/chargegrid-{args.version}.apk"
              f" e {BLOB_PREFIX}/latest.json), docs/setup.md, commit e push")
        return
    if not apk.exists():
        raise SystemExit(f"APK não encontrado: {apk}")
    sha = hashlib.sha256(apk.read_bytes()).hexdigest()
    # APK primeiro; o manifesto só aponta para a versão nova quando o arquivo já está no ar.
    url = blob_put(apk, f"{BLOB_PREFIX}/chargegrid-{args.version}.apk", token,
                   content_type="application/vnd.android.package-archive")
    with tempfile.TemporaryDirectory() as folder:
        latest = Path(folder) / "latest.json"
        latest.write_text(json.dumps(manifest(args.version, build, url, apk, sha, args.notes), ensure_ascii=False),
                          encoding="utf-8")
        blob_put(latest, f"{BLOB_PREFIX}/latest.json", token, content_type="application/json", overwrite=True, max_age=60)
    # Só a versão nova fica no Blob (o manifesto já aponta para ela).
    delete_old_apks(token, f"{BLOB_PREFIX}/chargegrid-{args.version}.apk")
    SETUP_DOC.write_text(with_note(SETUP_DOC.read_text(encoding="utf-8"),
                                   setup_note(args.version, build, sha, args.notes)), encoding="utf-8")
    run(["git", "add", PYPROJECT, SETUP_DOC], False)
    run(["git", "commit", "-m", f"Release app {args.version} (build {build})"], False)
    run(["git", "push"], False)
    print(f"\nPublicado: {args.version} · {apk.stat().st_size / 1_048_576:.0f} MB · SHA-256 {sha}\n{url}")


if __name__ == "__main__":
    sys.exit(main())
