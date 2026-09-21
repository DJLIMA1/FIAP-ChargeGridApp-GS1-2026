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


class StationPatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    address: str | None = Field(default=None, min_length=1, max_length=300)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    active: bool | None = None


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


class ProfilePatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
    vehicle_description: str | None = Field(default=None, max_length=200)


class ReserveInput(Input):
    connector_id: UUID


class StartInput(Input):
    public_code: str = Field(min_length=1, max_length=50)
    reservation_id: UUID | None = None
    coupon_code: str | None = Field(default=None, max_length=50)
    max_duration_minutes: int = Field(default=30, ge=1, le=1440)
    max_cost: Decimal | None = Field(default=None, gt=0, le=100000)


class Ack(Input):
    command_id: UUID
    status: Literal["received", "applied", "failed"]
    error: str | None = Field(default=None, max_length=200)


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
