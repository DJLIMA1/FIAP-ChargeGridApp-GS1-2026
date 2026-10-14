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


class PendingVehicleStore:
    """Carro escolhido no cadastro enquanto a conta aguarda a confirmação do e-mail.

    Fica no aparelho, indexado pelo hash do e-mail, e é aplicado no primeiro login dessa conta.
    """

    def __init__(self, path=None):
        storage = Path(os.environ.get('FLET_APP_STORAGE_DATA') or Path.home() / '.chargegrid')
        self.path = Path(path or storage / 'pending_vehicle.json')

    @staticmethod
    def key(email):
        import hashlib
        return hashlib.sha256(str(email or '').strip().casefold().encode()).hexdigest()

    def _read(self):
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError, TypeError):
            return {}
        return {key: value for key, value in data.items() if isinstance(value, dict)} if isinstance(data, dict) else {}

    def _write(self, data):
        try:
            if not data:
                self.path.unlink(missing_ok=True)
                return True
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, ensure_ascii=False))
            return True
        except (OSError, TypeError, ValueError):
            return False

    def load(self, email):
        return self._read().get(self.key(email)) if email else None

    def save(self, email, vehicle):
        if not email or not isinstance(vehicle, dict):
            return False
        return self._write({**self._read(), self.key(email): vehicle})

    def clear(self, email):
        data = self._read()
        return True if data.pop(self.key(email), None) is None else self._write(data)
