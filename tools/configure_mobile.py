"""Generate the public API configuration that is packaged with the Flet app."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parents[1]
ROOT_ENV_FILE = ROOT_DIR / ".env"
MOBILE_CONFIG_FILE = ROOT_DIR / "apps" / "mobile" / "assets" / "app_config.json"


def validate_api_url(value: str) -> str:
    value = value.rstrip("/")
    parsed = urlparse(value)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise ValueError("A API exige HTTPS; HTTP é permitido apenas em localhost para testes.")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Endereço da API inválido.")
    return value


def api_url_from_env(path: Path) -> str:
    try:
        lines = path.open(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Arquivo de configuração não encontrado: {path}") from exc

    with lines:
        for line in lines:
            key, separator, value = line.strip().partition("=")
            if separator and key == "CHARGEGRID_API_URL":
                return validate_api_url(value.strip().strip('"').strip("'"))
    raise ValueError("CHARGEGRID_API_URL não está definido no arquivo de configuração.")


def configure_mobile(env_file: Path = ROOT_ENV_FILE, output: Path = MOBILE_CONFIG_FILE) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"api_url": api_url_from_env(env_file)}, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT_ENV_FILE)
    parser.add_argument("--output", type=Path, default=MOBILE_CONFIG_FILE)
    args = parser.parse_args()
    configure_mobile(args.env_file, args.output)


if __name__ == "__main__":
    main()
