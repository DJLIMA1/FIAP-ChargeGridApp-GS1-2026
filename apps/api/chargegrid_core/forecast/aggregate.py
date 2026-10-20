"""Agregados horários duráveis por conector (ocupação e energia).

Função pura: recebe sessões e amostras de telemetria (dicionários) e devolve uma
linha por ``(conector, hora UTC)`` com atividade. É a mesma usada pela API
(rollup diário e horas recentes), pelo gerador sintético e pela conta demo.

Regras
------
* **Ocupação** vem das sessões: ``[started_at, ended_at)`` (sessão ativa: até
  ``now``), recortada em horas. Sessões são o registro durável; nunca somem.
* **Energia** vem das diferenças entre leituras de telemetria da mesma sessão
  (``energy_wh`` é cumulativo): ``ΔWh = Wh_atual − Wh_anterior``, nunca a soma dos
  cumulativos. Regressão (reboot/reset) não gera energia negativa: a leitura vira a
  nova referência. O trecho entre o início e a primeira leitura e entre a última
  leitura e o fim fecham o total da sessão, então a soma por hora é igual ao
  ``energy_wh`` final. Um delta que cruza a virada da hora é dividido pelo tempo
  (estimativa declarada em ``energy_basis``).
* Sem telemetria (apagada após 7 dias ou nunca enviada), a energia da sessão é
  espalhada uniformemente no seu intervalo (``energy_basis = "session_spread"``).
* ``origin``: ``measured`` só quando todas as sessões da hora são medidas; caso
  contrário ``simulated`` (bancada). O gerador sintético força ``synthetic``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

HOUR = timedelta(hours=1)
WH = Decimal("0.001")
ORIGINS = ("measured", "simulated", "synthetic")
BASES = ("telemetry", "session_spread", "synthetic")


def parse_time(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _dec(value) -> Decimal:
    if value is None or value == "":
        return Decimal(0)
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)
    return number if number.is_finite() and number > 0 else Decimal(0)


def floor_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def _pieces(begin: datetime, end: datetime, start: datetime, finish: datetime):
    """Trechos ``(hora, segundos)`` de ``[begin, end)`` recortados em ``[start, finish)``."""
    begin, end = max(begin, start), min(end, finish)
    current = floor_hour(begin)
    while current < end:
        nxt = current + HOUR
        seconds = (min(end, nxt) - max(begin, current)).total_seconds()
        if seconds > 0:
            yield current, seconds
        current = nxt


def _spread(energy: Decimal, begin: datetime, end: datetime, start: datetime, finish: datetime):
    """Divide ``energy`` em ``[begin, end)`` pelo tempo; devolve ``{hora: Wh}`` dentro da janela.

    O arredondamento (0,001 Wh) fecha no último trecho, conservando o total do intervalo.
    """
    if energy <= 0:
        return {}
    if end <= begin:
        hour = floor_hour(begin)
        return {hour: energy} if start <= hour < finish else {}
    total = Decimal(str((end - begin).total_seconds()))
    parts, used = {}, Decimal(0)
    pieces = list(_pieces(begin, end, begin, end))
    for index, (hour, seconds) in enumerate(pieces):
        if index == len(pieces) - 1:
            share = energy - used
        else:
            share = (energy * Decimal(str(seconds)) / total).quantize(WH, rounding=ROUND_HALF_UP)
            used += share
        if start <= hour < finish:
            parts[hour] = parts.get(hour, Decimal(0)) + share
    return parts


def session_energy(session: Mapping, samples: list[Mapping], now: datetime):
    """``(trechos [(início, fim, Wh)], base)`` da energia de uma sessão."""
    began = parse_time(session.get("started_at"))
    if began is None:
        return [], "session_spread"
    finished = (parse_time(session.get("ended_at")) or parse_time(session.get("last_measurement_at")) or now)
    total = _dec(session.get("energy_wh"))
    readings = sorted(((parse_time(s.get("captured_at")), _dec(s.get("energy_wh"))) for s in samples
                       if parse_time(s.get("captured_at")) is not None), key=lambda item: item[0])
    readings = [(moment, wh) for moment, wh in readings if began <= moment <= max(finished, began)]
    if not readings:
        return ([(began, max(finished, began), total)] if total > 0 else []), "session_spread"
    segments, previous_time, previous_wh = [], began, Decimal(0)
    for moment, wh in readings:
        if wh >= previous_wh:
            if wh > previous_wh:
                segments.append((previous_time, moment, wh - previous_wh))
        # Regressão (reboot/reset do contador): a leitura vira a nova referência.
        previous_time, previous_wh = moment, wh
    counted = sum((delta for _, _, delta in segments), Decimal(0))
    tail = total - counted
    if tail > 0:
        segments.append((previous_time, max(finished, previous_time), tail))
    return segments, "telemetry"


def hourly_rows(sessions: Iterable[Mapping], samples: Iterable[Mapping], start: datetime, end: datetime,
                now: datetime, *, origin: str | None = None) -> list[dict]:
    """Linhas ``{connector_id, hour_start, origin, busy_seconds, energy_wh, energy_basis,
    sessions_started, max_power_w}`` para as horas UTC em ``[start, end)``.

    ``start``/``end`` devem estar alinhados à hora; quem chama passa apenas horas fechadas.
    ``samples`` precisam de ``session_id``; sessões de ``id``.
    """
    start, end = floor_hour(start.astimezone(timezone.utc)), floor_hour(end.astimezone(timezone.utc))
    by_session: dict[str, list[Mapping]] = {}
    power: dict[tuple[str, datetime], Decimal] = {}
    session_connector = {}
    sessions = list(sessions)
    for session in sessions:
        session_connector[str(session.get("id"))] = str(session.get("connector_id"))
    for sample in samples:
        sid = str(sample.get("session_id"))
        by_session.setdefault(sid, []).append(sample)
        moment, watts = parse_time(sample.get("captured_at")), sample.get("power_w")
        connector = session_connector.get(sid)
        if moment is not None and watts is not None and connector is not None and start <= floor_hour(moment) < end:
            key = (connector, floor_hour(moment))
            power[key] = max(power.get(key, Decimal(0)), _dec(watts))
    cells: dict[tuple[str, datetime], dict] = {}

    def cell(connector, hour):
        return cells.setdefault((connector, hour), {
            "busy": 0.0, "energy": Decimal(0), "started": 0, "spread": False, "tele": False, "simulated": False})

    for session in sessions:
        began = parse_time(session.get("started_at"))
        if began is None:
            continue
        connector = str(session.get("connector_id"))
        finished = parse_time(session.get("ended_at")) or now
        simulated = (session.get("source") or "simulated") != "measured"
        if start <= floor_hour(began) < end:
            entry = cell(connector, floor_hour(began))
            entry["started"] += 1
            entry["simulated"] |= simulated
        for hour, seconds in _pieces(began, max(finished, began), start, end):
            entry = cell(connector, hour)
            entry["busy"] += seconds
            entry["simulated"] |= simulated
        segments, basis = session_energy(session, by_session.get(str(session.get("id")), []), now)
        for seg_begin, seg_end, wh in segments:
            for hour, share in _spread(wh, seg_begin, seg_end, start, end).items():
                entry = cell(connector, hour)
                entry["energy"] += share
                entry["spread"] |= basis == "session_spread"
                entry["tele"] |= basis == "telemetry"
                entry["simulated"] |= simulated
    rows = []
    for (connector, hour), entry in sorted(cells.items(), key=lambda item: (item[0][1], item[0][0])):
        kind = origin or ("simulated" if entry["simulated"] else "measured")
        rows.append({
            "connector_id": connector,
            "hour_start": hour,
            "origin": kind,
            "busy_seconds": min(3600, int(round(entry["busy"]))),
            "energy_wh": entry["energy"].quantize(WH, rounding=ROUND_HALF_UP),
            "energy_basis": "synthetic" if kind == "synthetic" else (
                "telemetry" if entry["tele"] and not entry["spread"] else "session_spread"),
            "sessions_started": entry["started"],
            "max_power_w": power.get((connector, hour)),
        })
    return rows
