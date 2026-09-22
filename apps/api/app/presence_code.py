"""Short lived station code delivered only to an authenticated physical panel."""

import hashlib
import hmac
from datetime import datetime, timezone

from .models import now

PERIOD_SECONDS = 300


def current_code(station, at=None):
    at = at or now()
    slot = int(at.timestamp()) // PERIOD_SECONDS
    message = f"{station.id}:{slot}".encode()
    digest = hmac.new(bytes.fromhex(station.presence_secret), message, hashlib.sha256).digest()
    code = f"#F{int.from_bytes(digest[:8], 'big') % 100000:05d}"
    expires_at = datetime.fromtimestamp((slot + 1) * PERIOD_SECONDS, timezone.utc)
    return code, expires_at


def valid_code(station, supplied, at=None):
    if not supplied:
        return False
    expected, _ = current_code(station, at)
    return hmac.compare_digest(expected, supplied.upper())
