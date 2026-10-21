from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StationInput(Input):
    name: str = Field(min_length=1, max_length=100)
    address: str = Field(min_length=1, max_length=300)
    latitude: Decimal = Field(ge=-90, le=90)
    longitude: Decimal = Field(ge=-180, le=180)


class ClaimInput(Input):
    token: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]{43}$")
    station_id: UUID | None = None


class AmenityInput(Input):
    kind: Literal["restaurante", "cafe", "banheiro", "shopping", "conveniencia"]
    name: str = Field(default="", max_length=80)
    distance_m: int | None = Field(default=None, ge=0, le=5000)


class StationPatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    address: str | None = Field(default=None, min_length=1, max_length=300)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    active: bool | None = None
    amenities: list[AmenityInput] | None = Field(default=None, max_length=12)
    # Teto de potência compartilhado pelos conectores (null remove); validado em chargegrid_core.power.
    max_power_kw: Decimal | None = Field(default=None, allow_inf_nan=False)
    power_limit_notify: bool | None = None
    # Pagamento (Stripe, modo teste): exigir antes do START e QR de pagamento no painel.
    prepay_required: bool | None = None
    kiosk_payments: bool | None = None
    # Totem de autoatendimento no painel físico (padrão desligado).
    kiosk_mode: bool | None = None


class ConnectorInput(Input):
    public_code: str = Field(min_length=1, max_length=50)
    connector_type: str = Field(min_length=1, max_length=50)
    power_kw: Decimal = Field(gt=0, le=1000)
    price_per_kwh: Decimal = Field(ge=0, le=10000)
    max_duration_minutes: int = Field(default=60, ge=1, le=1440)


class ConnectorPatch(Input):
    public_code: str | None = Field(default=None, min_length=1, max_length=50)
    connector_type: str | None = Field(default=None, min_length=1, max_length=50)
    power_kw: Decimal | None = Field(default=None, gt=0, le=1000)
    price_per_kwh: Decimal | None = Field(default=None, ge=0, le=10000)
    max_duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    active: bool | None = None
    # Limite do vendedor para este conector (null remove); nunca acima de power_kw.
    power_limit_kw: Decimal | None = Field(default=None, allow_inf_nan=False)
    # Carregador externo GoodWe HCA G2 ligado à tela deste ponto (null remove); único por posto.
    charger_address: int | None = Field(default=None, ge=1, le=247, strict=True)


class ProfilePatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
    vehicle_description: str | None = Field(default=None, max_length=200)
    # Modo apresentação da conta (o app sincroniza ao alternar); decide o pagamento do totem.
    presentation_mode: bool | None = None


class ReserveInput(Input):
    connector_id: UUID


class StartInput(Input):
    public_code: str | None = Field(default=None, min_length=1, max_length=50)
    presence_code: str = Field(min_length=7, max_length=7, pattern=r"^#[Ff][0-9]{5}$")
    reservation_id: UUID | None = None
    coupon_code: str | None = Field(default=None, max_length=50)
    max_duration_minutes: int = Field(default=30, ge=1, le=1440)
    max_cost: Decimal | None = Field(default=None, gt=0, le=100000)
    # Car battery: initial SoC, usable capacity and who drives the SoC afterwards.
    soc_percent: Decimal | None = Field(default=None, ge=0, le=100)
    battery_kwh: Decimal | None = Field(default=None, ge=5, le=250)
    soc_source: Literal["simulated", "phone"] | None = None
    # Limite geral do motorista (carro/escolha no app); a API aplica min(efetivo do conector, este).
    max_power_kw: Decimal | None = Field(default=None, gt=0, le=1000)
    # Pré-pagamento confirmado (Stripe, modo teste): a recarga usa o teto e os termos dele.
    payment_id: UUID | None = None
    # Versão das condições da taxa de permanência mostradas e aceitas no app (GET /stations).
    overstay_terms_version: str | None = Field(default=None, min_length=1, max_length=40)


class SocInput(Input):
    soc_percent: Decimal = Field(ge=0, le=100)


class Ack(Input):
    command_id: UUID
    status: Literal["received", "applied", "failed"]
    error: str | None = Field(default=None, max_length=200)
    new_device_key_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    new_claim_token_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # SET_POWER: limite que o equipamento instalou (W), confirmado por ele.
    applied_power_w: Decimal | None = Field(default=None, ge=0, le=1000000)


class ChargerInfo(Input):
    """Carregador controlado pelo equipamento (declarado por ele; transporte simulado rotulado)."""

    model: str = Field(min_length=1, max_length=40)
    variant: str | None = Field(default=None, max_length=40)
    transport: Literal["simulated", "modbus_tcp", "modbus_rtu", "none"] = "none"
    min_power_w: int = Field(ge=0, le=1000000)
    max_power_w: int = Field(gt=0, le=1000000)
    step_w: int = Field(default=100, gt=0, le=100000)
    phases: int | None = Field(default=None, ge=1, le=3)
    # Carregador externo (aditivo, tela com GoodWe HCA G2 via Modbus TCP): endereço e estado do link.
    address: int | None = Field(default=None, ge=1, le=247)
    link: Literal["online", "offline"] | None = None


class SyncInput(Input):
    boot_id: str = Field(min_length=1, max_length=100)
    sequence: int = Field(ge=0, le=2147483647)
    firmware_version: str = Field(max_length=50)
    session_id: UUID | None = None
    physical_state: Literal["idle", "reserved", "charging", "stopped", "fault"]
    connected: bool
    soc_percent: Decimal | None = Field(default=None, ge=0, le=100)
    energy_wh: Decimal = Field(default=Decimal(0), ge=0, le=100000000)
    power_w: Decimal | None = Field(default=None, ge=0, le=1000000)
    source: Literal["simulated", "measured", "estimated"]
    captured_at: datetime
    end_reason: str | None = Field(default=None, max_length=100)
    acks: list[Ack] = Field(default_factory=list, max_length=20)
    # Aditivos (firmware 0.5.0+/simulador): capacidade de ajuste ao vivo e limite aplicado agora.
    capabilities: list[Annotated[str, StringConstraints(max_length=40)]] = Field(default_factory=list, max_length=10)
    applied_power_w: Decimal | None = Field(default=None, ge=0, le=1000000)
    charger: ChargerInfo | None = None


class CouponInput(Input):
    code: str = Field(min_length=1, max_length=50)
    description: str = Field(max_length=200)
    station_id: UUID | None = None
    discount_percent: int = Field(ge=0, le=100)
    valid_until: datetime


class CouponPatch(Input):
    description: str | None = Field(default=None, max_length=200)
    discount_percent: int | None = Field(default=None, ge=0, le=100)
    valid_until: datetime | None = None
    active: bool | None = None


class AuthInput(Input):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class PasswordInput(AuthInput):
    # Passwords are opaque credentials; trimming changes the secret that was typed.
    # Login accepts legacy passwords even if new accounts use a stronger policy.
    password: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(min_length=1, max_length=128)


class RegisterInput(PasswordInput):
    password: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=100)
    account_type: Literal["consumer", "vendor"] = "consumer"


class CodeInput(AuthInput):
    code: str = Field(min_length=6, max_length=128)


class ResetInput(PasswordInput):
    password: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(min_length=8, max_length=128)
    code: str = Field(min_length=6, max_length=128)


class PasswordUpdateInput(Input):
    password: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(min_length=8, max_length=128)


class RefreshInput(Input):
    refresh_token: str = Field(min_length=1, max_length=4096)


class PowerSiteInput(Input):
    """Limite contratado (null = padrão do tipo/porte), rebalanceamento e tipo/porte do estabelecimento."""

    site_limit_kw: Decimal | None = Field(default=None, allow_inf_nan=False)
    rebalance_enabled: bool | None = None
    # Curva do consumo SIMULADO da loja (chargegrid_core.site_load); null volta ao padrão.
    building_profile: Literal["conveniencia", "farmacia", "padaria", "supermercado", "restaurante",
                              "shopping"] | None = None
    building_size: Literal["pequeno", "medio", "grande"] | None = None


class BuildingLoadInput(Input):
    """Consumo da loja enviado pelo simulador/demo (vale 30 min); null volta à simulação automática."""

    building_load_kw: Decimal | None = Field(ge=0, le=10000, allow_inf_nan=False)
