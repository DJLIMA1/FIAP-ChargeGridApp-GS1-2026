"""Endpoints do totem (prefixo /v1), só com ``Authorization: Device <chave>``; ver ``service``."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from ...database import db_session
from ...security import current_device
from ..auth.routes import limit
from ..devices.service import charger_device
from . import account, service
from .schemas import KioskOrderInput, KioskPayInput, KioskQuoteInput

router = APIRouter(tags=["kiosk"])


def kiosk_device(x_kiosk_charger_address: int | None = Header(default=None, ge=1, le=247),
                 device=Depends(current_device), db=Depends(db_session)):
    return charger_device(db, device, x_kiosk_charger_address) if x_kiosk_charger_address is not None else device


def _limit(db, device, name, maximum, seconds=60):
    limit(db, f"kiosk-{name}:{device.id}", maximum=maximum, seconds=seconds)


@router.get("/devices/kiosk/offer")
def offer(device=Depends(kiosk_device), db=Depends(db_session), user=Depends(account.kiosk_user)):
    _limit(db, device, "offer", 30)
    return service.offer(db, device, user)


@router.post("/devices/kiosk/quote")
def quote(data: KioskQuoteInput, device=Depends(kiosk_device), db=Depends(db_session),
          user=Depends(account.kiosk_user)):
    _limit(db, device, "quote", 30)
    return service.quote(db, device, data, user)


@router.post("/devices/kiosk/orders", status_code=201)
def create_order(data: KioskOrderInput, request: Request, idempotency_key: str = Header(default=""),
                 device=Depends(kiosk_device), db=Depends(db_session), user=Depends(account.kiosk_user)):
    _limit(db, device, "orders", 6, 300)
    order = service.create_order(db, device, data, idempotency_key, user)
    return service.order_view(db, order, str(request.base_url))


@router.post("/devices/kiosk/orders/{order_id}/pay")
def pay(order_id: UUID, request: Request, data: KioskPayInput | None = None, idempotency_key: str = Header(default=""),
        device=Depends(kiosk_device), db=Depends(db_session), user=Depends(account.kiosk_user)):
    _limit(db, device, "pay", 10, 300)
    order = service.pay(db, device, order_id, data or KioskPayInput(), idempotency_key, str(request.base_url), user)
    return service.order_view(db, order, str(request.base_url))


@router.post("/devices/kiosk/orders/{order_id}/cancel")
def cancel(order_id: UUID, request: Request, device=Depends(kiosk_device), db=Depends(db_session)):
    _limit(db, device, "cancel", 20, 300)
    return service.order_view(db, service.cancel(db, device, order_id), str(request.base_url))


@router.get("/devices/kiosk/orders/{order_id}")
def get_order(order_id: UUID, request: Request, device=Depends(kiosk_device), db=Depends(db_session)):
    _limit(db, device, "order", 120)
    return service.order_view(db, service.get_order(db, device, order_id), str(request.base_url))
