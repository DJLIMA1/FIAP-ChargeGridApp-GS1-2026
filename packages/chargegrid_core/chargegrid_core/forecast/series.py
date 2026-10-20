"""Série horária de um posto (hora local), montada a partir dos agregados por conector."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .aggregate import parse_time
from .calendar import iso, to_local

HOUR = timedelta(hours=1)


@dataclass
class StationSeries:
    """``occ[i]``: ocupação (0–1) da hora ``start + i``; ``kwh[i]``: energia entregue.

    ``None`` = sem histórico (antes do primeiro registro). Hora sem linha depois do início
    é ocupação zero observada: as sessões são completas.
    """

    start: datetime
    occ: list[float | None]
    kwh: list[float | None]
    connectors: int
    synthetic: list[bool] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.occ)

    def index(self, local: datetime) -> int:
        return int((local - self.start).total_seconds() // 3600)

    def at(self, index: int) -> datetime:
        return self.start + index * HOUR

    @property
    def first(self) -> int:
        """Índice da primeira hora com histórico (``len`` se não houver)."""
        return next((i for i, value in enumerate(self.occ) if value is not None), len(self.occ))

    def coverage(self) -> dict:
        days, synthetic_days = set(), set()
        for index, value in enumerate(self.occ):
            if value is None:
                continue
            day = self.at(index).date()
            if self.synthetic and self.synthetic[index]:
                synthetic_days.add(day)
            else:
                days.add(day)
        first = self.first
        return {
            "days_measured": len(days - synthetic_days),
            "days_synthetic": len(synthetic_days),
            "first_hour": iso(self.at(first)) if first < len(self) else None,
        }


def build_series(rows: Iterable[Mapping], connectors: int, start: datetime, end: datetime,
                 history_start: datetime | None = None) -> StationSeries:
    """Série local ``[start, end)`` (horas locais ingênuas).

    ``rows``: linhas de :func:`aggregate.hourly_rows` (``hour_start`` em UTC) de todos os
    conectores do posto. Numa mesma ``(conector, hora)``, dado real vence o sintético.
    ``history_start``: primeira hora local com histórico; padrão = primeira linha.
    """
    connectors = max(1, int(connectors or 1))
    size = max(0, int((end - start).total_seconds() // 3600))
    chosen: dict[tuple[str, int], Mapping] = {}
    for row in rows:
        moment = parse_time(row.get("hour_start"))
        if moment is None:
            continue
        index = int((to_local(moment) - start).total_seconds() // 3600)
        if not 0 <= index < size:
            continue
        key = (str(row.get("connector_id")), index)
        previous = chosen.get(key)
        if previous is None or (previous.get("origin") == "synthetic" and row.get("origin") != "synthetic"):
            chosen[key] = row
    busy = [0.0] * size
    energy = [0.0] * size
    synthetic = [False] * size
    first = size
    for (_, index), row in chosen.items():
        busy[index] += float(row.get("busy_seconds") or 0)
        energy[index] += float(row.get("energy_wh") or 0) / 1000
        synthetic[index] |= row.get("origin") == "synthetic"
        first = min(first, index)
    # Horas ociosas no meio do histórico sintético não têm linha: o trecho inteiro é sintético,
    # salvo onde houver dado real.
    marked = [index for index, flag in enumerate(synthetic) if flag]
    if marked:
        real = {index for (_, index), row in chosen.items() if row.get("origin") != "synthetic"}
        for index in range(marked[0], marked[-1] + 1):
            synthetic[index] = index not in real
    if history_start is not None:
        first = min(first, max(0, int((history_start - start).total_seconds() // 3600)))
    occ: list[float | None] = [None] * size
    kwh: list[float | None] = [None] * size
    for index in range(first, size):
        occ[index] = min(1.0, busy[index] / (3600 * connectors))
        kwh[index] = energy[index]
    return StationSeries(start=start, occ=occ, kwh=kwh, connectors=connectors, synthetic=synthetic)
