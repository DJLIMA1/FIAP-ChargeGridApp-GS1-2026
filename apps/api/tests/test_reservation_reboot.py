from datetime import timedelta
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.http_helpers import point_row
from app.models import ChargingSession, Command, Connector, Device, Profile, Reservation, Station, now
from app.modules.charging.service import start
from app.modules.devices.service import sync
from app.modules.reservations.routes import cancel
from app.modules.reservations.service import reserve
from app.schemas import ReserveInput, StartInput, SyncInput
from app.service import free


def reading(sequence, boot="boot-a", state="idle", acks=None):
    return SyncInput(
        boot_id=boot,
        sequence=sequence,
        firmware_version="test",
        physical_state=state,
        connected=False,
        source="simulated",
        captured_at=now(),
        acks=acks or [],
    )


def report(factory, seed, data):
    with factory.begin() as db:
        return sync(db, db.get(Device, seed["device"]), data)


def booked(factory, seed):
    report(factory, seed, reading(1))
    with factory.begin() as db:
        reservation = reserve(
            db, db.get(Profile, seed["a"]), ReserveInput(connector_id=seed["point"]), "booking"
        )
        rid = reservation.id
        cmd = db.scalar(select(Command).where(Command.reservation_id == rid))
        cid = cmd.id
    report(factory, seed, reading(2, state="reserved", acks=[{"command_id": cid, "status": "applied"}]))
    with factory() as db:
        return rid, db.get(Reservation, rid).expires_at, cid


def test_reboot_restores_confirmed_reservation_without_renewal_and_can_start(factory, seed):
    rid, deadline, original_command = booked(factory, seed)
    reboot = report(factory, seed, reading(0, boot="boot-b"))
    restore = reboot["commands"][0]
    assert restore["type"] == "RESERVE"
    assert restore["version"] == 2
    assert restore["reservation_id"] == str(rid)
    assert restore["parameters"]["expires_at"] == deadline.isoformat()
    assert reboot["authorized"]["reservation"]["expires_at"] == deadline.isoformat()
    with factory.begin() as db:
        point = point_row(db, db.get(Connector, seed["point"]))
        assert point["availability_status"] == "reconciling"
        assert point["reserved_until"] == deadline
        assert point["available"] is False
        assert db.get(Reservation, rid).status == "confirmed"
        with pytest.raises(HTTPException):
            start(db, db.get(Profile, seed["b"]), StartInput(public_code="CG-01"), "blocked-other")
    repeated = report(factory, seed, reading(1, boot="boot-b"))
    assert repeated["commands"][0]["id"] == restore["id"]
    restored = report(
        factory,
        seed,
        reading(
            2, boot="boot-b", state="reserved", acks=[{"command_id": restore["id"], "status": "applied"}]
        ),
    )
    assert restored["commands"] == []
    with factory.begin() as db:
        assert db.get(Reservation, rid).expires_at == deadline
        assert point_row(db, db.get(Connector, seed["point"]))["availability_status"] == "reserved"
        assert db.get(Command, original_command).status == "applied"
        session = start(
            db, db.get(Profile, seed["a"]), StartInput(public_code="CG-01", reservation_id=rid), "start"
        )
        assert session.status == "starting"
        assert db.get(Reservation, rid).status == "consumed"
        assert point_row(db, db.get(Connector, seed["point"]))["availability_status"] == "reconciling"


def test_divergent_state_without_reboot_restores_existing_deadline(factory, seed):
    rid, deadline, _ = booked(factory, seed)
    result = report(factory, seed, reading(3))
    assert result["commands"][0]["type"] == "RESERVE"
    assert result["commands"][0]["parameters"]["expires_at"] == deadline.isoformat()
    with factory() as db:
        assert db.get(Reservation, rid).status == "confirmed"
        assert db.get(Device, seed["device"]).reconciled is False


def test_reboot_pending_reservation_preserves_confirmation_deadline(factory, seed):
    report(factory, seed, reading(1))
    with factory.begin() as db:
        reservation = reserve(db, db.get(Profile, seed["a"]), ReserveInput(connector_id=seed["point"]), "r")
        rid, deadline = reservation.id, reservation.confirmation_deadline
    result = report(factory, seed, reading(0, boot="boot-b"))
    assert result["commands"][0]["type"] == "RESERVE"
    with factory() as db:
        assert db.get(Reservation, rid).status == "pending_device"
        assert db.get(Reservation, rid).confirmation_deadline == deadline


def test_expired_restore_command_reissues_but_late_ack_cannot_confirm(factory, seed):
    rid, deadline, _ = booked(factory, seed)
    old = report(factory, seed, reading(0, boot="boot-b"))["commands"][0]
    with factory.begin() as db:
        db.get(Command, UUID(old["id"])).expires_at = now() - timedelta(seconds=1)
    response = report(
        factory,
        seed,
        reading(1, boot="boot-b", state="reserved", acks=[{"command_id": old["id"], "status": "applied"}]),
    )
    new = response["commands"][0]
    assert new["id"] != old["id"] and new["version"] > old["version"]
    assert new["parameters"]["expires_at"] == deadline.isoformat()
    with factory() as db:
        assert db.get(Device, seed["device"]).reconciled is False
        assert db.get(Reservation, rid).expires_at == deadline


def test_failed_restoration_keeps_booking_and_retries_until_deadline(factory, seed):
    rid, deadline, _ = booked(factory, seed)
    old = report(factory, seed, reading(0, boot="boot-b"))["commands"][0]
    result = report(
        factory,
        seed,
        reading(1, boot="boot-b", acks=[{"command_id": old["id"], "status": "failed", "error": "temporary"}]),
    )
    assert result["commands"][0]["type"] == "RESERVE"
    assert result["commands"][0]["id"] != old["id"]
    with factory() as db:
        assert db.get(Reservation, rid).status == "confirmed"
        assert db.get(Reservation, rid).expires_at == deadline


def test_cancel_supersedes_restore_and_late_restore_ack_cannot_resurrect(factory, seed):
    rid, _, _ = booked(factory, seed)
    restore = report(factory, seed, reading(0, boot="boot-b"))["commands"][0]
    with factory.begin() as db:
        cancel(rid, db.get(Profile, seed["a"]), db)
    cancelled = report(
        factory,
        seed,
        reading(
            1, boot="boot-b", state="reserved", acks=[{"command_id": restore["id"], "status": "applied"}]
        ),
    )
    release = cancelled["commands"][0]
    assert release["type"] == "RELEASE"
    assert cancelled["authorized"]["reservation"] is None
    report(
        factory, seed, reading(2, boot="boot-b", acks=[{"command_id": release["id"], "status": "applied"}])
    )
    with factory() as db:
        assert db.get(Reservation, rid).status == "cancelled"
        assert free(db, db.get(Connector, seed["point"]))


def test_replay_neither_restores_again_nor_refreshes_presence_and_expiry_wins(factory, seed):
    rid, _, _ = booked(factory, seed)
    reboot_data = reading(0, boot="boot-b")
    result = report(factory, seed, reboot_data)
    with factory() as db:
        last_seen = db.get(Device, seed["device"]).last_seen
    duplicate = report(factory, seed, reboot_data)
    prior_boot = report(factory, seed, reading(99, boot="boot-a"))
    assert duplicate["commands"] == result["commands"] == prior_boot["commands"]
    with factory.begin() as db:
        assert db.get(Device, seed["device"]).last_seen == last_seen
        db.get(Reservation, rid).expires_at = now() - timedelta(seconds=1)
    expired = report(factory, seed, reboot_data)
    assert expired["authorized"]["reservation"] is None
    release = expired["commands"][0]
    assert release["type"] == "RELEASE" and release["parameters"]["reason"] == "expired"
    report(
        factory, seed, reading(1, boot="boot-b", acks=[{"command_id": release["id"], "status": "applied"}])
    )
    with factory() as db:
        assert db.get(Reservation, rid).status == "expired"
        assert point_row(db, db.get(Connector, seed["point"]))["availability_status"] == "available"


@pytest.mark.parametrize(
    "state,expected",
    [
        ("normal", "available"),
        ("offline", "offline"),
        ("missing", "offline"),
        ("fault", "fault"),
        ("connected", "occupied"),
        ("unreconciled", "reconciling"),
        ("station_disabled", "disabled"),
        ("connector_disabled", "disabled"),
        ("unowned", "disabled"),
        ("charging", "charging"),
        ("stopping", "reconciling"),
    ],
)
def test_availability_enum_is_safe_and_factory_is_never_available(factory, seed, state, expected):
    with factory.begin() as db:
        point, device = db.get(Connector, seed["point"]), db.get(Device, seed["device"])
        station = db.get(Station, seed["station"])
        if state == "offline":
            device.last_seen = now() - timedelta(seconds=46)
        elif state == "missing":
            device.revoked = True
        elif state == "fault":
            device.physical_state = "fault"
        elif state == "connected":
            device.connected = True
        elif state == "unreconciled":
            device.reconciled = False
        elif state == "station_disabled":
            station.active = False
        elif state == "connector_disabled":
            point.active = False
        elif state == "unowned":
            station.owner_id = None
        elif state in ("charging", "stopping"):
            db.add(
                ChargingSession(
                    user_id=seed["a"],
                    connector_id=point.id,
                    status=state,
                    max_duration_minutes=30,
                    price_per_kwh=1,
                    started_at=now(),
                )
            )
            device.physical_state = "charging"
        result = point_row(db, point)
        assert result["availability_status"] == expected
        assert result["available"] is (expected == "available")
        assert result["reserved_until"] is None
        assert "user_id" not in result
        if state == "unowned":
            assert free(db, point) is False
            response = sync(db, device, reading(1))
            assert response["connector"]["owned"] is False
            assert response["connector"]["active"] is True


def test_offline_reservation_exposes_only_deadline_not_customer(factory, seed):
    rid, deadline, _ = booked(factory, seed)
    with factory.begin() as db:
        db.get(Device, seed["device"]).last_seen = now() - timedelta(seconds=46)
        result = point_row(db, db.get(Connector, seed["point"]))
        assert result["availability_status"] == "offline"
        assert result["reserved_until"] == deadline
        assert "user_id" not in result and "reservation_id" not in result
        assert str(rid) not in str(result)
