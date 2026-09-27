from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from app.models import ChargingSession, Command, Connector, Device, Profile, Station
from app.modules.charging.service import start
from app.presence_code import current_code
from app.schemas import StartInput


@pytest.mark.parametrize("disable_point", [False, True])
def test_code_only_retry_survives_expiry_and_disabled_point(factory, seed, monkeypatch, disable_point):
    instant = datetime(2026, 9, 25, 12, 4, 59, tzinfo=timezone.utc)
    monkeypatch.setattr("app.presence_code.now", lambda: instant)
    monkeypatch.setattr("app.modules.charging.service.now", lambda: instant)
    with factory.begin() as db:
        code = current_code(db.get(Station, seed["station"]))[0]
        body = StartInput(presence_code=code)
        first = start(db, db.get(Profile, seed["a"]), body, "lost-response")
        session_id = first.id
        db.get(Connector, seed["point"]).active = not disable_point
    instant += timedelta(seconds=2)
    with factory.begin() as db:
        retry = start(db, db.get(Profile, seed["a"]), body, "lost-response")
        assert retry.id == session_id
        assert len(db.scalars(select(ChargingSession)).all()) == 1
        assert len(db.scalars(select(Command)).all()) == 1
    with factory.begin() as db, pytest.raises(HTTPException) as rejected:
        start(db, db.get(Profile, seed["a"]), body, "new-request")
    assert rejected.value.detail["code"] == "invalid_presence_code"


def test_code_only_retry_still_rejects_changed_body(factory, seed):
    with factory.begin() as db:
        body = StartInput(presence_code=current_code(db.get(Station, seed["station"]))[0])
        start(db, db.get(Profile, seed["a"]), body, "same-key")
    with factory.begin() as db, pytest.raises(HTTPException) as rejected:
        start(db, db.get(Profile, seed["a"]), body.model_copy(update={"max_duration_minutes": 20}), "same-key")
    assert rejected.value.detail["code"] == "idempotency_conflict"


def test_concurrent_code_only_retries_create_one_session(factory, seed):
    with factory() as db:
        body = StartInput(presence_code=current_code(db.get(Station, seed["station"]))[0])
    barrier = Barrier(2)

    def attempt(_):
        with factory.begin() as db:
            user = db.get(Profile, seed["a"])
            barrier.wait(timeout=5)
            return start(db, user, body, "same-intent").id

    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(attempt, range(2)))
    assert results[0] == results[1]
    with factory() as db:
        assert len(db.scalars(select(ChargingSession)).all()) == 1
        assert len(db.scalars(select(Command)).all()) == 1


def test_colliding_station_codes_never_select_a_different_free_station(factory, seed, monkeypatch):
    with factory.begin() as db:
        other = Station(owner_id=seed["owner"], name="Outro posto", address="Outra rua", latitude=1, longitude=1)
        db.add(other)
        db.flush()
        db.add(Connector(station_id=other.id, public_code="CG-OTHER", connector_type="bench",
                         power_kw=1, price_per_kwh=2))
    # The other station is offline: availability must not resolve a collision
    # between two locations and silently start the user's session elsewhere.
    monkeypatch.setattr("app.modules.charging.service.valid_code", lambda *args, **kwargs: True)
    with factory.begin() as db, pytest.raises(HTTPException) as rejected:
        start(db, db.get(Profile, seed["a"]), StartInput(presence_code="#F12345"), "collision")
    assert rejected.value.detail["code"] == "ambiguous_presence_code"
    with factory.begin() as db:
        session = start(db, db.get(Profile, seed["a"]),
                        StartInput(public_code="CG-01", presence_code="#F12345"), "selected-point")
        assert session.connector_id == seed["point"]


def test_retry_is_not_redirected_to_other_connector_in_same_station(factory, seed):
    with factory.begin() as db:
        extra = Connector(station_id=seed["station"], public_code="CG-02", connector_type="bench",
                          power_kw=1, price_per_kwh=2)
        db.add(extra)
        db.flush()
        # No device on the extra connector, so the first request resolves CG-01.
        body = StartInput(presence_code=current_code(db.get(Station, seed["station"]))[0])
        session_id = start(db, db.get(Profile, seed["a"]), body, "retry").id
    with factory.begin() as db:
        assert start(db, db.get(Profile, seed["a"]), body, "retry").id == session_id
        assert db.get(Device, seed["device"]).reconciled is False


def test_raw_station_inserts_generate_distinct_private_seeds(factory, seed):
    # Factory provisioning and legacy imports use SQL, bypassing ORM defaults.
    with factory.begin() as db:
        original = db.get(Station, seed["station"]).presence_secret
        secrets = [db.execute(text(
            "INSERT INTO stations (id, owner_id, name, address, latitude, longitude, active) "
            "VALUES (gen_random_uuid(), NULL, 'Factory', 'Setup', 0, 0, FALSE) RETURNING presence_secret"
        )).scalar_one() for _ in range(2)]
        assert len(set(secrets + [original])) == 3
        assert all(len(bytes.fromhex(value)) == 32 for value in secrets)
        assert db.get(Station, seed["station"]).presence_secret == original
