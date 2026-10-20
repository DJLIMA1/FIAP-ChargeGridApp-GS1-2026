"""Pontos de extensão do recibo e do resultado do dono para as outras frentes.

Cada frente pluga o seu fato confirmado com **um arquivo próprio + uma linha de registro**
(por exemplo no ``__init__`` do módulo dela ou em ``app/main.py``), sem editar o recibo:

* ``register_extras(name, batch)``: fatos por sessão usados pelo recibo **e** pela margem.
  ``batch(db, sessions) -> {session_id: dict}`` (uma consulta para várias sessões, sem N+1).
  Nomes conhecidos:

  - ``"payment"`` (frente A, ``payments/receipt.py``): ``{environment: "mock"|"sandbox"|"production",
    provider, provider_reference, method, status, settlement_status, authorized_amount,
    captured_amount, refunded_amount, net_amount, charged_amount, energy_amount, overstay_amount,
    waived_amount, uncollected_amount, below_minimum, provider_fee, refund_status, confirmed_at,
    settled_at}``. Valores em strings decimais (R$). Só registrar pagamento confirmado pelo
    provedor (webhook). ``net_amount`` (capturado − devolvido) substitui a receita estimada na
    margem; a captura deve usar ``chargegrid_core.economics.charged_amount``.
  - ``"overstay"`` (frente D, ``app/overstay.py::receipt_extras``): ``{phase, grace_minutes,
    started_at, ended_at, end_reason, billable_minutes, rate, max_amount, amount, final, summary,
    waived}``. ``amount`` entra na receita e na comissão (``None`` = sem termos aceitos, sem taxa).

  ``status`` x ``phase``: no recibo, ``status`` de **toda** seção é reservado ao core
  (``chargegrid_core.receipt``) e diz se a seção existe — ``"available"`` | ``"pending"`` |
  ``"not_applicable"`` | ``"unavailable"`` — então o estado de negócio de uma frente não pode
  usar essa chave. Na seção ``payment`` o core sobrescreve ``status`` e preserva o original em
  ``payment_status``; a seção ``overstay`` já nasce com ``phase`` (``grace`` | ``billing`` |
  ``capped`` | ``no_fee`` | ``closed``, o mesmo valor de ``status`` no bloco ``overstay`` da
  sessão e do sync) para não colidir. Clientes leem ``section["status"]`` para saber se mostram
  a seção e ``phase``/``payment_status`` para o estado.

* ``register_section(name, provider)``: seção só do recibo. ``provider(db, session)``.
  Nome conhecido: ``"power_changes"`` (frente B): lista
  ``[{at, requested_kw, applied_kw, status: "requested"|"applied"|"failed", reason_code,
  reason_label, confirmed_at, source}]`` — "applied" só após o ACK do equipamento.
  Outros nomes aparecem em ``receipt["extensions"]``.

Um provedor que falhar não derruba o recibo: a seção fica ausente (``not_applicable``)
e o erro é registrado no log.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

log = logging.getLogger(__name__)

_EXTRAS: dict[str, Callable] = {}
_SECTIONS: dict[str, Callable] = {}


def register_extras(name: str, batch: Callable) -> None:
    _EXTRAS[name] = batch


def register_section(name: str, provider: Callable) -> None:
    _SECTIONS[name] = provider


def unregister(name: str) -> None:
    """Remove um provedor (usado nos testes)."""
    _EXTRAS.pop(name, None)
    _SECTIONS.pop(name, None)


def extras_for(db, sessions) -> dict:
    """``{session_id: {"payment": {...}, "overstay": {...}}}`` para as sessões informadas."""
    sessions = list(sessions)
    result = {session.id: {} for session in sessions}
    if not sessions:
        return result
    for name, batch in _EXTRAS.items():
        try:
            with db.begin_nested():  # savepoint: um erro de SQL do provedor não aborta a transação
                values = batch(db, sessions) or {}
        except Exception:  # pragma: no cover - defensivo: uma frente não derruba o recibo
            log.exception("receipt extras provider %s failed", name)
            continue
        for session_id, value in values.items():
            if session_id in result and value is not None:
                result[session_id][name] = value
    return result


def sections_for(db, session) -> dict:
    sections = dict(extras_for(db, [session])[session.id])
    for name, provider in _SECTIONS.items():
        try:
            with db.begin_nested():
                value = provider(db, session)
        except Exception:  # pragma: no cover - defensivo
            log.exception("receipt section provider %s failed", name)
            continue
        if value is not None:
            sections[name] = value
    return sections
