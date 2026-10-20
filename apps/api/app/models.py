import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
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
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("profiles.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    address: Mapped[str] = mapped_column(String(300))
    latitude: Mapped[float] = mapped_column(Numeric(10, 7))
    longitude: Mapped[float] = mapped_column(Numeric(10, 7))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    presence_secret: Mapped[str] = mapped_column(
        String(64), default=lambda: secrets.token_hex(32),
        server_default=text("replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', '')"),
    )
    # Comodidades públicas do posto (restaurante, café...): [{"kind", "name", "distance_m"}].
    amenities: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    # Limites de potência (migração c3a9e5f1d204): teto compartilhado pelos conectores
    # ativos e aviso ao vendedor quando uma recarga roda limitada (chargegrid_core.power).
    max_power_kw: Mapped[float | None] = mapped_column(Numeric(10, 3))
    power_limit_notify: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Tarifa dinâmica (migração a7c2e9d4b6f1): dados base do dono; o cálculo é chargegrid_core.pricing.
    pricing: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180"),
        CheckConstraint("max_power_kw IS NULL OR max_power_kw > 0", name="station_max_power_positive"),
    )


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
    # Limite do vendedor para este conector; ``power_kw`` continua sendo a nominal.
    power_limit_kw: Mapped[float | None] = mapped_column(Numeric(10, 3))
    __table_args__ = (
        CheckConstraint("power_kw > 0 AND price_per_kwh >= 0 AND max_duration_minutes > 0"),
        CheckConstraint(
            "power_limit_kw IS NULL OR (power_limit_kw > 0 AND power_limit_kw <= power_kw)",
            name="connector_power_limit_range",
        ),
    )


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


class DeviceClaim(Base):
    __tablename__ = "device_claims"
    connector_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connectors.id"), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    claimed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("profiles.id"))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        CheckConstraint("(claimed_by IS NULL) = (claimed_at IS NULL)", name="claim_audit_complete"),
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
    # Multiplicador da tarifa dinâmica travado ao reservar (vale para a recarga desta reserva).
    demand_multiplier: Mapped[float | None] = mapped_column(Numeric(4, 2))
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
    # Tarifa dinâmica: price_per_kwh = base_price_per_kwh × demand_multiplier (travado no início).
    base_price_per_kwh: Mapped[float | None] = mapped_column(Numeric(10, 4))
    demand_multiplier: Mapped[float] = mapped_column(Numeric(4, 2), default=1, server_default=text("1"))
    discount_percent: Mapped[int] = mapped_column(Integer, default=0)
    energy_wh: Mapped[float] = mapped_column(Numeric(16, 3), default=0)
    soc_percent: Mapped[float | None] = mapped_column(Numeric(5, 2))
    source: Mapped[str | None] = mapped_column(String(20))
    # Car battery (migration f2b7d4c8a1e6): initial SoC, usable capacity and who
    # drives the current SoC ("simulated" = derived from energy, "phone" = app).
    start_soc_percent: Mapped[float | None] = mapped_column(Numeric(5, 2))
    battery_kwh: Mapped[float | None] = mapped_column(Numeric(6, 2))
    soc_source: Mapped[str | None] = mapped_column(String(20))
    # Potência máxima aplicada no início (efetivo do conector ∩ limite do motorista).
    power_limit_kw: Mapped[float | None] = mapped_column(Numeric(10, 3))
    last_measurement_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cost_estimate: Mapped[float] = mapped_column(Numeric(12, 4), default=0)
    end_reason: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (
        CheckConstraint(
            "energy_wh >= 0 AND (soc_percent IS NULL OR soc_percent BETWEEN 0 AND 100) AND discount_percent BETWEEN 0 AND 100"
        ),
        CheckConstraint(
            "start_soc_percent IS NULL OR start_soc_percent BETWEEN 0 AND 100", name="session_start_soc_range"
        ),
        CheckConstraint("battery_kwh IS NULL OR battery_kwh BETWEEN 5 AND 250", name="session_battery_kwh_range"),
        CheckConstraint("soc_source IS NULL OR soc_source IN ('simulated', 'phone')", name="session_soc_source"),
        CheckConstraint("power_limit_kw IS NULL OR power_limit_kw > 0", name="session_power_limit_positive"),
        CheckConstraint("demand_multiplier BETWEEN 1 AND 2", name="session_demand_multiplier_range"),
        Index("ix_charging_sessions_user_created", "user_id", "created_at"),
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


class SessionEvent(Base):
    """Server-observed facts; keys prevent retries from duplicating a fact."""

    __tablename__ = "session_events"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("charging_sessions.id"), index=True)
    event_key: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(30))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("session_id", "event_key"),)


class Command(Base):
    __tablename__ = "device_commands"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), index=True)
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reservations.id"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("charging_sessions.id"), index=True)
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
    __table_args__ = (
        UniqueConstraint("device_id", "boot_id", "sequence"),
        # Every device sync reads its latest sample; without this it scans the table.
        Index("ix_telemetry_device_received", "device_id", "received_at"),
    )


class Coupon(Base):
    __tablename__ = "coupons"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"), index=True)
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


class DriverProfile(Base):
    """Veículo e preferências do Modo Motorista (validados por chargegrid_core.driver)."""

    __tablename__ = "driver_profiles"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"), primary_key=True)
    vehicle: Mapped[dict] = mapped_column(JSONB, default=dict)
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# Consultas agregadas do dashboard do proprietário (migração a3f1c9d2e7b4).
Index("ix_charging_sessions_connector_ended", ChargingSession.connector_id, ChargingSession.ended_at)
Index("ix_charging_sessions_connector_created", ChargingSession.connector_id, ChargingSession.created_at)
Index("ix_reservations_connector_created", Reservation.connector_id, Reservation.created_at)
Index("ix_telemetry_samples_session_captured", Telemetry.session_id, Telemetry.captured_at)


class AiUsage(Base):
    """Uso do assistente de IA: somente metadados (sem perguntas, respostas ou dados pessoais)."""

    __tablename__ = "ai_usage"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"), index=True)
    feature: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(100), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    tools: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class ConnectorHourlyStats(Base):
    """Agregado horário durável por conector (migração c5f0a7e3d912; ``chargegrid_core.forecast.aggregate``).

    Ocupação vem das sessões (registro permanente) e energia das diferenças de telemetria,
    ou da energia da sessão espalhada no tempo quando a telemetria já foi limpa. ``origin``
    separa medido, simulado (bancada) e sintético (demonstração rotulada).
    """

    __tablename__ = "connector_hourly_stats"
    connector_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connectors.id"), primary_key=True)
    hour_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    origin: Mapped[str] = mapped_column(String(12), primary_key=True)
    busy_seconds: Mapped[int] = mapped_column(Integer, default=0)
    energy_wh: Mapped[float] = mapped_column(Numeric(16, 3), default=0)
    energy_basis: Mapped[str] = mapped_column(String(16))
    sessions_started: Mapped[int] = mapped_column(Integer, default=0)
    max_power_w: Mapped[float | None] = mapped_column(Numeric(12, 1))
    generator: Mapped[str | None] = mapped_column(String(20))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=text("now()"))
    __table_args__ = (
        CheckConstraint("origin IN ('measured', 'simulated', 'synthetic')", name="hourly_stats_origin"),
        CheckConstraint("energy_basis IN ('telemetry', 'session_spread', 'synthetic')", name="hourly_stats_basis"),
        CheckConstraint("busy_seconds BETWEEN 0 AND 3600 AND energy_wh >= 0 AND sessions_started >= 0",
                        name="hourly_stats_ranges"),
        CheckConstraint("mod(CAST(EXTRACT(EPOCH FROM hour_start) AS bigint), 3600) = 0", name="hourly_stats_hour_aligned"),
        Index("ix_connector_hourly_stats_hour", "hour_start"),
    )


class AggregateWatermark(Base):
    """Até onde os agregados duráveis estão fechados (a limpeza de telemetria respeita isto)."""

    __tablename__ = "aggregate_watermarks"
    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    rolled_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
