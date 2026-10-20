"""De onde vem o ganho por hora do motorista — sem obrigar ninguém a digitar.

Cadeia (a primeira que tiver valor vence):

1. **informado** — o motorista digitou a própria média em Ajustes;
2. fontes externas que implementam ``EarningsSource`` — hoje só a interface e o agregador
   ``TripHistory``; um adaptador da Uber Driver API (escopos restritos, aprovação da Uber e OAuth de
   cada motorista) alimentaria o ``TripHistory`` no futuro (ver docs/modo-motorista.md);
3. **estimativa** — R$ 38/h do ChargeGrid × curva de demanda por horário. Sempre rotulada "estimado".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from ..formatting import brl
from .models import DriverPreferences

SOURCE_TEXT = {'estimativa': 'estimado', 'informado': 'seu ganho', 'uber': 'histórico da Uber'}
MIN_ONLINE_MINUTES = 60


@runtime_checkable
class EarningsSource(Protocol):
    """Fonte de ganho médio por hora rodando. ``hourly`` devolve ``None`` sem dados suficientes."""

    source: str

    def hourly(self) -> float | None: ...


@dataclass(frozen=True)
class Trip:
    start: datetime
    end: datetime
    fare: float
    distance_km: float | None = None


@dataclass(frozen=True)
class TripHistory:
    """Agrega corridas (ex.: histórico da Uber) em R$/h e km/h por hora *online*.

    O histórico só tem o tempo em corrida; intervalos de até ``gap_minutes`` entre corridas contam
    como tempo online esperando a próxima (estimativa), intervalos maiores encerram a sessão.
    """

    trips: tuple[Trip, ...]
    source: str = 'uber'
    gap_minutes: int = 30

    def _sessions(self) -> list[tuple[datetime, datetime]]:
        sessions: list[list[datetime]] = []
        for trip in sorted((t for t in self.trips if t.end > t.start), key=lambda t: t.start):
            if sessions and trip.start - sessions[-1][1] <= timedelta(minutes=self.gap_minutes):
                sessions[-1][1] = max(sessions[-1][1], trip.end)
            else:
                sessions.append([trip.start, trip.end])
        return [(start, end) for start, end in sessions]

    def online_minutes(self) -> float:
        return sum((end - start).total_seconds() / 60 for start, end in self._sessions())

    def hourly(self) -> float | None:
        minutes = self.online_minutes()
        if minutes < MIN_ONLINE_MINUTES:
            return None
        return round(sum(max(0.0, trip.fare) for trip in self.trips if trip.end > trip.start) / (minutes / 60), 2)

    def km_per_hour(self) -> float | None:
        minutes = self.online_minutes()
        distances = [trip.distance_km for trip in self.trips if trip.end > trip.start]
        if minutes < MIN_ONLINE_MINUTES or not distances or any(d is None for d in distances):
            return None
        return round(sum(distances) / (minutes / 60), 1)


def resolve_earnings(preferences: DriverPreferences, *sources: EarningsSource) -> dict:
    """``{per_hour, source, estimated, label}``: o que o planejador usa e como a tela descreve."""
    source = preferences.source('earnings_per_hour')
    value = preferences.hourly_earnings
    if source != 'informado':
        for candidate in sources:
            found = candidate.hourly()
            if found:
                value, source = found, candidate.source
                break
    estimated = source == 'estimativa'
    label = f"{brl(value).replace(',00', '')}/h " + ('estimado' if estimated else f'({SOURCE_TEXT.get(source, source)})')
    return {'per_hour': round(value, 2), 'source': source, 'estimated': estimated, 'label': label}
