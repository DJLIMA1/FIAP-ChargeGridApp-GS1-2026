"""Rotas de pagamento (prefixo /v1). Stripe em MODO TESTE; ver ``service``."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from starlette.concurrency import run_in_threadpool

from ...database import db_session
from ...security import current_user
from ..auth.routes import limit
from . import service
from .funding import payment_row
from .schemas import PaymentInput

router = APIRouter()


@router.get("/payments/config")
def payments_config(user=Depends(current_user)):
    return service.config()


@router.post("/payments", status_code=201)
def create_payment(
    data: PaymentInput,
    request: Request,
    idempotency_key: str = Header(default=""),
    user=Depends(current_user),
    db=Depends(db_session),
):
    limit(db, f"payments:{user.id}", maximum=10, seconds=300)
    return payment_row(service.create_payment(db, user, data, idempotency_key, str(request.base_url)))


@router.get("/payments/current")
def current_payment(user=Depends(current_user), db=Depends(db_session)):
    payment = service.current_payment(db, user)
    return payment_row(payment) if payment else None


@router.get("/payments/{payment_id}")
def get_payment(payment_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    service.owned_payment(db, user, payment_id)
    return payment_row(service.advance(db, payment_id))


@router.post("/payments/{payment_id}/cancel")
def cancel_payment(payment_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    return payment_row(service.cancel_payment(db, user, payment_id))


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(default=""), db=Depends(db_session)):
    payload = await request.body()
    return await run_in_threadpool(service.handle_webhook, db, payload, stripe_signature)
