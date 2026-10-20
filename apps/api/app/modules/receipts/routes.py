"""Recibo explicável da recarga e exportação do histórico do motorista (só o titular)."""

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response

from chargegrid_core import analytics
from chargegrid_core import receipt as receipts

from ...database import db_session
from ...errors import fail
from ...models import now
from ...security import current_user
from ..owner.service import Window
from . import service

router = APIRouter(tags=["receipts"])
NO_STORE = {"Cache-Control": "no-store"}
HISTORY_DAYS = 30


def _attachment(filename):
    return {**NO_STORE, "Content-Disposition": f'attachment; filename="{filename}"'}


def _stamp(moment):
    return moment.astimezone(analytics.REPORT_TZ).strftime("%Y%m%d-%H%M")


@router.get("/charging-sessions/{session_id}/receipt")
def receipt(session_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    payload = service.build(db, service.own_session(db, user, session_id))
    return JSONResponse(jsonable_encoder(payload), headers=NO_STORE)


@router.get("/charging-sessions/{session_id}/receipt.pdf")
def receipt_pdf(session_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    from ...reports import pdf  # ReportLab só nesta rota (cold start das demais)

    payload = service.build(db, service.own_session(db, user, session_id))
    return Response(pdf.receipt_pdf(payload), media_type="application/pdf",
                    headers=_attachment(f"chargegrid-recibo-{payload['number'].lower()}.pdf"))


def _window(start, end):
    end = end or now()
    start = start or end - timedelta(days=HISTORY_DAYS)
    try:
        analytics.validate_window(start, end)
    except ValueError as exc:
        fail("invalid_period", str(exc), 422)
    return Window(start, end)


@router.get("/me/charging-sessions/export.{fmt}")
def history_export(
    fmt: Literal["csv", "pdf"],
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    user=Depends(current_user),
    db=Depends(db_session),
):
    report = service.history_report(db, user, _window(start, end))
    filename = f"chargegrid-historico-{_stamp(now())}.{fmt}"
    if fmt == "csv":
        return Response(analytics.to_csv(report["items"], receipts.HISTORY_EXPORT_COLUMNS),
                        media_type="text/csv; charset=utf-8", headers=_attachment(filename))
    from ...reports import pdf

    return Response(pdf.history_pdf(report), media_type="application/pdf", headers=_attachment(filename))
