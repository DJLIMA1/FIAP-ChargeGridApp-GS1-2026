import json
import os
from pathlib import Path
from urllib.parse import urlparse

ROOT_ENV_FILE = Path(__file__).resolve().parents[4] / '.env'
PACKAGED_CONFIG_FILE = Path(__file__).resolve().parents[2] / 'assets' / 'app_config.json'


def load_development_environment():
    try:
        for line in ROOT_ENV_FILE.read_text().splitlines():
            key, separator, value = line.strip().partition('=')
            if separator and key == 'CHARGEGRID_API_URL':
                os.environ.setdefault(key, value.strip().strip('"').strip("'"))
    except OSError:
        pass


def packaged_api_url(path=PACKAGED_CONFIG_FILE):
    try:
        value = json.loads(path.read_text()).get('api_url')
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, str) else None


def validate_api_url(value):
    value = value.rstrip('/')
    parsed = urlparse(value)
    local = parsed.hostname in {'localhost', '127.0.0.1', '::1'}
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and local):
        raise ValueError('A API exige HTTPS; HTTP é permitido apenas em localhost para testes.')
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Endereço da API inválido.')
    return value


def api_url():
    load_development_environment()
    value = os.getenv('CHARGEGRID_API_URL') or packaged_api_url()
    return validate_api_url(value or 'https://chargegrid.example.com/v1')
