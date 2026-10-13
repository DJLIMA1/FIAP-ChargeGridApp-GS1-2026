"""Contratos do Modo Motorista. Campos opcionais: o que faltar usa o perfil salvo ou o padrão."""
from typing import Literal

from pydantic import Field

from ...schemas import Input

HHMM = r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$"


def number(low, high, **kwargs):
    return Field(default=None, ge=low, le=high, allow_inf_nan=False, **kwargs)


class VehicleInput(Input):
    preset: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[a-z0-9_]+$")
    name: str | None = Field(default=None, max_length=60)
    usable_battery_kwh: float | None = number(5, 250)
    consumption_kwh_per_100km: float | None = number(5, 60)
    max_ac_kw: float | None = number(1, 43)
    max_dc_kw: float | None = number(0, 400)
    connectors: list[str] | None = Field(default=None, min_length=1, max_length=6)


class MealInput(Input):
    kind: Literal["almoco", "jantar", "lanche"]
    start: str = Field(pattern=HHMM)
    duration_minutes: int = Field(default=45, ge=10, le=120)
    flex_minutes: int = Field(default=30, ge=0, le=240)
    flexible: bool = False
    enabled: bool = True


class PreferencesInput(Input):
    shift_start: str | None = Field(default=None, pattern=HHMM)
    shift_end: str | None = Field(default=None, pattern=HHMM)
    meals: list[MealInput] | None = Field(default=None, max_length=4)
    km_per_hour: float | None = number(5, 80)
    earnings_per_hour: float | None = number(0, 500)
    earnings_per_km: float | None = number(0, 50)
    reserve_percent: float | None = number(5, 50)
    max_charge_percent: float | None = number(50, 100)
    home_charging: bool | None = None
    home_price_per_kwh: float | None = number(0, 10)
    city: str | None = Field(default=None, max_length=60)


class DriverProfileInput(Input):
    vehicle: VehicleInput = Field(default_factory=VehicleInput)
    preferences: PreferencesInput = Field(default_factory=PreferencesInput)


class PlanContext(Input):
    rain: bool | None = None
    holiday: bool = False
    airport: bool = False


class NextStopInput(Input):
    soc_percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    lat: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    lng: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    radius_km: float = Field(default=30, gt=0, le=100, allow_inf_nan=False)
    vehicle: VehicleInput | None = None
    preferences: PreferencesInput | None = None
    context: PlanContext = Field(default_factory=PlanContext)
    live_signals: bool = True


class PlanInput(NextStopInput):
    mode: Literal["auto", "full_shift"] = "auto"
