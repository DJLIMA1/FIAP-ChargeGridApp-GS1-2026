"""Indicadores do proprietário de postos (dashboard web, API e demo).

Funções puras e determinísticas: recebem registros já autorizados (dicionários
com os campos da API) ou agregados vindos do SQL e devolvem estruturas
serializáveis em JSON. Valores financeiros e de energia usam ``Decimal`` e são
expostos como strings, preservando precisão (mesma convenção da API).

Convenções (documentadas também em docs/api.md):

* Receita, energia e contagem de sessões consideram sessões encerradas
  (``completed``/``interrupted``) com energia positiva, atribuídas
  integralmente à data/hora de término (``ended_at``) — intervalo fechado no
  início e aberto no fim. Isso não equivale a consumo ocorrido na janela.
* Ocupação = minutos com sessão iniciada e ainda não encerrada (recortados na
  janela) / (pontos publicados × minutos da janela).
* Disponibilidade (uptime) é um retrato do momento: pontos publicados online /
  pontos publicados. Ainda não há histórico persistido de estados.
* Mapa de calor conta sessões pelo início (``started_at``; na ausência,
  ``created_at``) no fuso de São Paulo.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from . import overstay

try:  # tzdata pode faltar em builds embarcados; o Brasil não tem horário de verão desde 2019.
    from zoneinfo import ZoneInfo

    REPORT_TZ = ZoneInfo("America/Sao_Paulo")
except (ImportError, KeyError, ValueError):  # pragma: no cover - ZoneInfoNotFoundError é KeyError
    REPORT_TZ = timezone(timedelta(hours=-3), "BRT")

REPORT_TZ_NAME = "America/Sao_Paulo"
FINISHED_STATUSES = ("completed", "interrupted")
ACTIVE_STATUSES = ("starting", "charging", "stopping")
SESSION_STATUSES = ("starting", "charging", "stopping", "completed", "interrupted", "failed")
RESERVATION_STATUSES = ("pending_device", "confirmed", "cancelling", "cancelled", "expired", "consumed")
PERIOD_PRESETS = ("today", "7d", "30d", "custom")
GRANULARITIES = ("hour", "day")
METRICS = ("revenue", "energy_kwh", "sessions")
WEEKDAYS = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
MAX_WINDOW_DAYS = 366
MAX_HOURLY_DAYS = 31
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}

# Totem 0.8.0: canal e método da recarga paga, sempre no FIM das exportações do dono (o formato
# anterior continua igual coluna a coluna). Mesmos rótulos do painel web e do app do vendedor.
PAYMENT_CHANNEL_LABELS = {"app": "App", "kiosk_qr": "QR do painel", "kiosk_totem": "Totem"}
PAYMENT_EXPORT_COLUMNS = (("payment_channel", "Canal"), ("payment_method", "Pagamento"))
SESSION_EXPORT_COLUMNS = (
    ("id", "ID da sessão"),
    ("station_name", "Posto"),
    ("public_code", "Ponto"),
    ("status", "Status"),
    ("created_at", "Criada em"),
    ("started_at", "Início"),
    ("ended_at", "Fim"),
    ("duration_minutes", "Duração (min)"),
    ("energy_kwh", "Energia (kWh)"),
    ("price_per_kwh", "Tarifa (R$/kWh)"),
    ("discount_percent", "Desconto (%)"),
    ("cost_estimate", "Valor estimado (R$)"),
    ("source", "Origem da medição"),
    ("end_reason", "Motivo de término"),
    ("overstay_minutes", "Permanência cobrada (min)"),
    ("overstay_fee", "Taxa de permanência (R$)"),
    *PAYMENT_EXPORT_COLUMNS,
)
RESERVATION_EXPORT_COLUMNS = (
    ("id", "ID da reserva"),
    ("station_name", "Posto"),
    ("public_code", "Ponto"),
    ("status", "Status"),
    ("created_at", "Criada em"),
    ("expires_at", "Expira em"),
    ("no_show", "Não comparecimento"),
)
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


# ---------------------------------------------------------------- conversões

def parse_time(value) -> datetime | None:
    """ISO 8601 (aceita ``Z``) ou datetime → datetime com fuso; ``None`` se inválido."""
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


def to_decimal(value) -> Decimal:
    if value is None or value == "":
        return Decimal(0)
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)
    return number if number.is_finite() else Decimal(0)


def decimal_text(value, places: str = "0.01") -> str | None:
    """Decimal → string com casas fixas; ``None`` é preservado (sem dados)."""
    if value is None:
        return None
    return format(to_decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_UP), "f")


def local(value: datetime, tz=REPORT_TZ) -> datetime:
    return value.astimezone(tz)


# ------------------------------------------------------------------- períodos

def period_bounds(preset: str, now: datetime | None = None, *, start=None, end=None,
                  tz=REPORT_TZ) -> tuple[datetime, datetime]:
    """Janela [início, fim) em UTC para os atalhos do dashboard.

    ``today``/``7d``/``30d`` começam à meia-noite local e terminam agora; o
    período ``custom`` usa datas locais inclusivas (``end`` inclui o dia todo).
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today = now.astimezone(tz).date()
    if preset in ("today", "7d", "30d"):
        days = {"today": 0, "7d": 6, "30d": 29}[preset]
        first = datetime.combine(today - timedelta(days=days), time(), tz)
        return first.astimezone(timezone.utc), now
    if preset != "custom":
        raise ValueError("Período desconhecido")
    first_day, last_day = _as_date(start), _as_date(end)
    if first_day is None or last_day is None:
        raise ValueError("Informe as datas inicial e final")
    if last_day < first_day:
        raise ValueError("A data final deve ser posterior à inicial")
    if (last_day - first_day).days + 1 > MAX_WINDOW_DAYS:
        raise ValueError(f"Escolha até {MAX_WINDOW_DAYS} dias")
    begin = datetime.combine(first_day, time(), tz).astimezone(timezone.utc)
    finish = datetime.combine(last_day + timedelta(days=1), time(), tz).astimezone(timezone.utc)
    return begin, finish


def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def validate_window(start: datetime, end: datetime, granularity: str | None = None) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Informe datas com fuso horário")
    if end <= start:
        raise ValueError("O fim do período deve ser posterior ao início")
    if end - start > timedelta(days=MAX_WINDOW_DAYS):
        raise ValueError(f"Escolha um período de até {MAX_WINDOW_DAYS} dias")
    if granularity is not None and granularity not in GRANULARITIES:
        raise ValueError("Granularidade deve ser hour ou day")
    if granularity == "hour" and end - start > timedelta(days=MAX_HOURLY_DAYS):
        raise ValueError(f"Use granularidade diária para períodos acima de {MAX_HOURLY_DAYS} dias")


def suggested_granularity(start: datetime, end: datetime) -> str:
    return "hour" if end - start <= timedelta(days=2) else "day"


# ------------------------------------------------------------------- sessões

def is_eligible(session: Mapping, start: datetime, end: datetime) -> bool:
    """Sessão encerrada, com energia positiva e término dentro da janela."""
    ended = parse_time(session.get("ended_at"))
    return (session.get("status") in FINISHED_STATUSES and to_decimal(session.get("energy_wh")) > 0
            and ended is not None and start <= ended < end)


def overlap_minutes(first_start, first_end, second_start, second_end) -> Decimal:
    begin, finish = max(first_start, second_start), min(first_end, second_end)
    if finish <= begin:
        return Decimal(0)
    return Decimal(str((finish - begin).total_seconds())) / 60


def busy_minutes(session: Mapping, start: datetime, end: datetime, now: datetime) -> Decimal:
    began = parse_time(session.get("started_at"))
    if began is None:
        return Decimal(0)
    finished = parse_time(session.get("ended_at")) or now
    return overlap_minutes(began, finished, start, end)


def duration_minutes(session: Mapping, now: datetime | None = None) -> Decimal | None:
    began = parse_time(session.get("started_at"))
    if began is None:
        return None
    finished = parse_time(session.get("ended_at")) or now
    if finished is None:
        return None
    return max(Decimal(0), Decimal(str((finished - began).total_seconds())) / 60)


def average_ticket(revenue, sessions: int) -> Decimal | None:
    return to_decimal(revenue) / sessions if sessions else None


def occupancy_percent(minutes, points: int, start: datetime, end: datetime) -> Decimal | None:
    window = Decimal(str((end - start).total_seconds())) / 60
    if points <= 0 or window <= 0:
        return None
    return min(Decimal(100), to_decimal(minutes) * 100 / (window * points))


def uptime_percent(online: int, total: int) -> Decimal | None:
    return Decimal(online) * 100 / total if total else None


def summarize_sessions(sessions: Iterable[Mapping], start: datetime, end: datetime, now: datetime) -> dict:
    """Totais brutos a partir de registros (demo e testes; a API usa SQL)."""
    totals = {"revenue": Decimal(0), "energy_wh": Decimal(0), "sessions": 0, "busy_minutes": Decimal(0),
              "interrupted": 0, "failed": 0, "active_sessions": 0}
    for session in sessions:
        status = session.get("status")
        ended = parse_time(session.get("ended_at"))
        if is_eligible(session, start, end):
            totals["revenue"] += to_decimal(session.get("cost_estimate"))
            totals["energy_wh"] += to_decimal(session.get("energy_wh"))
            totals["sessions"] += 1
        if ended is not None and start <= ended < end:
            if status == "interrupted":
                totals["interrupted"] += 1
            elif status == "failed":
                totals["failed"] += 1
        if status in ACTIVE_STATUSES:
            totals["active_sessions"] += 1
        totals["busy_minutes"] += busy_minutes(session, start, end, now)
    return totals


def summarize_reservations(reservations: Iterable[Mapping], start: datetime, end: datetime) -> dict:
    total = no_shows = 0
    for reservation in reservations:
        created = parse_time(reservation.get("created_at"))
        if created is None or not start <= created < end:
            continue
        total += 1
        no_shows += reservation.get("status") == "expired"
    return {"reservations": total, "no_shows": no_shows}


def build_kpis(totals: Mapping, *, points: int, points_online: int, start: datetime, end: datetime) -> dict:
    """KPIs prontos para JSON (strings decimais; ``None`` = sem dados)."""
    sessions = int(totals.get("sessions") or 0)
    revenue = to_decimal(totals.get("revenue"))
    reservations = int(totals.get("reservations") or 0)
    no_shows = int(totals.get("no_shows") or 0)
    return {
        "revenue": decimal_text(revenue),
        "energy_wh": decimal_text(totals.get("energy_wh"), "0.001"),
        "energy_kwh": decimal_text(to_decimal(totals.get("energy_wh")) / 1000, "0.001"),
        "sessions": sessions,
        "average_ticket": decimal_text(average_ticket(revenue, sessions)),
        "occupancy_percent": decimal_text(occupancy_percent(totals.get("busy_minutes"), points, start, end), "0.1"),
        "uptime_percent": decimal_text(uptime_percent(points_online, points), "0.1"),
        "reservations": reservations,
        "no_shows": no_shows,
        "no_show_percent": decimal_text(Decimal(no_shows) * 100 / reservations if reservations else None, "0.1"),
        "interrupted_sessions": int(totals.get("interrupted") or 0),
        "failed_sessions": int(totals.get("failed") or 0),
        "active_sessions": int(totals.get("active_sessions") or 0),
        "points": points,
        "points_online": points_online,
    }


# ----------------------------------------------------------- séries temporais

def bucket_key(value: datetime, granularity: str, tz=REPORT_TZ) -> datetime:
    """Início do balde em horário local *ingênuo* (sem fuso)."""
    moment = value.astimezone(tz).replace(tzinfo=None) if value.tzinfo else value
    if granularity == "day":
        return moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return moment.replace(minute=0, second=0, microsecond=0)


def bucket_keys(start: datetime, end: datetime, granularity: str, tz=REPORT_TZ) -> list[datetime]:
    step = timedelta(days=1) if granularity == "day" else timedelta(hours=1)
    current, last = bucket_key(start, granularity, tz), bucket_key(end - timedelta(microseconds=1), granularity, tz)
    keys = []
    while current <= last:
        keys.append(current)
        current += step
    return keys


def series_payload(rows: Iterable, start: datetime, end: datetime, granularity: str, tz=REPORT_TZ) -> dict:
    """Preenche baldes vazios com zero.

    ``rows``: (balde local ingênuo ou datetime com fuso, receita, energia_wh, sessões).
    """
    totals: dict[datetime, list] = {}
    for bucket, revenue, energy_wh, count in rows:
        key = bucket_key(bucket, granularity, tz)
        entry = totals.setdefault(key, [Decimal(0), Decimal(0), 0])
        entry[0] += to_decimal(revenue)
        entry[1] += to_decimal(energy_wh)
        entry[2] += int(count or 0)
    keys = bucket_keys(start, end, granularity, tz)
    empty = [Decimal(0), Decimal(0), 0]
    return {
        "granularity": granularity,
        "timezone": REPORT_TZ_NAME,
        "basis": "ended_at",
        "buckets": [key.replace(tzinfo=tz).isoformat() for key in keys],
        "series": {
            "revenue": [decimal_text(totals.get(key, empty)[0]) for key in keys],
            "energy_kwh": [decimal_text(totals.get(key, empty)[1] / 1000, "0.001") for key in keys],
            "sessions": [totals.get(key, empty)[2] for key in keys],
        },
    }


def series_rows(sessions: Iterable[Mapping], start: datetime, end: datetime, granularity: str,
                tz=REPORT_TZ) -> list[tuple]:
    """Agrega registros elegíveis em tuplas aceitas por :func:`series_payload`."""
    return [(bucket_key(parse_time(s["ended_at"]), granularity, tz), s.get("cost_estimate"), s.get("energy_wh"), 1)
            for s in sessions if is_eligible(s, start, end)]


# ------------------------------------------------------------- mapa de calor

def heatmap_payload(cells: Iterable[tuple]) -> dict:
    """``cells``: (dia da semana 0=segunda, hora 0-23, quantidade)."""
    matrix = [[0] * 24 for _ in WEEKDAYS]
    for weekday, hour, count in cells:
        weekday, hour = int(weekday), int(hour)
        if 0 <= weekday < 7 and 0 <= hour < 24:
            matrix[weekday][hour] += int(count or 0)
    return {"timezone": REPORT_TZ_NAME, "basis": "started_at", "days": list(WEEKDAYS),
            "hours": list(range(24)), "cells": matrix, "max": max(max(row) for row in matrix)}


def heatmap_cells(sessions: Iterable[Mapping], start: datetime, end: datetime, tz=REPORT_TZ) -> list[tuple]:
    cells = []
    for session in sessions:
        moment = parse_time(session.get("started_at")) or parse_time(session.get("created_at"))
        if moment is None or not start <= moment < end:
            continue
        moment = moment.astimezone(tz)
        cells.append((moment.weekday(), moment.hour, 1))
    return cells


def peak_hours(heatmap: Mapping, top: int = 3) -> list[dict]:
    """Horários com mais sessões, somando todos os dias da semana."""
    totals = [sum(row[hour] for row in heatmap["cells"]) for hour in range(24)]
    ranked = sorted((hour for hour in range(24) if totals[hour]), key=lambda h: (-totals[h], h))
    return [{"hour": hour, "sessions": totals[hour]} for hour in ranked[:top]]


# ------------------------------------------------------------------- ranking

def ranking_payload(rows: Iterable[Mapping], start: datetime, end: datetime, limit: int | None = None) -> list[dict]:
    """Linhas por ponto com ``revenue``, ``energy_wh``, ``sessions`` e ``busy_minutes``."""
    result = []
    for row in rows:
        result.append({
            "connector_id": str(row["connector_id"]),
            "station_id": str(row["station_id"]),
            "station_name": row.get("station_name") or "",
            "public_code": row.get("public_code") or "",
            "revenue": decimal_text(row.get("revenue")),
            "energy_kwh": decimal_text(to_decimal(row.get("energy_wh")) / 1000, "0.001"),
            "sessions": int(row.get("sessions") or 0),
            "occupancy_percent": decimal_text(occupancy_percent(row.get("busy_minutes"), 1, start, end), "0.1"),
        })
    result.sort(key=lambda item: (-to_decimal(item["revenue"]), -item["sessions"], item["public_code"]))
    return result[:limit] if limit else result


def ranking_rows(sessions: Iterable[Mapping], points: Iterable[Mapping], start: datetime, end: datetime,
                 now: datetime) -> list[dict]:
    rows = {str(p["connector_id"]): {**p, "revenue": Decimal(0), "energy_wh": Decimal(0), "sessions": 0,
                                     "busy_minutes": Decimal(0)} for p in points}
    for session in sessions:
        row = rows.get(str(session.get("connector_id")))
        if row is None:
            continue
        if is_eligible(session, start, end):
            row["revenue"] += to_decimal(session.get("cost_estimate"))
            row["energy_wh"] += to_decimal(session.get("energy_wh"))
            row["sessions"] += 1
        row["busy_minutes"] += busy_minutes(session, start, end, now)
    return list(rows.values())


# -------------------------------------------------------------------- alertas

def build_alerts(points: Iterable[Mapping], now: datetime, *, idle_hours: int = 72) -> list[dict]:
    """Classifica alertas operacionais por ponto.

    Campos esperados: ``connector_id``, ``station_id``, ``station_name``,
    ``public_code``, ``published`` (ponto e posto ativos), ``has_device``,
    ``online``, ``last_seen``, ``physical_state``, ``failed_commands``,
    ``last_session_at``, ``created_reference`` (opcional), ``retired`` e, opcionais,
    ``charger_offline``/``charger_address`` (central da estação online, carregador GoodWe sem resposta:
    só este ponto; ``online`` aqui é o da central).
    """
    alerts = []
    for point in points:
        if point.get("retired"):
            continue
        base = {"connector_id": str(point["connector_id"]), "station_id": str(point["station_id"]),
                "station_name": point.get("station_name") or "", "public_code": point.get("public_code") or ""}
        label = f"{base['public_code']} · {base['station_name']}".strip(" ·")
        published = bool(point.get("published"))
        last_seen = parse_time(point.get("last_seen"))
        if published and not point.get("has_device"):
            alerts.append({**base, "kind": "no_device", "severity": "warning",
                           "title": "Ponto publicado sem dispositivo",
                           "detail": f"{label}: provisione um dispositivo para receber recargas.", "at": None})
        elif published and not point.get("online"):
            seen = last_seen.astimezone(REPORT_TZ).strftime("%d/%m %H:%M") if last_seen else "nunca"
            alerts.append({**base, "kind": "device_offline", "severity": "critical",
                           "title": "Dispositivo offline",
                           "detail": f"{label}: sem comunicação. Último contato: {seen}.",
                           "at": last_seen.isoformat() if last_seen else None})
        elif published and point.get("charger_offline"):
            address = point.get("charger_address")
            alerts.append({**base, "kind": "charger_offline", "severity": "critical",
                           "title": "Carregador offline",
                           "detail": f"{label}: a central da estação está online, mas o carregador"
                                     f"{f' {address}' if address else ''} não responde. Só este ponto fica indisponível.",
                           "at": None})
        if point.get("physical_state") == "fault":
            alerts.append({**base, "kind": "device_fault", "severity": "critical", "title": "Falha no equipamento",
                           "detail": f"{label}: o painel informou falha.", "at": None})
        failed = int(point.get("failed_commands") or 0)
        if failed:
            alerts.append({**base, "kind": "command_failed", "severity": "warning",
                           "title": "Falhas de comando",
                           "detail": f"{label}: {failed} comando(s) sem confirmação nas últimas 24 h.", "at": None})
        last_session = parse_time(point.get("last_session_at"))
        reference = last_session or parse_time(point.get("created_reference"))
        if published and point.get("online") and (reference is None or now - reference >= timedelta(hours=idle_hours)):
            since = last_session.astimezone(REPORT_TZ).strftime("%d/%m") if last_session else None
            alerts.append({**base, "kind": "point_idle", "severity": "info", "title": "Ponto parado",
                           "detail": f"{label}: nenhuma recarga desde {since}." if since else
                           f"{label}: ainda sem recargas registradas.",
                           "at": last_session.isoformat() if last_session else None})
    alerts.sort(key=lambda alert: (SEVERITY_ORDER[alert["severity"]], alert["station_name"], alert["public_code"]))
    return alerts


# ---------------------------------------------------------------- exportação

def payment_export_fields(payment: Mapping | None) -> dict:
    """``payment_channel``/``payment_method`` de uma recarga para CSV/PDF do dono.

    ``payment``: ``{"channel", "provider", "method"}`` do pré-pagamento (``channel`` como em
    ``/owner/sessions``: ``app`` | ``kiosk_qr`` | ``kiosk_totem``) ou ``None`` sem pré-pagamento
    (recarga do app sem pagamento antecipado: canal "App", método vazio). Simulado = totem com a
    conta do dono em Modo apresentação; o resto é Stripe em modo teste.
    """
    if not payment:
        return {"payment_channel": PAYMENT_CHANNEL_LABELS["app"], "payment_method": ""}
    channel = payment.get("channel") or "app"
    simulated = payment.get("provider") == "simulated" or payment.get("method") == "simulated"
    return {"payment_channel": PAYMENT_CHANNEL_LABELS.get(channel, channel),
            "payment_method": "Simulado" if simulated else "Stripe (teste)"}


def session_export_row(session: Mapping, now: datetime | None = None) -> dict:
    """Projeção mínima para relatórios: sem identidade do cliente."""
    point = session.get("connector") or {}
    duration = duration_minutes(session, now if session.get("status") in ACTIVE_STATUSES else None)
    return {
        "id": str(session.get("id") or ""),
        "station_id": str(session.get("station_id") or ""),
        "station_name": session.get("station_name") or "",
        "connector_id": str(session.get("connector_id") or point.get("id") or ""),
        "public_code": session.get("public_code") or point.get("public_code") or "",
        "status": session.get("status") or "",
        "created_at": _iso(session.get("created_at")),
        "started_at": _iso(session.get("started_at")),
        "ended_at": _iso(session.get("ended_at")),
        "duration_minutes": decimal_text(duration, "0.1"),
        "energy_kwh": decimal_text(to_decimal(session.get("energy_wh")) / 1000, "0.001"),
        "price_per_kwh": decimal_text(session.get("price_per_kwh"), "0.0001"),
        "discount_percent": int(session.get("discount_percent") or 0),
        "cost_estimate": decimal_text(session.get("cost_estimate"), "0.0001"),
        "source": session.get("source") or "",
        "end_reason": session.get("end_reason") or "",
        # Permanência após a recarga (chargegrid_core.overstay): minutos cobrados e taxa.
        "overstay_minutes": overstay.billable_minutes(overstay.clean_terms(session.get("overstay_terms")),
                                                      session.get("overstay_billable_seconds") or 0),
        "overstay_fee": decimal_text(session.get("overstay_fee") or 0, "0.01"),
    }


def reservation_export_row(reservation: Mapping) -> dict:
    point = reservation.get("connector") or {}
    return {
        "id": str(reservation.get("id") or ""),
        "station_id": str(reservation.get("station_id") or ""),
        "station_name": reservation.get("station_name") or "",
        "connector_id": str(reservation.get("connector_id") or point.get("id") or ""),
        "public_code": reservation.get("public_code") or point.get("public_code") or "",
        "status": reservation.get("status") or "",
        "created_at": _iso(reservation.get("created_at")),
        "expires_at": _iso(reservation.get("expires_at")),
        "no_show": reservation.get("status") == "expired",
    }


def _iso(value) -> str | None:
    parsed = parse_time(value)
    return parsed.isoformat() if parsed else None


def csv_cell(value) -> str:
    """Neutraliza fórmulas (CSV injection) sem alterar números legítimos."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "sim" if value else "não"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        try:
            Decimal(text)
        except InvalidOperation:
            return "'" + text
    return text


def to_csv(rows: Iterable[Mapping], columns=SESSION_EXPORT_COLUMNS) -> str:
    """CSV RFC 4180 (vírgula, decimal com ponto, UTF-8) com cabeçalho em português."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([header for _, header in columns])
    for row in rows:
        writer.writerow([csv_cell(row.get(key)) for key, _ in columns])
    return buffer.getvalue()


def export_envelope(rows: list, *, dataset: str, filters: Mapping, generated_at: datetime) -> dict:
    return {
        "schema_version": 1,
        "dataset": dataset,
        "generated_at": generated_at.isoformat(),
        "timezone": REPORT_TZ_NAME,
        "currency": "BRL",
        "units": {"energy": "kWh", "duration": "min"},
        "filters": {key: value for key, value in filters.items() if value not in (None, "")},
        "total": len(rows),
        "notes": "Valores estimados; energia pode ser simulada, medida ou estimada (coluna source).",
        "items": rows,
    }
