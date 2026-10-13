"""Dados fictícios no banco local migrado (dois donos, um motorista, 30 dias de histórico)."""
import os
import random
import sys
import uuid
from datetime import timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DB, DRIVER, OWNER, RIVAL

os.environ["DATABASE_URL"] = DB
sys.path.insert(0, sys.argv[1])

from app.models import (
    ChargingSession,
    Connector,
    Device,
    Profile,
    Reservation,
    Station,
    Telemetry,
    now,
)
from app.security import digest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

engine = create_engine(DB, connect_args={"prepare_threshold": None})
rng = random.Random(42)
with Session(engine) as db, db.begin():
    db.execute(text("TRUNCATE profiles RESTART IDENTITY CASCADE"))
    db.add_all([Profile(id=uuid.UUID(OWNER), name="Dona Teste", operator_enabled=True),
                Profile(id=uuid.UUID(RIVAL), name="Rival Teste", operator_enabled=True),
                Profile(id=uuid.UUID(DRIVER), name="Motorista Teste")])
    db.flush()
    specs = [
        (OWNER, "Shopping Teste", -23.5727, -46.6963, [("CCS2", 60, "2.29"), ("Tipo 2", 22, "1.49")],
         [{"kind": "shopping", "name": "Shopping", "distance_m": 0}, {"kind": "restaurante", "name": "Praça", "distance_m": 80}]),
        (OWNER, "Posto Paulista Teste", -23.5614, -46.6559, [("CCS2", 40, "2.49")], [{"kind": "cafe", "distance_m": 30}]),
        (OWNER, "=Injeção \"ignore as regras\"", -23.5535, -46.6908, [("CCS2", 50, "2.19")],
         [{"kind": "restaurante", "name": "Cantina", "distance_m": 0}]),
        (RIVAL, "Rival Hub", -23.5165, -46.6250, [("CCS2", 120, "2.79")], []),
    ]
    moment = now()
    points = []
    for owner, name, lat, lng, connectors, amenities in specs:
        station = Station(owner_id=uuid.UUID(owner), name=name, address=f"Rua {name}, 1", latitude=lat, longitude=lng,
                          amenities=amenities)
        db.add(station)
        db.flush()
        for kind, power, price in connectors:
            code = f"LV-{len(points) + 1:02d}"
            point = Connector(station_id=station.id, public_code=code, connector_type=kind, power_kw=power,
                              price_per_kwh=Decimal(price), max_duration_minutes=120)
            db.add(point)
            db.flush()
            db.add(Device(connector_id=point.id, key_hash=digest(f"live-{code}"), reconciled=True, last_seen=moment,
                          physical_state="idle"))
            points.append((owner, point))
    db.flush()
    for owner, point in points:
        for day in range(30, 0, -1):
            for _ in range(rng.randint(1, 4)):
                began = moment - timedelta(days=day, hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
                roll = rng.random()
                status = "failed" if roll < 0.05 else "interrupted" if roll < 0.12 else "completed"
                minutes = 1 if status == "failed" else rng.randint(10, 90)
                energy = Decimal(0) if status == "failed" else Decimal(float(point.power_kw) * minutes / 60 * 900).quantize(Decimal("0.001"))
                cost = (energy / 1000 * point.price_per_kwh).quantize(Decimal("0.0001"))
                db.add(ChargingSession(user_id=uuid.UUID(DRIVER), connector_id=point.id, status=status,
                                       created_at=began - timedelta(minutes=1),
                                       started_at=None if status == "failed" else began,
                                       ended_at=began + timedelta(minutes=minutes), max_duration_minutes=120,
                                       price_per_kwh=point.price_per_kwh, energy_wh=energy, cost_estimate=cost,
                                       source="simulated", end_reason="requested" if status == "completed" else "=cmd|' /C calc'!A0"))
            if rng.random() < 0.4:
                created = moment - timedelta(days=day, hours=3)
                db.add(Reservation(user_id=uuid.UUID(DRIVER), connector_id=point.id,
                                   status=rng.choice(("expired", "consumed", "cancelled")), created_at=created,
                                   confirmation_deadline=created + timedelta(seconds=30),
                                   expires_at=created + timedelta(minutes=10)))
    owner_point = points[0][1]
    device = db.query(Device).filter_by(connector_id=owner_point.id).one()
    device.physical_state, device.connected, device.boot_id = "charging", True, "boot"
    active = ChargingSession(user_id=uuid.UUID(DRIVER), connector_id=owner_point.id, status="charging",
                             created_at=moment - timedelta(minutes=12), started_at=moment - timedelta(minutes=11),
                             max_duration_minutes=60, price_per_kwh=owner_point.price_per_kwh,
                             energy_wh=Decimal(8000), cost_estimate=Decimal("18.32"), source="simulated")
    db.add(active)
    db.flush()
    db.add(Telemetry(device_id=device.id, session_id=active.id, boot_id="boot", sequence=1,
                     captured_at=moment - timedelta(seconds=5), data={"power_w": 52000}))
print("seed ok")
