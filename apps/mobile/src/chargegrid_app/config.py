import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

_HERE = Path(__file__).resolve()
# Em pacotes (APK, Pyodide) a árvore de diretórios é rasa: sem .env da raiz.
ROOT_ENV_FILE = _HERE.parents[4] / '.env' if len(_HERE.parents) > 4 else None
PACKAGED_CONFIG_FILE = _HERE.parents[2] / 'assets' / 'app_config.json'
# Opções de build aplicadas por quem empacota (ex.: dashboard web publicado com
# dashboard_config.json). O app/APK não chama set_build_options: tudo desligado.
_BUILD_OPTIONS = {}


def set_build_options(demo=None, api_url=None):
    _BUILD_OPTIONS.clear()
    if demo is True:
        _BUILD_OPTIONS['demo'] = True
    if isinstance(api_url, str) and api_url.strip():
        _BUILD_OPTIONS['api_url'] = api_url.strip()


def load_build_options(path):
    """Lê um JSON empacotado (``{"demo": true, "api_url": "/v1"}``); ausente/inválido = nada muda."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    set_build_options(demo=data.get('demo'), api_url=data.get('api_url'))
    return True


def demo_enabled():
    """The isolated demo requires an explicit opt-in.

    Development uses CHARGEGRID_ENABLE_DEMO=1; the public web dashboard opts in via
    its packaged build options. Packaged app builds receive neither; absence fails closed.
    """
    return os.getenv('CHARGEGRID_ENABLE_DEMO') == '1' or _BUILD_OPTIONS.get('demo') is True


def running_in_browser():
    return sys.platform == 'emscripten'


def browser_origin():
    """``window.location.origin`` no Pyodide (janela ou web worker); ``None`` fora dele."""
    try:
        import js  # módulo do Pyodide
        origin = str(js.location.origin)
    except Exception:  # fora do navegador ou sem location
        return None
    return origin if origin.startswith(('http://', 'https://')) else None


def load_development_environment():
    if ROOT_ENV_FILE is None:
        return
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


def packaged_version(path=PACKAGED_CONFIG_FILE):
    """Versão gravada no build (``tools/configure_mobile.py``); ``None`` fora de um APK configurado."""
    try:
        value = json.loads(path.read_text()).get('version')
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


def same_origin_api_url(override=None):
    """No navegador a API fica na mesma origem (``<origin>/v1``, reescrito pela hospedagem): sem CORS.

    ``override`` absoluto é usado como está; relativo (``/v1``) é resolvido na origem da página.
    """
    if override and not override.startswith('/'):
        return override
    origin = browser_origin()
    return origin + (override or '/v1') if origin else None


def api_url():
    if running_in_browser():
        value = same_origin_api_url(_BUILD_OPTIONS.get('api_url'))
        return validate_api_url(value or 'https://chargegrid.example.com/v1')
    load_development_environment()
    override = _BUILD_OPTIONS.get('api_url')
    if override and override.startswith('/'):
        override = None  # caminho relativo só faz sentido no navegador
    value = os.getenv('CHARGEGRID_API_URL') or override or packaged_api_url()
    return validate_api_url(value or 'https://chargegrid.example.com/v1')
