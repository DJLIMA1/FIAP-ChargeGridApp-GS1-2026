"""Resultado do dono: configuração do posto (custo do kWh) e margem por sessão/período.

Tela (``/owner/margin``), CSV e PDF usam a mesma agregação (``service.margin_report``).
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse, Response

from chargegrid_core import analytics, economics
from chargegrid_core import rent as rent_rules

from ...database import db_session
from ...models import now
from ...security import current_user
from ...service import owned
from ..owner.routes import scope_for, window_for
from . import service

router = APIRouter(tags=["economics"])
NO_STORE = {"Cache-Control": "no-store"}


@router.get("/stations/{station_id}/economics")
def get_economics(station_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    return JSONResponse(service.station_economics(owned(db, user, station_id), db=db), headers=NO_STORE)


@router.put("/stations/{station_id}/economics")
def put_economics(station_id: UUID, body: dict = Body(...), user=Depends(current_user), db=Depends(db_session)):
    station = owned(db, user, station_id)
    service.update_station_economics(station, body)
    db.flush()
    return JSONResponse(service.station_economics(station, db=db), headers=NO_STORE)


@router.get("/owner/margin")
def margin(
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    station_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user=Depends(current_user),
    db=Depends(db_session),
):
    report = service.margin_report(db, scope_for(db, user, station_id), window_for(start, end))
    report.update(items=report["items"][offset:offset + limit], limit=limit, offset=offset)
    return JSONResponse(economics.serialize(report), headers=NO_STORE)


@router.get("/owner/export/central-rent.csv")
def central_rent_export(
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    station_id: UUID | None = None,
    user=Depends(current_user),
    db=Depends(db_session),
):
    """Aluguel das centrais do período: uma linha por central, mês e valor mensal."""
    rent = service.central_rent(db, scope_for(db, user, station_id), window_for(start, end))
    stamp = now().astimezone(analytics.REPORT_TZ).strftime("%Y%m%d-%H%M")
    headers = {**NO_STORE, "Content-Disposition": f'attachment; filename="chargegrid-aluguel-centrais-{stamp}.csv"'}
    return Response(rent_rules.rent_csv(rent["lines"]), media_type="text/csv; charset=utf-8", headers=headers)


@router.get("/owner/export/margin.{fmt}")
def margin_export(
    fmt: Literal["csv", "pdf"],
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    station_id: UUID | None = None,
    user=Depends(current_user),
    db=Depends(db_session),
):
    scope = scope_for(db, user, station_id)
    report = service.margin_report(db, scope, window_for(start, end))
    stamp = now().astimezone(analytics.REPORT_TZ).strftime("%Y%m%d-%H%M")
    headers = {**NO_STORE, "Content-Disposition": f'attachment; filename="chargegrid-resultado-{stamp}.{fmt}"'}
    if fmt == "csv":
        return Response(economics.margin_csv(report["items"]), media_type="text/csv; charset=utf-8", headers=headers)
    from ...reports import pdf  # ReportLab só nesta rota (cold start das demais)

    name = next((item["station_name"] for item in report["stations"] if station_id and
                 item["station_id"] == str(station_id)), None)
    return Response(pdf.margin_pdf(economics.serialize(report), name), media_type="application/pdf",
                    headers=headers)
