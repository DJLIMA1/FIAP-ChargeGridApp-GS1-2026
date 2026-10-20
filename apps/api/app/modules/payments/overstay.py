"""Contrato com a frente de permanência (overstay). STUB: devolve zero e ``final=True``.

A frente D substitui os corpos destas duas funções (mantendo as assinaturas):

* ``overstay_terms(db, station)`` — termos mostrados e somados ao teto no orçamento:
  ``{"reserve_cents": int, "fee_per_minute": Decimal|None, "tolerance_minutes": int|None,
  "max_billable_minutes": int|None}``. ``reserve_cents`` entra em ``payments.amount_cents``.
* ``overstay_charge(db, session)`` — no acerto: ``(cents, final)``. O pagamento só é acertado
  quando a energia está encerrada **e** ``final`` é ``True`` (cabo desconectado ou limite atingido):
  o cartão permite uma única captura. O que passar da reserva vira ``uncollected_cents`` (nunca
  é cobrado em silêncio). Quando a permanência terminar fora do sync, chame
  ``payments.service.prepare_settlement_for_session(db, session)``.
"""


def overstay_terms(db, station):
    return {"reserve_cents": 0, "fee_per_minute": None, "tolerance_minutes": None, "max_billable_minutes": None}


def overstay_charge(db, session):
    return 0, True
