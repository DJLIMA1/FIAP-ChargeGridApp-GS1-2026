"""Páginas HTML de pagamento (fora de /v1, como /auth/confirmed). Stripe em MODO TESTE.

* ``/pay/k/{public_code}?c=12345`` — QR do painel físico: quem chega sem o app escolhe um valor
  (R$ 10/20/40) e paga na Checkout hospedada. O código ``c`` é o #F atual do painel (presença).
* ``/pay/s/{id}?t=...`` — status do pagamento do painel (link com token): aguardando, pago,
  recarga em andamento (com "Encerrar"), valor cobrado e devolvido.
* ``/pay/return?p=...`` — retorno da Checkout aberta pelo app: só informa; quem confirma é o
  servidor (webhook ou verificação na Stripe), nunca o redirecionamento.
* Totem (pedido sem celular, ``modules/kiosk_totem``): ``/pay/o/{pedido}?t=...`` (QR do pedido →
  Checkout) e ``/pay/r/{pedido}?t=...`` (status e recibo do visitante; ``.pdf`` para o PDF).
"""

from decimal import Decimal
from html import escape
from urllib.parse import parse_qs, quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from chargegrid_core import billing, pricing

from ...database import db_session
from ...models import ChargingSession, Connector, KioskOrder, Payment, Station
from ..kiosk_totem import service as totem
from ..pricing.service import current_terms
from ..receipts import service as receipts
from . import service
from .funding import FUNDED, PRE_START, status_label

router = APIRouter(include_in_schema=False)

HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
                               "form-action 'self' https://checkout.stripe.com; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
STYLE = """
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#121315;color:#F2F2F2;
font:16px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}main{max-width:440px;margin:0 auto;padding:24px 16px}
.brand{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}.brand b{font-size:20px}
.tag{background:#E8922B;color:#1B1306;border-radius:999px;padding:3px 10px;font-size:12px;font-weight:700;letter-spacing:.5px}
.card{background:#1E2023;border:1px solid #2C2F33;border-radius:16px;padding:18px;margin:14px 0}
h1{font-size:24px;margin:4px 0 6px}.muted{color:#A7ABB1;font-size:14px}.row{display:flex;justify-content:space-between;margin:6px 0}
.amounts{display:grid;gap:10px;margin-top:12px}button,.btn{display:block;width:100%;border:0;border-radius:12px;padding:15px;
font-size:17px;font-weight:700;text-align:center;text-decoration:none;cursor:pointer;background:#3EBF80;color:#08130D}
.secondary{background:#2C2F33;color:#F2F2F2}.danger{background:#D64545;color:#fff}.big{font-size:30px;font-weight:800}
.notice{border-left:3px solid #E8922B;padding:8px 12px;background:#1B1712;border-radius:8px;font-size:14px;color:#E9D9C2}
"""


TEST_FOOTER = "Pagamento processado pela Stripe em modo de teste: nenhum valor real é cobrado."
SIMULATED_FOOTER = "Pagamento simulado (Modo apresentação do posto): nenhum valor é cobrado nem movimentado."


def page(title, body, *, refresh=None, status=200, tag="AMBIENTE DE TESTE", footer=TEST_FOOTER):
    meta = f'<meta http-equiv="refresh" content="{int(refresh)}">' if refresh else ""
    html = (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"{meta}<title>{escape(title)}</title><style>{STYLE}</style></head><body><main>"
        f'<div class="brand"><b>ChargeGrid</b><span class="tag">{escape(tag)}</span></div>'
        f"{body}"
        f'<p class="muted">{escape(footer)}</p>'
        "</main></body></html>"
    )
    return HTMLResponse(html, status_code=status, headers=HEADERS)


def error_page(exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
    body = f'<div class="card"><h1>Não foi possível continuar</h1><p>{escape(str(detail.get("message")))}</p></div>'
    return page("ChargeGrid", body, status=exc.status_code)


def money(cents):
    return billing.format_money(cents or 0)


def _settlement_rows(payment):
    if payment.charge_cents is None or payment.settlement_status != "done":
        return ""
    returned = payment.amount_cents - payment.charge_cents
    kind = "devolvido" if payment.method == "pix" or payment.refunded_cents else "liberado no cartão"
    rows = [("Energia confirmada", money(payment.energy_cents)), ("Cobrado", money(payment.charge_cents)),
            (f"Valor {kind}", money(returned))]
    if payment.waived_cents:
        rows.append(("Perdoado", money(payment.waived_cents)))
    return "".join(f'<div class="row"><span class="muted">{escape(a)}</span><b>{escape(b)}</b></div>' for a, b in rows)


def _final(payment):
    if payment.settlement_status in ("due", "settling"):
        return False
    return payment.status == "completed" or (payment.status in ("expired", "canceled")
                                             and payment.settlement_status in ("none", "done", "failed"))


# ---------------------------------------------------------------------------- QR do painel


def _kiosk_view(db, public_code, code):
    connector, station = service.kiosk_context(db, public_code, code)
    base, multiplier = current_terms(db, connector)
    price = pricing.dynamic_price(base, multiplier)
    buttons = "".join(
        f'<button name="amount" value="{cents}">{escape(money(cents))}</button>' for cents in service.KIOSK_AMOUNTS_CENTS
    )
    body = (
        f'<div class="card"><p class="muted">Ponto {escape(connector.public_code)} · {escape(station.name)}</p>'
        f'<h1>Pague aqui e carregue sem o app</h1><p class="muted">Tarifa agora: R$ {escape(str(price))}/kWh</p>'
        f'<form method="post" action="/pay/k/{quote(connector.public_code, safe="")}">'
        f'<input type="hidden" name="c" value="{escape(code)}"><div class="amounts">{buttons}</div></form></div>'
        '<div class="notice">Pré-autorizamos o valor escolhido e cobramos só a energia confirmada pelo equipamento; '
        "o restante é liberado. Teste: cartão 4242 4242 4242 4242, validade futura e CVC qualquer.</div>"
    )
    return page("Pagar recarga", body)


@router.get("/pay/k/{public_code}")
def kiosk_page(public_code: str, c: str = Query(default="", max_length=10), db=Depends(db_session)):
    try:
        return _kiosk_view(db, public_code, c)
    except HTTPException as exc:
        return error_page(exc)


def _kiosk_checkout(db, public_code, form, request_base):
    code = (form.get("c") or [""])[0][:10]
    try:
        amount = int((form.get("amount") or ["0"])[0])
    except ValueError:
        amount = 0
    payment, _ = service.create_kiosk_payment(db, public_code, code, amount, request_base)
    return payment.checkout_url


@router.post("/pay/k/{public_code}")
async def kiosk_checkout(public_code: str, request: Request, db=Depends(db_session)):
    form = parse_qs((await request.body()).decode("utf-8", "replace"))
    try:
        url = await run_in_threadpool(_kiosk_checkout, db, public_code, form, str(request.base_url))
    except HTTPException as exc:
        return error_page(exc)
    return RedirectResponse(url, status_code=303, headers={"Cache-Control": "no-store"})


def _status_view(db, payment_id, token, cancel):
    payment = service.kiosk_payment(db, payment_id, token)
    payment = service.advance(db, payment.id)
    connector = db.get(Connector, payment.connector_id)
    station = db.get(Station, connector.station_id)
    session = db.get(ChargingSession, payment.session_id) if payment.session_id else None
    parts = [f'<div class="card"><p class="muted">Ponto {escape(connector.public_code)} · {escape(station.name)}</p>'
             f'<h1>{escape(status_label(payment))}</h1>'
             f'<div class="row"><span class="muted">Valor pré-autorizado</span><b>{escape(money(payment.amount_cents))}'
             "</b></div>"]
    if payment.status in PRE_START:
        if payment.status == "declined":
            parts.append('<p>O cartão foi recusado. Tente outro cartão.</p>')
        elif cancel:
            parts.append('<p>Pagamento não concluído.</p>')
        if payment.checkout_url:
            parts.append(f'<a class="btn" href="{escape(payment.checkout_url)}">Continuar pagamento</a>')
    elif payment.status in FUNDED and not session:
        parts.append('<p>Pagamento confirmado. Iniciando a recarga no ponto…</p>')
    if session:
        kwh = f"{float(session.energy_wh or 0) / 1000:.2f}".replace(".", ",")
        state = {"starting": "Iniciando", "charging": "Carregando", "stopping": "Encerrando"}.get(
            session.status, "Recarga encerrada")
        parts.append(f'<div class="row"><span class="muted">Recarga</span><b>{escape(state)}</b></div>'
                     f'<div class="row"><span class="muted">Energia</span><b>{kwh} kWh</b></div>')
        if session.status in ("starting", "charging"):
            parts.append(f'<form method="post" action="/pay/s/{payment.id}/stop"><input type="hidden" name="t" '
                         f'value="{escape(token)}"><button class="danger">Encerrar recarga</button></form>')
    parts.append(_settlement_rows(payment))
    parts.append("</div>")
    return page("Pagamento da recarga", "".join(parts), refresh=None if _final(payment) else 3)


@router.get("/pay/s/{payment_id}")
def kiosk_status(payment_id: UUID, t: str = Query(default="", max_length=100), cancel: int = 0,
                 db=Depends(db_session)):
    try:
        return _status_view(db, payment_id, t, cancel)
    except HTTPException as exc:
        return error_page(exc)


def _stop(db, payment_id, token):
    payment = service.kiosk_payment(db, payment_id, token)
    service.kiosk_stop(db, payment)


@router.post("/pay/s/{payment_id}/stop")
async def kiosk_stop(payment_id: UUID, request: Request, db=Depends(db_session)):
    form = parse_qs((await request.body()).decode("utf-8", "replace"))
    token = (form.get("t") or [""])[0][:100]
    try:
        await run_in_threadpool(_stop, db, payment_id, token)
    except HTTPException as exc:
        return error_page(exc)
    return RedirectResponse(f"/pay/s/{payment_id}?t={quote(token)}", status_code=303,
                            headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------- totem (pedido sem celular)


def _comma(value, step):
    return str(Decimal(str(value)).quantize(Decimal(step))).replace(".", ",")


def _order_page(db, order_id, token):
    """Status do pedido do totem e, depois do início, o recibo (``receipts.service``) do visitante."""
    order = totem.order_by_token(db, order_id, token)
    if order.payment_id:
        service.advance(db, order.payment_id)
    order = totem.refresh_order(db, db.get(KioskOrder, order.id))
    db.commit()
    simulated = order.method == "simulated"
    labels = {"tag": "SIMULADO", "footer": SIMULATED_FOOTER} if simulated else {}
    connector = db.get(Connector, order.connector_id)
    station = db.get(Station, connector.station_id)
    payment = db.get(Payment, order.payment_id) if order.payment_id else None
    session = db.get(ChargingSession, order.session_id) if order.session_id else None
    status_text = totem.STATUS_LABELS[order.status] + (" · SIMULADO" if simulated else "")
    parts = [f'<div class="card"><p class="muted">Totem · Ponto {escape(connector.public_code)} · '
             f'{escape(station.name)}</p><h1>{escape(status_text)}</h1>']
    if payment is not None:
        parts.append(f'<div class="row"><span class="muted">Pagamento</span><b>{escape(status_label(payment))}</b></div>'
                     f'<div class="row"><span class="muted">Valor pré-autorizado</span>'
                     f'<b>{escape(money(payment.amount_cents))}</b></div>')
    if session is None:
        if order.status == "awaiting_payment":
            parts.append("<p>Conclua o pagamento no celular; o totem inicia a recarga sozinho.</p>")
        parts.append("</div>")
        final = order.status not in (*totem.KIOSK_ORDER_OPEN,)
        return page("Pedido do totem", "".join(parts), refresh=None if final else 5, **labels)
    receipt = receipts.build(db, session)
    charges = receipt["charges"]
    rows = [("Recibo nº", receipt["number"]), ("Situação", receipt["times"]["status_label"]),
            ("Fim", receipt["times"]["end_reason_label"] or "—"), ("Energia", f"{receipt['energy']['kwh']} kWh"),
            ("Tarifa", f"R$ {_comma(session.price_per_kwh, '0.0001')}/kWh"),
            ("Total", f"R$ {_comma(charges['total'], '0.01')}")]
    if payment is not None and payment.settlement_status == "done" and payment.charge_cents is not None:
        returned = "Devolvido (simulado)" if simulated else "Devolvido/liberado"
        rows.append((returned, money(payment.amount_cents - payment.charge_cents)))
    overstay_section = receipt.get("overstay") or {}
    if overstay_section.get("status") == "available" and overstay_section.get("summary"):
        rows.append(("Permanência", overstay_section["summary"]))
    parts.extend(f'<div class="row"><span class="muted">{escape(str(a))}</span><b>{escape(str(b))}</b></div>'
                 for a, b in rows)
    parts.append("</div>")
    parts.extend(f'<div class="notice">{escape(note)}</div>' for note in receipt["labels"]["notes"])
    parts.append(f'<p><a class="btn secondary" href="/pay/r/{order.id}.pdf?t={quote(token)}">Baixar PDF</a></p>')
    final = receipt["final"] and (payment is None or payment.settlement_status in ("done", "failed"))
    return page("Recibo da recarga", "".join(parts), refresh=None if final else 5, **labels)


@router.get("/pay/r/{order_id}.pdf")
def totem_receipt_pdf(order_id: UUID, t: str = Query(default="", max_length=100), db=Depends(db_session)):
    from ...reports import pdf  # ReportLab só nesta rota

    try:
        order = totem.order_by_token(db, order_id, t)
        if order.session_id is None:
            return page("ChargeGrid", '<div class="card"><h1>O recibo fica pronto quando a recarga começar</h1></div>',
                        status=404)
        payload = receipts.build(db, db.get(ChargingSession, order.session_id))
    except HTTPException as exc:
        return error_page(exc)
    return Response(pdf.receipt_pdf(payload), media_type="application/pdf",
                    headers={"Cache-Control": "no-store",
                             "Content-Disposition": f'attachment; filename="chargegrid-recibo-{payload["number"].lower()}.pdf"'})


@router.get("/pay/r/{order_id}")
def totem_receipt(order_id: UUID, t: str = Query(default="", max_length=100), db=Depends(db_session)):
    try:
        return _order_page(db, order_id, t)
    except HTTPException as exc:
        return error_page(exc)


@router.get("/pay/o/{order_id}")
def totem_checkout(order_id: UUID, t: str = Query(default="", max_length=100), db=Depends(db_session)):
    """QR do pedido na tela do totem: abre a Checkout hospedada enquanto o pagamento aguarda."""
    try:
        order = totem.order_by_token(db, order_id, t)
        order = totem.refresh_order(db, order)
        db.commit()
        payment = db.get(Payment, order.payment_id) if order.payment_id else None
    except HTTPException as exc:
        return error_page(exc)
    if order.status == "awaiting_payment" and payment is not None and payment.status in PRE_START \
            and payment.checkout_url:
        return RedirectResponse(payment.checkout_url, status_code=303, headers={"Cache-Control": "no-store"})
    return RedirectResponse(f"/pay/r/{order.id}?t={quote(t)}", status_code=303, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------- retorno do app


@router.get("/pay/return")
def app_return(p: UUID, cancel: int = 0, db=Depends(db_session)):
    if not db.get(Payment, p):
        return page("ChargeGrid", '<div class="card"><h1>Pagamento não encontrado</h1></div>', status=404)
    payment = service.advance(db, p)
    if payment.status in FUNDED:
        text = ("Pagamento confirmado (teste)", "Volte ao app ChargeGrid e informe o código do painel para iniciar.")
    elif payment.status in PRE_START and not cancel:
        text = ("Confirmando com a Stripe…", "Esta página atualiza sozinha. Você também pode voltar ao app.")
    elif payment.status in PRE_START:
        text = ("Pagamento não concluído", "Volte ao app ChargeGrid para tentar de novo.")
    else:
        text = (status_label(payment), "Volte ao app ChargeGrid.")
    body = (f'<div class="card"><h1>{escape(text[0])}</h1><p>{escape(text[1])}</p>'
            f'<div class="row"><span class="muted">Valor</span><b>{escape(money(payment.amount_cents))}</b></div></div>')
    waiting = payment.status in PRE_START and not cancel
    return page("Pagamento ChargeGrid", body, refresh=3 if waiting else None)
