import json
import os
from pathlib import Path

DEFAULT_DARK_MODE = True


class Preferences:
    def __init__(self, path=None):
        storage = Path(os.environ.get('FLET_APP_STORAGE_DATA') or Path.home() / '.chargegrid')
        self.path = Path(path or storage / 'preferences.json')

    def load(self):
        try:
            data = json.loads(self.path.read_text())
            value = data.get('dark_mode', DEFAULT_DARK_MODE) if isinstance(data, dict) else DEFAULT_DARK_MODE
            return value if isinstance(value, bool) else DEFAULT_DARK_MODE
        except (OSError, ValueError, TypeError):
            return DEFAULT_DARK_MODE

    def save(self, dark):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({'dark_mode': bool(dark)}))
            return True
        except OSError:
            return False


class DriverProfileStore:
    """Perfil do Modo Motorista salvo no aparelho (veículo, turno, refeições e última bateria).

    Arquivo separado de ``preferences.json`` para que salvar o tema não apague o perfil.
    """

    def __init__(self, path=None):
        storage = Path(os.environ.get('FLET_APP_STORAGE_DATA') or Path.home() / '.chargegrid')
        self.path = Path(path or storage / 'driver_profile.json')

    def load(self):
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError, TypeError):
            return None
        if not isinstance(data, dict) or not isinstance(data.get('vehicle'), dict) \
                or not isinstance(data.get('preferences'), dict):
            return None
        return data

    def save(self, profile):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(profile, ensure_ascii=False))
            return True
        except (OSError, TypeError, ValueError):
            return False
