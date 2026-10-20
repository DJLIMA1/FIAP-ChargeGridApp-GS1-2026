"""Contrato com a frente de permanência (overstay), implementado em ``app.overstay``.

* ``overstay_terms(db, station)`` — termos mostrados e somados ao teto no orçamento:
  ``{"reserve_cents": int, "fee_per_minute": Decimal|None, "tolerance_minutes": int|None,
  "max_billable_minutes": int|None}`` (+ os termos completos de ``chargegrid_core.overstay``,
  travados no orçamento e copiados para a sessão no START pago). ``reserve_cents`` é o teto
  da taxa e entra em ``payments.amount_cents``.
* ``overstay_charge(db, session)`` — no acerto: ``(cents, final)``. ``final`` só é ``True`` com a
  energia encerrada **e** a permanência fechada, ausente ou no teto. Quando a permanência
  termina fora do sync, ``app.overstay.reconcile`` chama
  ``payments.service.prepare_settlement_for_session(db, session)``.
"""

from ... import overstay


def overstay_terms(db, station):
    return overstay.payment_terms(station)


def overstay_charge(db, session):
    return overstay.charge(db, session)
