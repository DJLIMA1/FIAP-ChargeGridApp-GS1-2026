"""Endpoints agregados do dashboard web do proprietário (somente leitura).

Ações de gestão (tarifa, publicação, cupons, dispositivos) continuam nos
endpoints existentes de stations/connectors/coupons/devices.
"""

import json
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from chargegrid_core import analytics

from ...database import db_session
from ...errors import fail
from ...models import now
from ...security import current_user
from ...service import operator, owned
from . import service

router = APIRouter(prefix="/owner", tags=["owner"])
DEFAULT_DAYS = 7
NO_STORE = {"Cache-Control": "no-store"}


def scope_for(db, user, station_id):
    operator(user)
    if station_id is not None:
        owned(db, user, station_id)
    return service.Scope(owner_id=user.id, station_id=station_id)


def window_for(start, end, granularity=None):
    end = end or now()
    start = start or end - timedelta(days=DEFAULT_DAYS)
    try:
        analytics.validate_window(start, end, granularity)
    except ValueError as exc:
        fail("invalid_period", str(exc), 422)
    return service.Window(start, end)


def statuses(value, allowed):
    if not value:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    invalid = [item for item in items if item not in allowed]
    if invalid:
        fail("invalid_status", "Status inválido: " + ", ".join(invalid), 422)
    return items


@router.get("/overview")
def overview(
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    station_id: UUID | None = None,
    user=Depends(current_user),
    db=Depends(db_session),
):
    scope = scope_for(db, user, station_id)
    return service.overview(db, scope, window_for(start, end))


@router.get("/timeseries")
def timeseries(
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    station_id: UUID | None = None,
    metric: Literal["all", "revenue", "energy_kwh", "sessions"] = "all",
    granularity: Literal["hour", "day"] = "day",
    user=Depends(current_user),
    db=Depends(db_session),
):
    scope = scope_for(db, user, station_id)
    payload = service.timeseries(db, scope, window_for(start, end, granularity), granularity)
    if metric != "all":
        payload["series"] = {metric: payload["series"][metric]}
    return payload


@router.get("/heatmap")
def heatmap(
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    station_id: UUID | None = None,
    user=Depends(current_user),
    db=Depends(db_session),
):
    scope = scope_for(db, user, station_id)
    return service.heatmap(db, scope, window_for(start, end))


@router.get("/sessions")
def sessions(
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    station_id: UUID | None = None,
    status: str | None = Query(None, max_length=200),
    q: str | None = Query(None, max_length=100),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(current_user),
    db=Depends(db_session),
):
    scope = scope_for(db, user, station_id)
    query = service.session_query(scope, window_for(start, end), statuses(status, analytics.SESSION_STATUSES), q)
    moment = now()
    return service.paginate(db, query, lambda row: service.session_item(row, moment), limit, offset)


@router.get("/reservations")
def reservations(
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    station_id: UUID | None = None,
    status: str | None = Query(None, max_length=200),
    q: str | None = Query(None, max_length=100),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(current_user),
    db=Depends(db_session),
):
    scope = scope_for(db, user, station_id)
    query = service.reservation_query(
        scope, window_for(start, end), statuses(status, analytics.RESERVATION_STATUSES), q
    )
    return service.paginate(db, query, service.reservation_item, limit, offset)


@router.get("/alerts")
def alerts(station_id: UUID | None = None, user=Depends(current_user), db=Depends(db_session)):
    return service.alerts(db, scope_for(db, user, station_id))


@router.get("/live")
def live(station_id: UUID | None = None, user=Depends(current_user), db=Depends(db_session)):
    return service.live(db, scope_for(db, user, station_id))


DATASETS = {
    "sessions": (service.session_query, analytics.SESSION_STATUSES, analytics.SESSION_EXPORT_COLUMNS),
    "reservations": (service.reservation_query, analytics.RESERVATION_STATUSES,
                     analytics.RESERVATION_EXPORT_COLUMNS),
}


def export(db, user, dataset, fmt, start, end, station_id, status, q):
    build_query, allowed, columns = DATASETS[dataset]
    scope = scope_for(db, user, station_id)
    window = window_for(start, end)
    query = build_query(scope, window, statuses(status, allowed), q)
    rows = db.execute(query.limit(service.EXPORT_LIMIT + 1)).mappings().all()
    if len(rows) > service.EXPORT_LIMIT:
        fail("export_too_large", f"Mais de {service.EXPORT_LIMIT} registros. Reduza o período ou use filtros.", 413)
    moment = now()
    items = [service.session_item(row, moment) if dataset == "sessions" else service.reservation_item(row)
             for row in rows]
    stamp = moment.astimezone(analytics.REPORT_TZ).strftime("%Y%m%d-%H%M")
    filename = f"chargegrid-{'sessoes' if dataset == 'sessions' else 'reservas'}-{stamp}.{fmt}"
    headers = {**NO_STORE, "Content-Disposition": f'attachment; filename="{filename}"'}
    if fmt == "csv":
        return Response(analytics.to_csv(items, columns), media_type="text/csv; charset=utf-8", headers=headers)
    filters = {"from": window.start.isoformat(), "to": window.end.isoformat(),
               "station_id": str(station_id) if station_id else None, "status": status, "q": q}
    envelope = analytics.export_envelope(items, dataset=dataset, filters=filters, generated_at=moment)
    return Response(json.dumps(envelope, ensure_ascii=False), media_type="application/json", headers=headers)


def _export_route(dataset, fmt):
    def endpoint(
        start: datetime | None = Query(None, alias="from"),
        end: datetime | None = Query(None, alias="to"),
        station_id: UUID | None = None,
        status: str | None = Query(None, max_length=200),
        q: str | None = Query(None, max_length=100),
        user=Depends(current_user),
        db=Depends(db_session),
    ):
        return export(db, user, dataset, fmt, start, end, station_id, status, q)

    endpoint.__name__ = f"export_{dataset}_{fmt}"
    router.add_api_route(f"/export/{dataset}.{fmt}", endpoint, methods=["GET"], name=endpoint.__name__)


for _dataset in DATASETS:
    for _fmt in ("csv", "json"):
        _export_route(_dataset, _fmt)
