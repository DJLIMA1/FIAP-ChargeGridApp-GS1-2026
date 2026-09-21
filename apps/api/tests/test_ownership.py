import secrets
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import db_session
from app.main import app
from app.models import Connector, Device, DeviceClaim, Profile, Station
from app.modules.ownership.routes import claim_point
from app.schemas import ClaimInput
from app.security import current_user, digest


@pytest.fixture
def equipment(factory, seed):
    token = secrets.token_urlsafe(32)
    with factory.begin() as db:
        vendor = db.get(Profile, seed["b"])
        vendor.account_type = "vendor"
        station = Station(
            owner_id=None, name="Fábrica", address="Configurar", latitude=0, longitude=0, active=False
        )
        db.add(station)
        db.flush()
        point = Connector(
            station_id=station.id,
            public_code="FACTORY-01",
            connector_type="Tipo 2",
            power_kw=7.4,
            price_per_kwh=0,
            active=False,
        )
        db.add(point)
        db.flush()
        db.add(Device(connector_id=point.id, key_hash=digest("independent-device-secret")))
        db.add(DeviceClaim(connector_id=point.id, token_hash=digest(token)))
        return {**seed, "factory_station": station.id, "factory_point": point.id, "token": token}


def run_claim(factory, user_id, token, station_id=None):
    with factory.begin() as db:
        return claim_point(db, user_id, ClaimInput(token=token, station_id=station_id))


def test_vendor_claim_enables_management_but_never_publishes(factory, equipment):
    e = equipment
    result = run_claim(factory, e["b"], e["token"])
    assert result["station_id"] == str(e["factory_station"])
    assert result["connector_id"] == str(e["factory_point"])
    assert result["already_claimed"] is False
    assert set(result) == {"station_id", "connector_id", "already_claimed", "message"}
    with factory() as db:
        assert db.get(Profile, e["b"]).operator_enabled is True
        assert db.get(Station, e["factory_station"]).owner_id == e["b"]
        assert db.get(Station, e["factory_station"]).active is False
        assert db.get(Connector, e["factory_point"]).active is False
        claim = db.get(DeviceClaim, e["factory_point"])
        assert claim.claimed_by == e["b"] and claim.claimed_at is not None
        assert claim.token_hash == digest(e["token"])
        assert db.get(Station, e["station"]).owner_id == e["owner"]


def test_consumer_cannot_claim_and_token_remains_usable(factory, equipment):
    e = equipment
    with pytest.raises(HTTPException) as error:
        run_claim(factory, e["a"], e["token"])
    assert error.value.status_code == 403
    assert run_claim(factory, e["b"], e["token"])["already_claimed"] is False


def test_legacy_operator_can_claim(factory, equipment):
    assert run_claim(factory, equipment["owner"], equipment["token"])["already_claimed"] is False


def test_replay_is_idempotent_and_second_owner_is_rejected(factory, equipment):
    e = equipment
    first = run_claim(factory, e["b"], e["token"])
    replay = run_claim(factory, e["b"], e["token"])
    assert replay["already_claimed"] is True
    assert replay["station_id"] == first["station_id"]
    with pytest.raises(HTTPException) as error:
        run_claim(factory, e["owner"], e["token"])
    assert error.value.status_code == 409
    with factory() as db:
        assert db.get(Station, e["factory_station"]).owner_id == e["b"]


def test_claim_into_owned_group_preserves_other_points(factory, equipment):
    e = equipment
    result = run_claim(factory, e["owner"], e["token"], e["station"])
    assert result["station_id"] == str(e["station"])
    with factory() as db:
        assert db.get(Station, e["factory_station"]).owner_id is None
        assert db.get(Connector, e["point"]).station_id == e["station"]
        assert db.get(Connector, e["factory_point"]).station_id == e["station"]
        assert db.get(Connector, e["factory_point"]).active is False
    assert run_claim(factory, e["owner"], e["token"], e["station"])["already_claimed"] is True
    with pytest.raises(HTTPException) as error:
        run_claim(factory, e["owner"], e["token"], e["factory_station"])
    assert error.value.status_code == 409


def test_cannot_claim_into_someone_elses_group(factory, equipment):
    e = equipment
    with pytest.raises(HTTPException) as error:
        run_claim(factory, e["b"], e["token"], e["station"])
    assert error.value.status_code == 404
    with factory() as db:
        assert db.get(DeviceClaim, e["factory_point"]).claimed_by is None
        assert db.get(Profile, e["b"]).operator_enabled is False


def test_existing_owner_never_overwritten_even_with_unused_claim(factory, equipment):
    e = equipment
    with factory.begin() as db:
        db.get(Station, e["factory_station"]).owner_id = e["owner"]
    with pytest.raises(HTTPException) as error:
        run_claim(factory, e["b"], e["token"])
    assert error.value.status_code == 409


@pytest.mark.parametrize("same_user", [False, True])
def test_concurrent_claims_serialize_without_duplicate_ownership(factory, equipment, same_user):
    e = equipment
    barrier = Barrier(2)

    def attempt(user_id):
        barrier.wait(timeout=5)
        try:
            return (user_id, run_claim(factory, user_id, e["token"]))
        except HTTPException as error:
            return (user_id, error.status_code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [e["b"], e["b"] if same_user else e["owner"]]))
    if same_user:
        assert sorted(result["already_claimed"] for _, result in results) == [False, True]
    else:
        assert sum(result == 409 for _, result in results) == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(DeviceClaim)) == 1
        claim = db.get(DeviceClaim, e["factory_point"])
        assert claim.claimed_by == db.get(Station, e["factory_station"]).owner_id


def test_unknown_token_does_not_reveal_equipment(factory, equipment):
    with pytest.raises(HTTPException) as error:
        run_claim(factory, equipment["b"], secrets.token_urlsafe(32))
    assert error.value.status_code == 404
    assert str(equipment["factory_point"]) not in str(error.value.detail)


def test_http_claim_contract_no_secrets_and_no_manual_connector_creation(factory, equipment):
    e = equipment

    def database():
        with factory() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    def user():
        with factory() as db:
            return db.get(Profile, e["b"])

    app.dependency_overrides[db_session] = database
    app.dependency_overrides[current_user] = user
    try:
        with TestClient(app) as client:
            invalid = client.post("/v1/ownership/claim", json={"token": "CG-01"})
            assert invalid.status_code == 422
            response = client.post("/v1/ownership/claim", json={"token": e["token"]})
            assert response.status_code == 200
            assert e["token"] not in response.text and "token_hash" not in response.text
            stations = client.get("/v1/operator/stations")
            assert stations.status_code == 200
            assert "token_hash" not in stations.text and e["token"] not in stations.text
            refused = client.post(
                f"/v1/stations/{e['factory_station']}/connectors",
                json={
                    "public_code": "manual",
                    "connector_type": "Tipo 2",
                    "power_kw": 7.4,
                    "price_per_kwh": 0,
                },
            )
            assert refused.status_code == 409
            assert refused.json()["error"]["code"] == "claim_required"
            # Rejected attempts must consume the persistent rate budget, too.
            unknown = secrets.token_urlsafe(32)
            for _ in range(14):
                rejected = client.post("/v1/ownership/claim", json={"token": unknown})
                assert rejected.status_code == 404
                assert unknown not in rejected.text
            limited = client.post("/v1/ownership/claim", json={"token": e["token"]})
            assert limited.status_code == 429
            assert limited.json()["error"]["code"] == "rate_limited"
    finally:
        app.dependency_overrides.clear()


def test_vendor_first_setup_is_a_draft_until_both_publish_steps_succeed(factory, equipment):
    e = equipment

    def database():
        with factory() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    def user():
        with factory() as db:
            return db.get(Profile, e['b'])

    app.dependency_overrides[db_session] = database
    app.dependency_overrides[current_user] = user
    try:
        with TestClient(app) as client:
            claim = client.post('/v1/ownership/claim', json={'token': e['token']})
            assert claim.status_code == 200
            station_id, point_id = claim.json()['station_id'], claim.json()['connector_id']
            location = client.patch(f'/v1/stations/{station_id}', json={
                'name': 'Estação Centro', 'address': 'Rua das Flores, 50, São Paulo',
                'latitude': -23.55, 'longitude': -46.63,
            })
            assert location.status_code == 200
            assert location.json()['active'] is False
            tariff = client.patch(f'/v1/connectors/{point_id}', json={
                'connector_type': 'Tipo 2', 'power_kw': 7.4,
                'price_per_kwh': 1.8, 'max_duration_minutes': 60,
            })
            assert tariff.status_code == 200
            assert tariff.json()['active'] is False
            assert all(item['id'] != station_id for item in client.get('/v1/stations').json()['items'])
            assert client.patch(f'/v1/connectors/{point_id}', json={'active': True}).status_code == 200
            # A partial publish still does not list the station publicly.
            assert all(item['id'] != station_id for item in client.get('/v1/stations').json()['items'])
            published = client.patch(f'/v1/stations/{station_id}', json={'active': True})
            assert published.status_code == 200
            assert published.json()['name'] == 'Estação Centro'
            assert any(item['id'] == station_id for item in client.get('/v1/stations').json()['items'])
    finally:
        app.dependency_overrides.clear()
