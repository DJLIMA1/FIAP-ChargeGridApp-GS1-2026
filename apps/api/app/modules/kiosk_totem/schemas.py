"""Corpos dos endpoints do totem (``/v1/devices/kiosk/*``); contrato em docs/esp32-protocol.md."""

from decimal import Decimal
from typing import Literal

from pydantic import Field

from ...schemas import Input


class KioskQuoteInput(Input):
    """Como cobrar e quanto: R$ (``amount``), minutos (``minutes``) ou kWh (``energy_kwh``, 1 casa)."""

    mode: Literal["value", "time", "energy", "autonomy"]
    amount: Decimal | None = Field(default=None, gt=0, le=10000, decimal_places=2, allow_inf_nan=False)
    minutes: int | None = Field(default=None, ge=1, le=1440)
    energy_kwh: Decimal | None = Field(default=None, gt=0, le=1000, decimal_places=1, allow_inf_nan=False)
    autonomy_km: int | None = Field(default=None, ge=1, le=2000)
    power: Literal["max", "reduced"] = "max"


class KioskOrderInput(KioskQuoteInput):
    """"Aceitar e pagar": o orçamento mostrado (``quote_hash``) e a versão da taxa de permanência vista."""

    quote_hash: str = Field(min_length=8, max_length=64, pattern=r"^[0-9a-f]+$")
    overstay_terms_version: str | None = Field(default=None, min_length=1, max_length=40)


class KioskPayInput(Input):
    """Só conferência: o método é decidido pelo servidor (``voucher``/``card_terminal`` reservados)."""

    method: Literal["simulated", "stripe", "voucher", "card_terminal"] | None = None
    funding_source: Literal["balance", "pix", "card"] | None = None
