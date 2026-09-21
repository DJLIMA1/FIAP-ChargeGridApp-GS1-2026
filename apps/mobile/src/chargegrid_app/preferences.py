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
