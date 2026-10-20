"""Taxa de permanência (overstay): o carro continua conectado depois que a recarga terminou.

A regra do dono é a ``rotation`` das regras do posto (``pricing.clean_rules``):

* ``enabled`` (padrão desligado), ``start_after_min`` = tolerância (0–1440 min),
  ``interval_min`` = intervalo cobrado (1–1440 min; 1 = "por minuto"),
  ``amount`` = valor por intervalo (R$ 0–100) e ``max_amount`` = teto (R$ 0–1000).

Os **termos** são a cópia aceita pelo motorista antes do início (orçamento): mudanças
posteriores do dono não alteram uma recarga em curso. ``version`` identifica os valores
aceitos (o app envia a versão que mostrou).

Cálculo, sempre sobre o tempo **confirmado** pelo equipamento (segundos cobráveis), nunca
sobre o relógio: ``taxa = min(teto, valor × floor((segundos − tolerância) / intervalo))``.
Só conta intervalo completo (a favor do motorista). Tudo determinístico, stdlib e ``Decimal``.
"""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
DEFAULT_ROTATION = {"enabled": False, "start_after_min": 10, "interval_min": 1, "amount": "1.00",
                    "max_amount": "30.00"}
MAX_AMOUNT_LIMIT = Decimal("1000")
TERM_FIELDS = ("grace_minutes", "interval_minutes", "amount", "max_amount")


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _money(value) -> Decimal:
    return _dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def money_text(value) -> str:
    """``Decimal('1')`` -> ``'R$ 1,00'``."""
    return f"R$ {str(_money(value)).replace('.', ',')}"


def cents(value) -> int:
    return int((_money(value) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def clean_rotation(rule) -> dict:
    """Valida a regra ``rotation`` já mesclada com o padrão; ``ValueError`` em pt-BR."""
    try:
        rule["start_after_min"] = int(rule["start_after_min"])
        rule["interval_min"] = int(rule["interval_min"])
        amount = _dec(rule["amount"])
        maximum = _dec(rule["max_amount"])
    except (TypeError, ValueError, InvalidOperation):
        raise ValueError("Preencha a taxa de permanência com números.") from None
    if not 0 <= rule["start_after_min"] <= 1440:
        raise ValueError("A tolerância vai de 0 a 1440 minutos.")
    if not 1 <= rule["interval_min"] <= 1440:
        raise ValueError("O intervalo da taxa de permanência vai de 1 a 1440 minutos.")
    if not amount.is_finite() or not Decimal(0) <= amount <= Decimal(100):
        raise ValueError("O valor da taxa de permanência vai de R$ 0,00 a R$ 100,00.")
    if not maximum.is_finite() or not Decimal(0) <= maximum <= MAX_AMOUNT_LIMIT:
        raise ValueError("O teto da taxa de permanência vai de R$ 0,00 a R$ 1.000,00.")
    rule["amount"] = str(_money(amount))
    rule["max_amount"] = str(_money(maximum))
    return rule


def terms_version(terms) -> str:
    canonical = json.dumps({field: str(terms[field]) for field in TERM_FIELDS}, sort_keys=True)
    return "ovs-" + hashlib.sha256(canonical.encode()).hexdigest()[:12]


def terms_from_rotation(rule) -> dict | None:
    """Termos que o motorista aceita (ou ``None`` com a taxa desligada)."""
    if not rule or not rule.get("enabled"):
        return None
    terms = {
        "enabled": True,
        "grace_minutes": int(rule["start_after_min"]),
        "interval_minutes": int(rule["interval_min"]),
        "amount": str(_money(rule["amount"])),
        "max_amount": str(_money(rule["max_amount"])),
    }
    terms["version"] = terms_version(terms)
    return terms


def clean_terms(raw) -> dict | None:
    """Termos gravados (sessão/orçamento): valida e recalcula a versão; inválido -> ``None``."""
    if not isinstance(raw, dict) or not raw.get("enabled"):
        return None
    try:
        rule = clean_rotation({"start_after_min": raw["grace_minutes"], "interval_min": raw["interval_minutes"],
                               "amount": raw["amount"], "max_amount": raw["max_amount"]})
    except (KeyError, ValueError):
        return None
    return terms_from_rotation({**rule, "enabled": True})


def _intervals(terms, seconds) -> int:
    over = int(seconds) - int(terms["grace_minutes"]) * 60
    return max(0, over // (int(terms["interval_minutes"]) * 60))


def fee_due(terms, seconds) -> Decimal:
    """Valor devido para ``seconds`` cobráveis (``0.00`` sem termos ou dentro da tolerância)."""
    if not terms:
        return Decimal("0.00")
    fee = _money(terms["amount"]) * _intervals(terms, seconds)
    return min(_money(terms["max_amount"]), fee).quantize(CENT)


def billable_minutes(terms, seconds) -> int:
    """Minutos cobrados além da tolerância (intervalos completos, até o teto)."""
    if not terms:
        return 0
    intervals = _intervals(terms, seconds)
    amount = _money(terms["amount"])
    if amount > 0:
        cap = int((_money(terms["max_amount"]) / amount).to_integral_value(rounding="ROUND_CEILING"))
        intervals = min(intervals, cap)
    return intervals * int(terms["interval_minutes"])


def capped(terms, seconds) -> bool:
    return bool(terms) and fee_due(terms, seconds) >= _money(terms["max_amount"])


def grace_remaining_seconds(terms, seconds) -> int:
    if not terms:
        return 0
    return max(0, int(terms["grace_minutes"]) * 60 - int(seconds))


def max_billable_minutes(terms) -> int | None:
    """Minutos além da tolerância até atingir o teto (``None`` com valor zero)."""
    if not terms or _money(terms["amount"]) <= 0:
        return None
    steps = (_money(terms["max_amount"]) / _money(terms["amount"])).to_integral_value(rounding="ROUND_CEILING")
    return int(steps) * int(terms["interval_minutes"])


def fee_per_minute(terms) -> Decimal | None:
    if not terms:
        return None
    return (_money(terms["amount"]) / int(terms["interval_minutes"])).quantize(Decimal("0.0001"))


def phase(terms, seconds, *, closed=False) -> str:
    """``closed`` | ``no_fee`` (sem termos aceitos) | ``grace`` | ``billing`` | ``capped``."""
    if closed:
        return "closed"
    if not terms:
        return "no_fee"
    if capped(terms, seconds):
        return "capped"
    return "grace" if int(seconds) <= int(terms["grace_minutes"]) * 60 else "billing"


def summary(terms) -> str | None:
    """``Após a recarga: 10 min de tolerância; depois R$ 1,00 por minuto, até R$ 30,00.``"""
    if not terms:
        return None
    every = "por minuto" if int(terms["interval_minutes"]) == 1 else f"a cada {terms['interval_minutes']} min"
    return (f"Após a recarga: {terms['grace_minutes']} min de tolerância; depois "
            f"{money_text(terms['amount'])} {every}, até {money_text(terms['max_amount'])}.")


def public(terms) -> dict:
    """Condições mostradas ao motorista antes de aceitar (sem dados privados do dono)."""
    if not terms:
        return {"enabled": False, "grace_minutes": None, "interval_minutes": None, "amount": None,
                "max_amount": None, "fee_per_minute": None, "version": None, "summary": None}
    return {key: terms[key] for key in ("enabled", "grace_minutes", "interval_minutes", "amount",
                                        "max_amount", "version")} | {
        "fee_per_minute": str(fee_per_minute(terms)), "summary": summary(terms)}
