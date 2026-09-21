import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def now():
    return datetime.now(UTC)


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    account_type: Mapped[str] = mapped_column(String(20), default="consumer", server_default="consumer")
    phone: Mapped[str | None] = mapped_column(String(30))
    vehicle_description: Mapped[str | None] = mapped_column(String(200))
    operator_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint("account_type IN ('consumer', 'vendor')", name="profile_account_type"),)


class Station(Base):
    __tablename__ = "stations"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    address: Mapped[str] = mapped_column(String(300))
    latitude: Mapped[float] = mapped_column(Numeric(10, 7))
    longitude: Mapped[float] = mapped_column(Numeric(10, 7))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180"),)


class Connector(Base):
    __tablename__ = "connectors"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    station_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stations.id"), index=True)
    public_code: Mapped[str] = mapped_column(String(50), unique=True)
    connector_type: Mapped[str] = mapped_column(String(50))
    power_kw: Mapped[float] = mapped_column(Numeric(10, 3))
    price_per_kwh: Mapped[float] = mapped_column(Numeric(10, 4))
    max_duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    control_version: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (CheckConstraint("power_kw > 0 AND price_per_kwh >= 0 AND max_duration_minutes > 0"),)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    connector_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connectors.id"), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    firmware_version: Mapped[str | None] = mapped_column(String(50))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    boot_id: Mapped[str | None] = mapped_column(String(100))
    sequence: Mapped[int] = mapped_column(Integer, default=-1)
    physical_state: Mapped[str] = mapped_column(String(20), default="unknown")
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    reconciled: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        Index("one_active_device", "connector_id", unique=True, postgresql_where=text("NOT revoked")),
    )


class Reservation(Base):
    __tablename__ = "reservations"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"), index=True)
    connector_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connectors.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending_device")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    confirmation_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = tuple(
        Index(
            f"one_reservation_{field}",
            field,
            unique=True,
            postgresql_where=text("status IN ('pending_device','confirmed','cancelling')"),
        )
        for field in ("user_id", "connector_id")
    )


class ChargingSession(Base):
    __tablename__ = "charging_sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"), index=True)
    connector_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connectors.id"), index=True)
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reservations.id"))
    status: Mapped[str] = mapped_column(String(20), default="starting")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, server_default=text("now()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_duration_minutes: Mapped[int] = mapped_column(Integer)
    max_cost: Mapped[float | None] = mapped_column(Numeric(12, 4))
    price_per_kwh: Mapped[float] = mapped_column(Numeric(10, 4))
    discount_percent: Mapped[int] = mapped_column(Integer, default=0)
    energy_wh: Mapped[float] = mapped_column(Numeric(16, 3), default=0)
    soc_percent: Mapped[float | None] = mapped_column(Numeric(5, 2))
    source: Mapped[str | None] = mapped_column(String(20))
    last_measurement_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cost_estimate: Mapped[float] = mapped_column(Numeric(12, 4), default=0)
    end_reason: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (
        CheckConstraint(
            "energy_wh >= 0 AND (soc_percent IS NULL OR soc_percent BETWEEN 0 AND 100) AND discount_percent BETWEEN 0 AND 100"
        ),
        *tuple(
            Index(
                f"one_session_{field}",
                field,
                unique=True,
                postgresql_where=text("status IN ('starting','charging','stopping')"),
            )
            for field in ("user_id", "connector_id")
        ),
    )


class Command(Base):
    __tablename__ = "device_commands"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), index=True)
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reservations.id"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("charging_sessions.id"))
    type: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer)
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error: Mapped[str | None] = mapped_column(String(200))
    __table_args__ = (UniqueConstraint("device_id", "version"),)


class Telemetry(Base):
    __tablename__ = "telemetry_samples"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("charging_sessions.id"))
    boot_id: Mapped[str] = mapped_column(String(100))
    sequence: Mapped[int] = mapped_column(Integer)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    data: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("device_id", "boot_id", "sequence"),)


class Coupon(Base):
    __tablename__ = "coupons"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"))
    station_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stations.id"))
    code: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str] = mapped_column(String(200))
    discount_percent: Mapped[int] = mapped_column(Integer)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("discount_percent BETWEEN 0 AND 100"),)


class Idempotency(Base):
    __tablename__ = "idempotency_requests"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"), primary_key=True)
    operation: Mapped[str] = mapped_column(String(100), primary_key=True)
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    body_hash: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID)


class RequestLimit(Base):
    __tablename__ = "request_limits"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    window: Mapped[int] = mapped_column(Integer, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DeviceBoot(Base):
    __tablename__ = "device_boots"
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    boot_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
