from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from ...schemas import Input


class ChatMessage(Input):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatContext(Input):
    mode: Literal["driver", "owner"] = "driver"
    screen: str | None = Field(default=None, max_length=40)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


class ChatInput(Input):
    messages: list[ChatMessage] = Field(min_length=1, max_length=12)
    context: ChatContext = Field(default_factory=ChatContext)


class SearchInput(Input):
    query: str = Field(min_length=2, max_length=300)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


class SessionInsightInput(Input):
    session_id: UUID


class OwnerInsightsInput(Input):
    """Mesmo filtro do dashboard (``from``/``to`` ISO e ``station_id`` opcional).
    Sem ``from``/``to``, analisa os últimos ``days`` dias."""

    start: datetime | None = Field(default=None, alias="from")
    end: datetime | None = Field(default=None, alias="to")
    station_id: UUID | None = None
    days: int = Field(default=30, ge=1, le=366)
