"""Pontos de extensão do recibo e do resultado do dono para as outras frentes.

Cada frente pluga o seu fato confirmado com **um arquivo próprio + uma linha de registro**
(por exemplo no ``__init__`` do módulo dela ou em ``app/main.py``), sem editar o recibo:

* ``register_extras(name, batch)``: fatos por sessão usados pelo recibo **e** pela margem.
  ``batch(db, sessions) -> {session_id: dict}`` (uma consulta para várias sessões, sem N+1).
  Nomes conhecidos:

  - ``"payment"`` (frente A): ``{environment: "mock"|"sandbox"|"production", provider,
    provider_reference, method, status, authorized_amount, captured_amount, refunded_amount,
    net_amount, provider_fee, refund_status, confirmed_at}``. Valores em strings decimais (R$).
    Só registrar pagamento confirmado pelo provedor (webhook). ``net_amount`` (capturado −
    devolvido) substitui a receita estimada na margem; a captura deve usar
    ``chargegrid_core.economics.charged_amount``.
  - ``"overstay"`` (frente D): ``{status, grace_minutes, started_at, ended_at,
    billable_minutes, rate, amount, waived}``. ``amount`` entra na receita e na comissão.

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
