import os
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.database import Base
from app.models import Connector, Device, Profile, Station, now
from app.security import digest


@pytest.fixture(scope="session")
def engine():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL PostgreSQL obrigatório")
    if "test" not in url.rsplit("/", 1)[-1]:
        pytest.fail("Banco descartável deve ter test no nome")
    if not url.startswith("postgresql"):
        pytest.fail("Testes críticos exigem PostgreSQL")
    engine = create_engine(url, poolclass=NullPool, connect_args={"prepare_threshold": None})
    yield engine
    engine.dispose()


@pytest.fixture
def factory(engine):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def seed(factory):
    with factory.begin() as db:
        owner = Profile(id=uuid.uuid4(), name="Operator", operator_enabled=True)
        a = Profile(id=uuid.uuid4(), name="A")
        b = Profile(id=uuid.uuid4(), name="B")
        db.add_all([owner, a, b])
        db.flush()
        station = Station(owner_id=owner.id, name="Demo", address="Bancada", latitude=0, longitude=0)
        db.add(station)
        db.flush()
        connector = Connector(
            station_id=station.id,
            public_code="CG-01",
            connector_type="bench",
            power_kw=1,
            price_per_kwh=2,
            max_duration_minutes=60,
        )
        db.add(connector)
        db.flush()
        device = Device(
            connector_id=connector.id,
            key_hash=digest("test-key"),
            last_seen=now(),
            reconciled=True,
            physical_state="idle",
        )
        db.add(device)
        db.flush()
        return {
            "owner": owner.id,
            "a": a.id,
            "b": b.id,
            "station": station.id,
            "point": connector.id,
            "device": device.id,
        }
