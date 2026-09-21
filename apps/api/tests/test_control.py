import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import ChargingSession, Command, Connector, Device, Profile, Reservation, now
from app.modules.charging.service import start
from app.modules.devices.service import sync
from app.modules.reservations.service import reserve
from app.schemas import ReserveInput, StartInput, SyncInput
from app.service import free


def measurement(sequence, **kwargs):
    return SyncInput(
        boot_id=kwargs.pop("boot_id", "boot-a"),
        sequence=sequence,
        firmware_version="test",
        physical_state=kwargs.pop("physical_state", "idle"),
        connected=kwargs.pop("connected", False),
        source="simulated",
        captured_at=now(),
        **kwargs,
    )


def do_sync(factory, seed, data):
    with factory.begin() as db:
        return sync(db, db.get(Device, seed["device"]), data)


def test_two_reservations_one_winner(factory, seed):
    barrier = Barrier(2)

    def attempt(uid):
        try:
            with factory.begin() as db:
                user = db.get(Profile, uid)
                barrier.wait()
                reserve(db, user, ReserveInput(connector_id=seed["point"]), str(uid))
            return True
        except HTTPException as error:
            assert error.status_code == 409
            return False

    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(attempt, [seed["a"], seed["b"]]))
    assert sum(results) == 1
    with factory() as db:
        assert len(db.scalars(select(Reservation)).all()) == 1
        assert len(db.scalars(select(Command)).all()) == 1


def test_reserve_start_race(factory, seed):
    barrier = Barrier(2)

    def attempt(kind):
        try:
            with factory.begin() as db:
                user = db.get(Profile, seed["a" if kind == "reserve" else "b"])
                barrier.wait()
                if kind == "reserve":
                    reserve(db, user, ReserveInput(connector_id=seed["point"]), "r")
                else:
                    start(db, user, StartInput(public_code="CG-01"), "s")
            return True
        except HTTPException:
            return False

    with ThreadPoolExecutor(2) as executor:
        assert sum(executor.map(attempt, ["reserve", "start"])) == 1


def test_idempotency_and_mismatch(factory, seed):
    with factory.begin() as db:
        user = db.get(Profile, seed["a"])
        first = reserve(db, user, ReserveInput(connector_id=seed["point"]), "same")
        second = reserve(db, user, ReserveInput(connector_id=seed["point"]), "same")
        assert first.id == second.id
    with factory.begin() as db:
        user = db.get(Profile, seed["a"])
        # Different body with an existing connector is checked before availability.
        with pytest.raises(HTTPException):
            start(db, user, StartInput(public_code="CG-01"), "different")


def test_late_ack_does_not_confirm_and_release_reissued(factory, seed):
    with factory.begin() as db:
        reservation = reserve(db, db.get(Profile, seed["a"]), ReserveInput(connector_id=seed["point"]), "r")
        reservation.confirmation_deadline = now() - timedelta(seconds=1)
        command = db.scalar(select(Command))
        command.expires_at = now() - timedelta(seconds=1)
        command_id = command.id
    result = do_sync(
        factory,
        seed,
        measurement(1, physical_state="reserved", acks=[{"command_id": command_id, "status": "applied"}]),
    )
    assert result["authorized"]["reservation"] is None
    assert result["commands"][0]["type"] == "RELEASE"
    release_id = result["commands"][0]["id"]
    with factory.begin() as db:
        db.get(Command, uuid.UUID(release_id)).expires_at = now() - timedelta(seconds=1)
    result = do_sync(factory, seed, measurement(2))
    assert result["commands"][0]["id"] != release_id
    do_sync(
        factory, seed, measurement(3, acks=[{"command_id": result["commands"][0]["id"], "status": "applied"}])
    )
    with factory() as db:
        assert free(db, db.get(Connector, seed["point"]))
        assert db.scalar(select(Reservation)).status == "expired"


def test_start_stop_energy_duplicate_reboot(factory, seed):
    do_sync(factory, seed, measurement(1))
    with factory.begin() as db:
        session = start(db, db.get(Profile, seed["a"]), StartInput(public_code="CG-01"), "s")
        sid = session.id
        start_id = db.scalar(select(Command)).id
    charging = measurement(
        2,
        physical_state="charging",
        connected=True,
        session_id=sid,
        energy_wh=10,
        soc_percent=30,
        acks=[{"command_id": start_id, "status": "applied"}],
    )
    do_sync(factory, seed, charging)
    do_sync(factory, seed, charging)
    with factory() as db:
        assert db.get(ChargingSession, sid).status == "charging"
        assert db.get(ChargingSession, sid).energy_wh == 10
    do_sync(
        factory,
        seed,
        measurement(
            0,
            boot_id="boot-b",
            session_id=sid,
            physical_state="stopped",
            energy_wh=12,
            end_reason="device_reboot",
        ),
    )
    with factory() as db:
        assert db.get(ChargingSession, sid).status == "interrupted"
        assert db.get(ChargingSession, sid).energy_wh == 12
    do_sync(
        factory,
        seed,
        measurement(
            99, boot_id="boot-a", session_id=sid, physical_state="charging", connected=True, energy_wh=99
        ),
    )
    with factory() as db:
        assert db.get(Device, seed["device"]).boot_id == "boot-b"
        assert db.get(ChargingSession, sid).energy_wh == 12


def test_device_cannot_ack_other_command(factory, seed):
    with factory.begin() as db:
        reserve(db, db.get(Profile, seed["a"]), ReserveInput(connector_id=seed["point"]), "r")
        command = db.scalar(select(Command))
        # Other-device check without violating FK: a second real device.
        other = Device(connector_id=seed["point"], key_hash="other", revoked=True)
        db.add(other)
        db.flush()
        command.device_id = other.id
        cid = command.id
    with pytest.raises(HTTPException) as error:
        do_sync(factory, seed, measurement(1, acks=[{"command_id": cid, "status": "applied"}]))
    assert error.value.status_code == 409


def test_start_timeout_stop_ack_without_session(factory, seed):
    with factory.begin() as db:
        session = start(db, db.get(Profile, seed["a"]), StartInput(public_code="CG-01"), "s")
        db.scalar(select(Command)).expires_at = now() - timedelta(seconds=1)
        sid = session.id
    result = do_sync(factory, seed, measurement(1))
    assert result["commands"][0]["type"] == "STOP"
    do_sync(
        factory, seed, measurement(2, acks=[{"command_id": result["commands"][0]["id"], "status": "applied"}])
    )
    with factory() as db:
        assert db.get(ChargingSession, sid).status == "failed"
        assert db.get(ChargingSession, sid).end_reason == "start_timeout"
        assert free(db, db.get(Connector, seed["point"]))


def test_offline_blocks_reservation(factory, seed):
    with factory.begin() as db:
        db.get(Device, seed["device"]).last_seen = now() - timedelta(seconds=46)
    with factory.begin() as db, pytest.raises(HTTPException):
        reserve(db, db.get(Profile, seed["a"]), ReserveInput(connector_id=seed["point"]), "r")


def test_finished_session_is_immutable_but_identical_replay_is_allowed(factory, seed):
    do_sync(factory, seed, measurement(1))
    with factory.begin() as db:
        session = start(db, db.get(Profile, seed["a"]), StartInput(public_code="CG-01"), "s")
        sid = session.id
        command_id = db.scalar(select(Command)).id
    do_sync(
        factory,
        seed,
        measurement(
            2,
            physical_state="charging",
            connected=True,
            session_id=sid,
            energy_wh=10,
            soc_percent=30,
            acks=[{"command_id": command_id, "status": "applied"}],
        ),
    )
    do_sync(
        factory,
        seed,
        measurement(3, session_id=sid, physical_state="stopped", energy_wh=12, soc_percent=31),
    )
    do_sync(
        factory,
        seed,
        measurement(4, session_id=sid, physical_state="stopped", energy_wh=12, soc_percent=31),
    )
    with pytest.raises(HTTPException) as error:
        do_sync(
            factory,
            seed,
            measurement(5, session_id=sid, physical_state="stopped", energy_wh=13, soc_percent=31),
        )
    assert error.value.status_code == 409
    with factory() as db:
        assert db.get(ChargingSession, sid).energy_wh == 12


def test_reboot_stop_without_repeated_end_reason_is_interrupted(factory, seed):
    do_sync(factory, seed, measurement(1))
    with factory.begin() as db:
        session = start(db, db.get(Profile, seed["a"]), StartInput(public_code="CG-01"), "s")
        sid = session.id
        command_id = db.scalar(select(Command)).id
    do_sync(
        factory,
        seed,
        measurement(
            2,
            physical_state="charging",
            connected=True,
            session_id=sid,
            energy_wh=10,
            acks=[{"command_id": command_id, "status": "applied"}],
        ),
    )
    reboot = do_sync(factory, seed, measurement(0, boot_id="boot-b"))
    command = reboot["commands"][0]
    assert command["type"] == "STOP"
    do_sync(
        factory,
        seed,
        measurement(
            1,
            boot_id="boot-b",
            acks=[{"command_id": command["id"], "status": "applied"}],
        ),
    )
    with factory() as db:
        session = db.get(ChargingSession, sid)
        assert session.status == "interrupted"
        assert session.end_reason == "device_reboot"
        assert session.energy_wh == 10


@pytest.mark.parametrize("change", ["revoke", "rotate"])
def test_sync_refreshes_authenticated_device_after_concurrent_credential_change(factory, seed, change):
    with factory() as request_db:
        # The dependency authenticated the key, but another transaction changed
        # the credential before this request acquired the connector lock.
        authenticated = request_db.get(Device, seed["device"])
        with factory.begin() as other_db:
            if change == "revoke":
                other_db.get(Device, seed["device"]).revoked = True
            else:
                other_db.get(Device, seed["device"]).key_hash = "rotated-key-hash"
        with pytest.raises(HTTPException) as error:
            sync(request_db, authenticated, measurement(1))
        assert error.value.status_code == 401


def test_sync_does_not_accept_older_sequence_after_concurrent_sync(factory, seed):
    do_sync(factory, seed, measurement(1))
    with factory.begin() as request_db:
        authenticated = request_db.get(Device, seed["device"])
        do_sync(factory, seed, measurement(5))
        sync(request_db, authenticated, measurement(4))
    with factory() as db:
        assert db.get(Device, seed["device"]).sequence == 5


def test_start_refreshes_control_version_loaded_before_connector_lock(factory, seed):
    with factory.begin() as request_db:
        stale_connector = request_db.get(Connector, seed["point"])
        assert stale_connector.control_version == 0
        with factory.begin() as other_db:
            other_db.get(Connector, seed["point"]).control_version = 2
        session = start(request_db, request_db.get(Profile, seed["a"]), StartInput(public_code="CG-01"), "s")
        command = request_db.scalar(select(Command).where(Command.session_id == session.id))
        assert command.version == 3
