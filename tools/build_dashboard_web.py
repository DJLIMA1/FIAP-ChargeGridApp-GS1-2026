"""Gera o dashboard web como site estático (``flet build web``) pronto para a Vercel.

O Python roda no navegador (Pyodide). O dashboard importa ``chargegrid_app`` e
``chargegrid_core`` de ``apps/mobile/src``; este script monta um diretório de
build com tudo lado a lado, empacota, confere que nada privado foi junto e
prepara o diretório de deploy::

    .venv/bin/python tools/build_dashboard_web.py
    cd apps/dashboard/build/vercel && vercel --prod

Saídas (ignoradas pelo git):

- ``apps/dashboard/build/web-src``: fonte montada para o ``flet build``;
- ``apps/dashboard/build/web-src/build/web``: saída do ``flet build web``;
- ``apps/dashboard/build/vercel``: ``vercel.json`` + ``public/`` (o site).
"""

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = ROOT_DIR / "apps" / "dashboard"
MOBILE_DIR = ROOT_DIR / "apps" / "mobile"
DEFAULT_STAGING = DASHBOARD_DIR / "build" / "web-src"
DEFAULT_DEPLOY = DASHBOARD_DIR / "build" / "vercel"
VERCEL_TEMPLATE = DASHBOARD_DIR / "vercel.json"
CONFIG_NAME = "dashboard_config.json"

# Só o que o painel usa: fontes Barlow, ícone/marca e ícones do formulário de posto.
ASSETS = (
    "Barlow-Regular.ttf", "Barlow-Medium.ttf", "Barlow-SemiBold.ttf",
    "BarlowCondensed-Bold.ttf", "BarlowCondensed-Medium.ttf", "BarlowCondensed-SemiBold.ttf",
    "Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf",
    "icon.png", "brand_mark.svg", "figma",
)
# Prévia local de IA (fala direto com o OpenRouter) e arquivos locais nunca vão para o site.
PRIVATE_FILES = ("demo_ai.py",)
IGNORED = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache", ".env", ".env.*", "app_config.json", *PRIVATE_FILES,
)
# Arquivos da saída que o navegador nunca pede (símbolos de depuração, CLI do Pyodide).
UNUSED_OUTPUT = ("*.symbols", "*.map", "*.d.ts", ".last_build_id", "pyodide/python", "pyodide/python.bat",
                 "pyodide/python.exe", "pyodide/python_cli_entry.mjs", "pyodide/package.json")
FORBIDDEN_IN_PACKAGE = (b"OPENROUTER_API_KEY", b"sk-or-", b"DATABASE_URL=", b"SUPABASE_SERVICE")


def stage(staging: Path, demo: bool = True, api_url: str | None = None) -> Path:
    """Monta a fonte do build: main.py, chargegrid_dashboard, src/{chargegrid_app,chargegrid_core}, assets."""
    if staging.exists():
        # Mantém o cache do Flutter (build/flutter) para builds incrementais; troca só a fonte.
        for child in staging.iterdir():
            if child.name != "build":
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    staging.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DASHBOARD_DIR / "main.py", staging / "main.py")
    shutil.copy2(DASHBOARD_DIR / "pyproject.toml", staging / "pyproject.toml")
    shutil.copytree(DASHBOARD_DIR / "chargegrid_dashboard", staging / "chargegrid_dashboard", ignore=IGNORED)
    for package in ("chargegrid_app", "chargegrid_core"):
        shutil.copytree(MOBILE_DIR / "src" / package, staging / "src" / package, ignore=IGNORED)
    assets = staging / "assets"
    assets.mkdir()
    for name in ASSETS:
        source = MOBILE_DIR / "assets" / name
        if source.is_dir():
            shutil.copytree(source, assets / name, ignore=IGNORED)
        else:
            shutil.copy2(source, assets / name)
    config = {"demo": bool(demo)}
    if api_url:
        config["api_url"] = api_url
    # Fica na raiz do app (dentro do app.zip): no web, assets/ é servido por HTTP, não pelo Python.
    (staging / CONFIG_NAME).write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return staging


def flet_executable() -> str:
    candidate = Path(sys.executable).with_name("flet")
    if candidate.exists():
        return str(candidate)
    found = shutil.which("flet")
    if not found:
        raise SystemExit("flet não encontrado; use o venv do app (.venv/bin/python).")
    return found


def build(staging: Path, cdn: bool = False, verbose: bool = False) -> Path:
    command = [
        flet_executable(), "build", "web", str(staging), "--yes", "--skip-flutter-doctor",
        "--base-url", "/", "--route-url-strategy", "hash",
        "--product", "ChargeGrid Painel", "--description", "Painel do proprietário de postos ChargeGrid",
        "--pwa-background-color", "#131313", "--pwa-theme-color", "#D72B32",
        "--splash-color", "#131313", "--splash-dark-color", "#131313",
    ]
    if not cdn:
        command.append("--no-cdn")  # Pyodide, CanvasKit e fontes servidos pela própria Vercel
    if verbose:
        command.append("-v")
    subprocess.run(command, cwd=staging, check=True)
    output = staging / "build" / "web"
    if not (output / "index.html").is_file():
        raise SystemExit(f"Build sem index.html em {output}")
    return output


def verify(output: Path) -> None:
    """Falha se o pacote Python levar a prévia de IA, .env ou algo com cara de segredo."""
    archive = output / "assets" / "app" / "app.zip"
    if not archive.is_file():
        raise SystemExit(f"Pacote Python ausente: {archive}")
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        leaked = [name for name in names
                  if Path(name).name in PRIVATE_FILES or Path(name).stem in {Path(p).stem for p in PRIVATE_FILES}
                  or Path(name).name.startswith(".env")]
        if leaked:
            raise SystemExit(f"Arquivos privados no pacote web: {leaked}")
        for name in names:
            data = bundle.read(name)
            for marker in FORBIDDEN_IN_PACKAGE:
                if marker in data:
                    raise SystemExit(f"Possível segredo ({marker.decode()}) em {name}")
        if CONFIG_NAME not in names:
            raise SystemExit(f"{CONFIG_NAME} ausente do pacote web")


def prepare_deploy(output: Path, deploy: Path) -> Path:
    if deploy.exists():
        vercel_link = deploy / ".vercel"
        keep = vercel_link.is_dir()
        if keep:  # preserva o vínculo com o projeto da Vercel entre builds
            saved = deploy.parent / ".vercel-link"
            shutil.rmtree(saved, ignore_errors=True)
            shutil.move(str(vercel_link), saved)
        shutil.rmtree(deploy)
        deploy.mkdir(parents=True)
        if keep:
            shutil.move(str(saved), vercel_link)
    deploy.mkdir(parents=True, exist_ok=True)
    shutil.copytree(output, deploy / "public")
    prune(deploy / "public")
    shutil.copy2(VERCEL_TEMPLATE, deploy / "vercel.json")
    return deploy


def prune(site: Path) -> None:
    for pattern in UNUSED_OUTPUT:
        for path in site.glob(pattern) if "/" in pattern else site.rglob(pattern):
            if path.is_file():
                path.unlink()


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--deploy", type=Path, default=DEFAULT_DEPLOY)
    parser.add_argument("--api-url", help="URL da API (padrão: mesma origem, <site>/v1 reescrito pela Vercel)")
    parser.add_argument("--no-demo", action="store_true", help="publica sem o botão 'Entrar na conta demo'")
    parser.add_argument("--cdn", action="store_true", help="carrega Pyodide/CanvasKit de CDNs (site menor)")
    parser.add_argument("--stage-only", action="store_true", help="só monta a fonte, sem flet build")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    staging = stage(args.staging.resolve(), demo=not args.no_demo, api_url=args.api_url)
    print(f"Fonte montada em {staging}")
    if args.stage_only:
        return 0
    output = build(staging, cdn=args.cdn, verbose=args.verbose)
    verify(output)
    deploy = prepare_deploy(output, args.deploy.resolve())
    print(f"Build web: {output} ({directory_size(output) / 1e6:.1f} MB)")
    print(f"Site (public): {directory_size(deploy / 'public') / 1e6:.1f} MB")
    print(f"Deploy pronto: {deploy}  →  cd '{deploy}' && vercel --prod")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
