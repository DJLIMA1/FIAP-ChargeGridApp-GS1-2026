from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from app.presence_code import current_code, valid_code


def test_station_code_rotates_on_five_minute_boundary():
    station = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        presence_secret="b8" * 32,
    )
    before = datetime(2026, 9, 22, 12, 4, 59, tzinfo=timezone.utc)
    after = datetime(2026, 9, 22, 12, 5, 0, tzinfo=timezone.utc)
    first, expiry = current_code(station, before)
    second, later_expiry = current_code(station, after)
    assert len(first) == 7 and first.startswith("#F")
    assert first != second
    assert expiry == after
    assert later_expiry.minute == 10
    assert valid_code(station, first, before)
    assert not valid_code(station, first, after)
    assert valid_code(station, second.lower(), after)
