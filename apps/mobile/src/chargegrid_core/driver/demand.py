"""Curva de demanda/ganho por horário para motoristas de app.

Não existe API oficial pública de demanda da Uber/99. O padrão aqui é uma
**heurística** de grandes cidades brasileiras (picos ~6h30–9h30 e ~17h–20h,
almoço, sexta/sábado à noite, madrugada fraca) e é sempre rotulado como
"estimativa". Sinais ao vivo (clima, eventos) entram pela interface
``DemandSignal`` e apenas multiplicam a curva base.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Protocol, runtime_checkable

PEAK_THRESHOLD = 1.3
SLOT_MINUTES = 15

# (minuto do dia, multiplicador) — interpolação linear entre os pontos.
_WEEKDAY = ((0, 0.5), (300, 0.45), (360, 0.85), (390, 1.35), (450, 1.5), (540, 1.35), (570, 1.0),
            (660, 0.9), (720, 1.15), (810, 1.1), (840, 0.9), (960, 0.95), (1020, 1.4), (1080, 1.55),
            (1170, 1.45), (1200, 1.1), (1260, 0.95), (1320, 0.85), (1440, 0.6))
_FRIDAY = _WEEKDAY[:13] + ((1080, 1.6), (1170, 1.5), (1200, 1.3), (1260, 1.2), (1320, 1.3), (1440, 1.4))
_SATURDAY = ((0, 1.4), (120, 1.3), (240, 0.8), (300, 0.5), (420, 0.6), (600, 0.85), (720, 1.1),
             (840, 1.0), (1020, 1.0), (1140, 1.15), (1260, 1.25), (1320, 1.35), (1440, 1.4))
_SUNDAY = ((0, 1.35), (120, 1.2), (240, 0.7), (300, 0.45), (480, 0.55), (660, 0.85), (780, 1.05),
           (900, 0.85), (1080, 1.05), (1200, 1.1), (1290, 0.85), (1440, 0.55))
_CURVES = {0: _WEEKDAY, 1: _WEEKDAY, 2: _WEEKDAY, 3: _WEEKDAY, 4: _FRIDAY, 5: _SATURDAY, 6: _SUNDAY}


def _interpolate(points, minute: float) -> float:
    for (m0, v0), (m1, v1) in zip(points, points[1:], strict=False):
        if m0 <= minute <= m1:
            return v0 + (v1 - v0) * (minute - m0) / (m1 - m0)
    return points[-1][1]


def base_multiplier(when: datetime, holiday: bool = False) -> float:
    """Multiplicador relativo de ganho por hora (1,0 = média do motorista)."""
    curve = _SUNDAY if holiday else _CURVES[when.weekday()]
    minute = when.hour * 60 + when.minute + SLOT_MINUTES / 2
    return round(_interpolate(curve, minute), 4)


@runtime_checkable
class DemandSignal(Protocol):
    """Fonte de demanda. ``multiplier`` retorna o fator para o slot que começa em ``when``."""

    source: str

    def multiplier(self, when: datetime) -> float: ...


@dataclass(frozen=True)
class BonusWindow:
    """Bônus opcional (aeroporto, show, jogo): multiplica a demanda em uma janela."""

    label: str
    start: datetime
    end: datetime
    factor: float = 1.2

    def applies(self, when: datetime) -> bool:
        return self.start <= when < self.end


@dataclass
class HeuristicDemand:
    """Padrão de grandes cidades brasileiras + feriados + bônus. Sempre "estimativa"."""

    holidays: frozenset[date] = frozenset()
    bonuses: tuple[BonusWindow, ...] = ()
    source: str = 'heuristica'

    def multiplier(self, when: datetime) -> float:
        value = base_multiplier(when, when.date() in self.holidays)
        for bonus in self.bonuses:
            if bonus.applies(when):
                value *= bonus.factor
        return value


@dataclass
class WeatherSignal:
    """Clima por hora (ex.: Open-Meteo). Chuva aumenta a procura por corridas.

    ``hourly`` mapeia o início da hora local (sem fuso) → (precipitação mm, temperatura °C).
    """

    hourly: dict[datetime, tuple[float | None, float | None]] = field(default_factory=dict)
    source: str = 'open-meteo'

    def conditions(self, when: datetime):
        return self.hourly.get(when.replace(minute=0, second=0, microsecond=0, tzinfo=None))

    def multiplier(self, when: datetime) -> float:
        found = self.conditions(when)
        if not found:
            return 1.0
        precipitation, temperature = found
        factor = 1.0
        if precipitation is not None and precipitation >= 2.5:
            factor *= 1.35
        elif precipitation is not None and precipitation >= 0.2:
            factor *= 1.2
        if temperature is not None and (temperature >= 32 or temperature <= 10):
            factor *= 1.05
        return factor

    def rainy_hours(self, start: datetime, end: datetime) -> list[datetime]:
        hours, current = [], start.replace(minute=0, second=0, microsecond=0)
        while current < end:
            found = self.conditions(current)
            if found and found[0] is not None and found[0] >= 0.2:
                hours.append(current)
            current += timedelta(hours=1)
        return hours


@dataclass
class ManualContext:
    """Contexto informado pelo motorista quando não há sinal ao vivo (ex.: "está chovendo")."""

    rain: bool = False
    source: str = 'informado'

    def multiplier(self, when: datetime) -> float:
        return 1.2 if self.rain else 1.0


@dataclass
class CombinedDemand:
    """Curva base × sinais adicionais (cada sinal falho deve ser omitido por quem monta)."""

    base: DemandSignal
    extras: tuple[DemandSignal, ...] = ()

    @property
    def source(self) -> str:
        return '+'.join([self.base.source, *(signal.source for signal in self.extras)])

    def multiplier(self, when: datetime) -> float:
        value = self.base.multiplier(when)
        for signal in self.extras:
            value *= signal.multiplier(when)
        return round(min(3.0, max(0.1, value)), 4)


def peak_windows(slots: list[tuple[datetime, float]], threshold: float = PEAK_THRESHOLD):
    """Agrupa slots consecutivos com multiplicador ≥ ``threshold`` em janelas (início, fim, pico)."""
    windows, current = [], None
    for when, value in slots:
        if value >= threshold:
            if current is None:
                current = [when, when + timedelta(minutes=SLOT_MINUTES), value]
            else:
                current[1], current[2] = when + timedelta(minutes=SLOT_MINUTES), max(current[2], value)
        elif current is not None:
            windows.append(tuple(current))
            current = None
    if current is not None:
        windows.append(tuple(current))
    return windows
