from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field

from ...schemas import Input


class PaymentInput(Input):
    """Orçamento aceito pelo motorista; o teto é calculado pela API."""

    connector_id: UUID
    power_tier: Literal["max", "reduced"] = "max"
    mode: Literal["time", "value", "energy"]
    minutes: int | None = Field(default=None, ge=1, le=1440)
    max_cost: Decimal | None = Field(default=None, gt=0, le=100000)
    energy_kwh: Decimal | None = Field(default=None, gt=0, le=1000)
    max_power_kw: Decimal | None = Field(default=None, gt=0, le=1000)
    coupon_code: str | None = Field(default=None, max_length=50)
