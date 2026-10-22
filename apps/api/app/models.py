import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    DDL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    FetchedValue,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
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
    # Modo apresentação da conta (migração f4b9d2c7e1a3), sincronizado pelo app: no servidor só
    # decide o pagamento do totem dos postos desta conta (simulado em vez de Stripe teste).
    presentation_mode: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    __table_args__ = (CheckConstraint("account_type IN ('consumer', 'vendor')", name="profile_account_type"),)


class SimulatedWallet(Base):
    __tablename__ = "simulated_wallets"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"), primary_key=True)
    balance_cents: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    legacy_imported: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    transactions: Mapped[list] = mapped_column(JSONB, default=list)
    __table_args__ = (CheckConstraint("balance_cents >= 0", name="simulated_wallet_nonnegative"),)


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
    # Resultado do dono (migração b6d2f9a4c8e1): custo do kWh informado pelo dono (NULL = não
    # informado) e comissão da plataforma (contrato; só leitura para o dono).
    energy_cost_per_kwh: Mapped[float | None] = mapped_column(Numeric(10, 4))
    platform_fee_percent: Mapped[float] = mapped_column(Numeric(5, 2), default=25, server_default=text("25"))
    # Pagamento Stripe em modo teste (migração e5a1c7f3b9d2): exigir pagamento antes do
    # START e mostrar o QR de pagamento no painel físico.
    prepay_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    kiosk_payments: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Limites do posto (chargegrid_core.site_load): limite contratado da instalação (loja incluída;
    # NULL = padrão pelo pico estimado) e, desde a migração d8b3f6a2c5e7, a margem ESTIMADA da loja
    # (mínimo e pico típicos; NULL = 14–22 kW). Sem medidor, o pico estimado fica reservado o tempo
    # todo: carregadores = min(max_power_kw, contratado − pico). Rebalanceamento ligado por padrão
    # desde a migração a3e8c5d1f7b9.
    site_limit_kw: Mapped[float | None] = mapped_column(Numeric(10, 3))
    store_min_kw: Mapped[float | None] = mapped_column(Numeric(10, 3))
    store_peak_kw: Mapped[float | None] = mapped_column(Numeric(10, 3))
    rebalance_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # DESCONTINUADAS (sem uso desde d8b3f6a2c5e7; mantidas por uma versão para rollback): consumo
    # simulado/manual da loja e tipo/porte da curva simulada.
    building_load_kw: Mapped[float | None] = mapped_column(Numeric(10, 3))
    building_load_source: Mapped[str | None] = mapped_column(String(20))
    building_load_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    building_profile: Mapped[str | None] = mapped_column(String(20))
    building_size: Mapped[str | None] = mapped_column(String(10))
    # Totem de autoatendimento no painel físico (migração f4b9d2c7e1a3; modules/kiosk_totem).
    kiosk_mode: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180"),
        CheckConstraint("max_power_kw IS NULL OR max_power_kw > 0", name="station_max_power_positive"),
        CheckConstraint("energy_cost_per_kwh IS NULL OR energy_cost_per_kwh BETWEEN 0 AND 100",
                        name="station_energy_cost_range"),
        CheckConstraint("platform_fee_percent BETWEEN 0 AND 100", name="station_platform_fee_range"),
        CheckConstraint("site_limit_kw IS NULL OR site_limit_kw > 0", name="station_site_limit_positive"),
        CheckConstraint("building_load_kw IS NULL OR building_load_kw >= 0", name="station_building_load_range"),
        CheckConstraint("building_load_source IS NULL OR building_load_source IN ('simulated')",
                        name="station_building_load_source"),
        CheckConstraint("store_min_kw IS NULL OR store_min_kw >= 0", name="station_store_min_range"),
        CheckConstraint("store_peak_kw IS NULL OR (store_peak_kw >= 0 AND store_peak_kw <= 10000)",
                        name="station_store_peak_range"),
        CheckConstraint("store_min_kw IS NULL OR store_peak_kw IS NULL OR store_min_kw <= store_peak_kw",
                        name="station_store_min_le_peak"),
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
    # Todo conector É um carregador GoodWe HCA G2 (Modbus TCP, unit id / mDNS
    # cg-hca-<endereço>.local) ligado à tela do ponto. Nunca vazio: sem valor no INSERT, o
    # gatilho do banco põe o próximo endereço livre do posto (1, 2, 3…); o dono pode trocar.
    # Carregador sem resposta: a tela carrega com a simulação interna dela.
    charger_address: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default=FetchedValue())
    # Carregador adicional removido pelo dono (migração e2c7a9d4f6b3) que tinha histórico: a linha
    # fica (sessões, reservas, pagamentos), some das listas e libera o endereço (NULL só aqui).
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("power_kw > 0 AND price_per_kwh >= 0 AND max_duration_minutes > 0"),
        CheckConstraint(
            "power_limit_kw IS NULL OR (power_limit_kw > 0 AND power_limit_kw <= power_kw)",
            name="connector_power_limit_range",
        ),
        CheckConstraint("charger_address IS NULL OR charger_address BETWEEN 1 AND 247",
                        name="connector_charger_address_range"),
        CheckConstraint("charger_address IS NOT NULL OR removed_at IS NOT NULL",
                        name="connector_charger_address_unless_removed"),
        # Dois pontos do mesmo posto nunca falam com o mesmo carregador.
        UniqueConstraint("station_id", "charger_address", name="uq_connector_station_charger_address"),
    )


# Mesmo gatilho da migração c5e9a2d7f4b1 (o schema dos testes nasce de create_all): qualquer
# INSERT sem charger_address (ORM, SQL da fábrica em tools/provision_point.py) recebe o menor
# endereço livre do posto.
CONNECTOR_CHARGER_ADDRESS_TRIGGER = (
    """
CREATE OR REPLACE FUNCTION connector_next_charger_address() RETURNS trigger AS $$
BEGIN
    IF NEW.charger_address IS NULL THEN
        SELECT n INTO NEW.charger_address FROM generate_series(1, 247) AS n
        WHERE NOT EXISTS (
            SELECT 1 FROM connectors c WHERE c.station_id = NEW.station_id AND c.charger_address = n
        )
        ORDER BY n LIMIT 1;
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql
""",
    """
CREATE TRIGGER connector_next_charger_address BEFORE INSERT ON connectors
FOR EACH ROW EXECUTE FUNCTION connector_next_charger_address()
""",
)
for _statement in CONNECTOR_CHARGER_ADDRESS_TRIGGER:
    event.listen(Connector.__table__, "after_create", DDL(_statement).execute_if(dialect="postgresql"))


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
    # Declarado pelo próprio equipamento a cada sync: ["set_power_v1"] e o carregador que ele
    # controla ({model, variant, transport, min_power_w, max_power_w, step_w, phases}).
    capabilities: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    charger: Mapped[dict | None] = mapped_column(JSONB)
    # Estação = a TELA (dispositivo com chave). Carregador adicional comandado por ela: linha
    # própria (sessões/comandos/estado do ponto) sem chave utilizável, ligada à tela; a tela
    # sincroniza por ele com ``charger_address`` no corpo do sync (migração d3f8a1c6e2b7).
    parent_device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("devices.id"), index=True)
    # Aluguel das centrais (migração c4f1a8e6d2b9): quando a linha nasceu (NULL = antes da migração;
    # vale o vínculo do QR) e quando foi revogada (gatilho ``device_revoked_at``: revogar, restaurar
    # de fábrica ou aposentar carregadores sem tocar nesses fluxos).
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=now,
                                                        server_default=text("now()"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index("one_active_device", "connector_id", unique=True, postgresql_where=text("NOT revoked")),
        CheckConstraint("parent_device_id IS NULL OR parent_device_id <> id", name="device_parent_not_self"),
    )


# Mesmo gatilho da migração c4f1a8e6d2b9: a primeira revogação grava ``revoked_at`` (fim do
# aluguel da central), qualquer que seja o caminho que revogou.
DEVICE_REVOKED_AT_TRIGGER = (
    """
CREATE OR REPLACE FUNCTION device_revoked_at() RETURNS trigger AS $$
BEGIN
    IF NEW.revoked AND NEW.revoked_at IS NULL AND (TG_OP = 'INSERT' OR NOT OLD.revoked) THEN
        NEW.revoked_at := now();
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql
""",
    """
CREATE TRIGGER device_revoked_at BEFORE INSERT OR UPDATE OF revoked ON devices
FOR EACH ROW EXECUTE FUNCTION device_revoked_at()
""",
)
for _statement in DEVICE_REVOKED_AT_TRIGGER:
    event.listen(Device.__table__, "after_create", DDL(_statement).execute_if(dialect="postgresql"))


class CentralRentRate(Base):
    """Aluguel mensal por central (contrato; ``chargegrid_core.rent``), com vigência por data local.

    ``station_id`` NULL = padrão da plataforma; numa linha de posto, ``monthly_amount`` NULL =
    volta ao padrão a partir de ``effective_from``. Gravado só pela administração
    (``tools/set_central_rent.py``); o dono só lê.
    """

    __tablename__ = "central_rent_rates"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    station_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stations.id"), index=True)
    monthly_amount: Mapped[float | None] = mapped_column(Numeric(10, 2))
    effective_from: Mapped[datetime] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=text("now()"))
    __table_args__ = (
        CheckConstraint("monthly_amount IS NULL OR monthly_amount BETWEEN 0 AND 10000",
                        name="central_rent_amount_range"),
        CheckConstraint("station_id IS NOT NULL OR monthly_amount IS NOT NULL", name="central_rent_default_amount"),
        Index("uq_central_rent_default", "effective_from", unique=True, postgresql_where=text("station_id IS NULL")),
        Index("uq_central_rent_station", "station_id", "effective_from", unique=True,
              postgresql_where=text("station_id IS NOT NULL")),
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
    # Explicação do preço travado ao reservar (chargegrid_core.receipt.price_terms).
    price_terms: Mapped[dict | None] = mapped_column(JSONB)
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
    # Potência ao vivo: limite do motorista/carro pedido no início, alvo da última decisão,
    # potência aplicada confirmada pelo equipamento e o motivo em texto (app, painel e recibo).
    requested_power_kw: Mapped[float | None] = mapped_column(Numeric(10, 3))
    target_power_kw: Mapped[float | None] = mapped_column(Numeric(10, 3))
    applied_power_kw: Mapped[float | None] = mapped_column(Numeric(10, 3))
    power_state: Mapped[str | None] = mapped_column(String(20))
    power_reason: Mapped[str | None] = mapped_column(String(300))
    power_reason_short: Mapped[str | None] = mapped_column(String(60))
    power_reason_code: Mapped[str | None] = mapped_column(String(30))
    power_decision_id: Mapped[int | None] = mapped_column(BigInteger)
    last_measurement_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cost_estimate: Mapped[float] = mapped_column(Numeric(12, 4), default=0)
    end_reason: Mapped[str | None] = mapped_column(String(100))
    # Recibo e resultado do dono (migração b6d2f9a4c8e1), gravados ao travar o preço no início:
    # explicação do preço (chargegrid_core.receipt.price_terms), custo do kWh e comissão do posto.
    price_terms: Mapped[dict | None] = mapped_column(JSONB)
    energy_cost_per_kwh: Mapped[float | None] = mapped_column(Numeric(10, 4))
    platform_fee_percent: Mapped[float | None] = mapped_column(Numeric(5, 2))
    # Permanência após a recarga (migração c8e3a5f2d914, chargegrid_core.overstay): termos aceitos
    # no início, intervalo com o cabo ainda conectado e a taxa sobre os segundos confirmados.
    overstay_terms: Mapped[dict | None] = mapped_column(JSONB)
    overstay_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    overstay_last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    overstay_billable_seconds: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    overstay_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    overstay_end_reason: Mapped[str | None] = mapped_column(String(30))
    overstay_fee: Mapped[float] = mapped_column(Numeric(12, 4), default=0, server_default=text("0"))
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
        CheckConstraint("energy_cost_per_kwh IS NULL OR energy_cost_per_kwh BETWEEN 0 AND 100",
                        name="session_energy_cost_range"),
        CheckConstraint("platform_fee_percent IS NULL OR platform_fee_percent BETWEEN 0 AND 100",
                        name="session_platform_fee_range"),
        CheckConstraint(
            "power_state IS NULL OR power_state IN ('applied','reducing','raising','waiting','paused','fixed')",
            name="session_power_state",
        ),
        CheckConstraint("applied_power_kw IS NULL OR applied_power_kw >= 0", name="session_applied_power_range"),
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
    # Dados do fato (ex.: potência aplicada e motivo); null nos eventos sem detalhe.
    data: Mapped[dict | None] = mapped_column(JSONB)
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

# Permanência após a recarga (migração c8e3a5f2d914): um intervalo aberto por ponto.
OVERSTAY_END_REASONS = ("disconnected", "device_reboot", "observation_lost", "owner_waived")
_OVERSTAY_OPEN = text("overstay_started_at IS NOT NULL AND overstay_ended_at IS NULL")
for _constraint in (
    CheckConstraint("overstay_billable_seconds >= 0 AND overstay_fee >= 0", name="session_overstay_amounts"),
    CheckConstraint("overstay_ended_at IS NULL OR overstay_started_at IS NOT NULL", name="session_overstay_order"),
    CheckConstraint(
        "overstay_end_reason IS NULL OR overstay_end_reason IN ("
        + ", ".join(f"'{reason}'" for reason in OVERSTAY_END_REASONS) + ")",
        name="session_overstay_end_reason",
    ),
):
    ChargingSession.__table__.append_constraint(_constraint)
Index("one_open_overstay_connector", ChargingSession.connector_id, unique=True, postgresql_where=_OVERSTAY_OPEN)
Index("ix_open_overstay_user", ChargingSession.user_id, postgresql_where=_OVERSTAY_OPEN)


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


PAYMENT_STATUSES = (
    "awaiting_payment", "declined", "authorized", "paid", "in_use", "expired", "canceled", "completed",
)
PAYMENT_OPEN = ("awaiting_payment", "declined", "authorized", "paid")
SETTLEMENT_STATUSES = ("none", "due", "settling", "done", "failed")


class Payment(Base):
    """Pré-pagamento de uma recarga (Stripe em modo teste); valores em centavos inteiros.

    Uma fonte de verdade para o dinheiro: o teto aceito (``amount_cents``), os termos travados
    no orçamento e o acerto final (capturado, devolvido, perdoado). Ver ``chargegrid_core.billing``.
    """

    __tablename__ = "payments"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"), index=True)
    connector_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connectors.id"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("charging_sessions.id"), unique=True)
    origin: Mapped[str] = mapped_column(String(10), default="app")
    provider: Mapped[str] = mapped_column(String(20), default="stripe")
    environment: Mapped[str] = mapped_column(String(10), default="test")
    status: Mapped[str] = mapped_column(String(20), default="awaiting_payment")
    settlement_status: Mapped[str] = mapped_column(String(20), default="none")
    amount_cents: Mapped[int] = mapped_column(Integer)
    energy_cap_cents: Mapped[int] = mapped_column(Integer)
    fixed_fee_cents: Mapped[int] = mapped_column(Integer, default=0)
    overstay_reserve_cents: Mapped[int] = mapped_column(Integer, default=0)
    energy_cents: Mapped[int | None] = mapped_column(Integer)
    overstay_cents: Mapped[int | None] = mapped_column(Integer)
    charge_cents: Mapped[int | None] = mapped_column(Integer)
    waived_cents: Mapped[int] = mapped_column(Integer, default=0)
    uncollected_cents: Mapped[int] = mapped_column(Integer, default=0)
    captured_cents: Mapped[int] = mapped_column(Integer, default=0)
    refunded_cents: Mapped[int] = mapped_column(Integer, default=0)
    provider_fee_cents: Mapped[int | None] = mapped_column(Integer)
    # Termos travados no orçamento: o START com este pagamento usa estes, não os do momento.
    price_per_kwh: Mapped[float] = mapped_column(Numeric(10, 4))
    base_price_per_kwh: Mapped[float] = mapped_column(Numeric(10, 4))
    demand_multiplier: Mapped[float] = mapped_column(Numeric(4, 2))
    discount_percent: Mapped[int] = mapped_column(Integer, default=0)
    coupon_code: Mapped[str | None] = mapped_column(String(50))
    max_duration_minutes: Mapped[int] = mapped_column(Integer)
    max_power_kw: Mapped[float | None] = mapped_column(Numeric(10, 3))
    quote: Mapped[dict] = mapped_column(JSONB, default=dict)
    provider_checkout_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    provider_payment_intent_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    provider_status: Mapped[str | None] = mapped_column(String(40))
    method: Mapped[str | None] = mapped_column(String(30))
    checkout_url: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    start_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_provider_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settle_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(200))
    kiosk_token_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (
        CheckConstraint("origin IN ('app', 'kiosk')", name="payment_origin"),
        CheckConstraint("environment = 'test'", name="payment_environment_test"),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{value}'" for value in PAYMENT_STATUSES) + ")", name="payment_status"
        ),
        CheckConstraint(
            "settlement_status IN (" + ", ".join(f"'{value}'" for value in SETTLEMENT_STATUSES) + ")",
            name="payment_settlement_status",
        ),
        CheckConstraint(
            "amount_cents > 0 AND energy_cap_cents > 0 AND fixed_fee_cents >= 0 AND overstay_reserve_cents >= 0"
            " AND amount_cents = energy_cap_cents + fixed_fee_cents + overstay_reserve_cents",
            name="payment_amounts",
        ),
        CheckConstraint(
            "captured_cents >= 0 AND refunded_cents >= 0 AND waived_cents >= 0 AND uncollected_cents >= 0"
            " AND captured_cents <= amount_cents AND refunded_cents <= captured_cents"
            " AND (charge_cents IS NULL OR charge_cents BETWEEN 0 AND amount_cents)",
            name="payment_settlement_amounts",
        ),
        CheckConstraint("discount_percent BETWEEN 0 AND 100", name="payment_discount_range"),
        Index("ix_payments_connector_status", "connector_id", "status"),
        Index(
            "ix_payments_settlement", "settlement_status",
            postgresql_where=text("settlement_status IN ('due', 'settling')"),
        ),
        # Um pagamento do app em aberto por pessoa (o convidado do painel fica de fora).
        Index(
            "one_open_app_payment_user", "user_id", unique=True,
            postgresql_where=text(
                "origin = 'app' AND status IN ('awaiting_payment', 'declined', 'authorized', 'paid')"
            ),
        ),
    )


KIOSK_ORDER_STATUSES = ("held", "awaiting_payment", "paid", "charging", "finished", "canceled", "expired", "failed")
# Pedido aberto: trava o ponto para o totem até ``expires_at`` (a sessão assume depois do START).
KIOSK_ORDER_OPEN = ("held", "awaiting_payment", "paid")
KIOSK_METHODS = ("simulated", "stripe")


class KioskOrder(Base):
    """Pedido do totem de autoatendimento (migração f4b9d2c7e1a3; ``modules/kiosk_totem``).

    Um por compra no painel, do perfil convidado do ponto: termos travados no orçamento, a trava
    do ponto (``expires_at`` enquanto aberto), o pagamento e a sessão. O token do recibo do
    visitante não é guardado: só o sal da derivação e o SHA-256.
    """

    __tablename__ = "kiosk_orders"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    connector_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connectors.id"))
    guest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"))
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"), unique=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("charging_sessions.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="held")
    method: Mapped[str] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(10))
    quote: Mapped[dict] = mapped_column(JSONB, default=dict)
    quote_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_salt: Mapped[str] = mapped_column(String(32))
    token_hash: Mapped[str] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{value}'" for value in KIOSK_ORDER_STATUSES) + ")", name="kiosk_order_status"
        ),
        CheckConstraint("method IN ('simulated', 'stripe')", name="kiosk_order_method"),
        CheckConstraint("mode IN ('value', 'time', 'energy')", name="kiosk_order_mode"),
        Index("ix_kiosk_orders_connector_created", "connector_id", "created_at"),
        # Um pedido aberto (trava) por ponto.
        Index(
            "one_open_kiosk_order_connector", "connector_id", unique=True,
            postgresql_where=text("status IN ('held', 'awaiting_payment', 'paid')"),
        ),
    )


class PaymentEvent(Base):
    """Eventos de webhook já processados (deduplicação); o corpo não é guardado."""

    __tablename__ = "payment_events"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), default="stripe")
    event_id: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(80))
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"), index=True)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("provider", "event_id"),)


class PowerDecision(Base):
    """Registro legível de cada decisão de divisão de potência de um posto (append-only)."""

    __tablename__ = "power_decisions"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    station_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stations.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    trigger: Mapped[str] = mapped_column(String(40))
    inputs: Mapped[dict] = mapped_column(JSONB)
    available_kw: Mapped[float | None] = mapped_column(Numeric(10, 3))
    exceeded_kw: Mapped[float] = mapped_column(Numeric(10, 3), default=0)
    summary: Mapped[str] = mapped_column(String(300))
    input_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (Index("ix_power_decisions_station_created", "station_id", "created_at"),)
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
