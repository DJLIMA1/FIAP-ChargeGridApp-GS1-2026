import json
import os
from pathlib import Path


class Preferences:
    def __init__(self, path=None):
        storage = Path(os.environ.get('FLET_APP_STORAGE_DATA') or Path.home() / '.chargegrid')
        self.path = Path(path or storage / 'preferences.json')

    def load(self):
        try:
            data = json.loads(self.path.read_text())
            value = data.get('dark_mode', True) if isinstance(data, dict) else True
            return value if isinstance(value, bool) else True
        except (OSError, ValueError, TypeError):
            return True

    def save(self, dark):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({'dark_mode': bool(dark)}))
            return True
        except OSError:
            return False
