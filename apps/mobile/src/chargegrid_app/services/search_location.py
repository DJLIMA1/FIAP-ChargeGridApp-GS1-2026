"""One explicitly saved search per account on this device; no location capture."""

import hashlib
import json
import math
import os
from pathlib import Path
from uuid import uuid4


class SearchLocation:
    def __init__(self, user_id, directory=None):
        storage = Path(directory or os.environ.get('FLET_APP_STORAGE_DATA') or Path.home() / '.chargegrid')
        account = hashlib.sha256(str(user_id).encode()).hexdigest() if user_id else None
        self.path = storage / f'search-location-{account}.json' if account else None

    @staticmethod
    def validated(data):
        if not isinstance(data, dict):
            return None
        try:
            lat, lng, radius = (float(data[key]) for key in ('lat', 'lng', 'radius'))
            if not all(math.isfinite(value) for value in (lat, lng, radius)):
                return None
            if not -90 <= lat <= 90 or not -180 <= lng <= 180 or not 0 < radius <= 500:
                return None
            query = data.get('query') or ''
            if not isinstance(query, str) or len(query) > 300:
                return None
            return {'lat': lat, 'lng': lng, 'radius': radius, 'query': query}
        except (KeyError, ValueError, TypeError):
            return None

    def load(self):
        if self.path is None:
            return None
        try:
            return self.validated(json.loads(self.path.read_text()))
        except (OSError, ValueError):
            return None

    def save(self, data):
        data = self.validated(data)
        if self.path is None or data is None:
            return False
        temporary = self.path.with_name(self.path.name + f'.{uuid4().hex}.tmp')
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open('x', encoding='utf-8') as output:
                temporary.chmod(0o600)
                output.write(json.dumps(data, ensure_ascii=False))
            temporary.replace(self.path)
            return True
        except OSError:
            return False
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def remove(self):
        if self.path is None:
            return True
        try:
            self.path.unlink(missing_ok=True)
            return True
        except OSError:
            return False
