"""Cliente Stripe mínimo (httpx, sem SDK) e verificação de assinatura do webhook.

Só o necessário para o teto pré-pago: criar/consultar/expirar a Checkout Session, consultar o
PaymentIntent, capturar (parcial), cancelar a autorização e devolver (refund parcial). Toda
chamada que altera dinheiro leva ``Idempotency-Key``: repetir depois de um timeout é seguro.

Somente MODO TESTE: ``current()`` devolve ``None`` sem chave ou com chave que não seja de teste.
Os testes trocam o gateway por ``FakeStripe`` (``use()``) e nunca acessam a rede.
"""

import hashlib
import hmac
import time

import httpx

from ...config import settings

API_BASE = "https://api.stripe.com"
TEST_KEY_PREFIXES = ("sk_test_", "rk_test_")
SIGNATURE_TOLERANCE_SECONDS = 300


class GatewayError(Exception):
    """Falha do provedor; ``retryable`` indica que o resultado é desconhecido (timeout/5xx)."""

    def __init__(self, code, message="", status=None, retryable=False):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable


def encode(params, prefix=""):
    """Dicionário aninhado → pares do formulário da Stripe (``a[b][0]=c``)."""
    pairs = []
    items = params.items() if isinstance(params, dict) else enumerate(params)
    for key, value in items:
        name = f"{prefix}[{key}]" if prefix else str(key)
        if value is None:
            continue
        if isinstance(value, (dict, list, tuple)):
            pairs.extend(encode(value, name))
        elif isinstance(value, bool):
            pairs.append((name, "true" if value else "false"))
        else:
            pairs.append((name, str(value)))
    return pairs


class StripeGateway:
    environment = "test"

    def __init__(self, secret_key, timeout=8.0, transport=None):
        self._client = httpx.Client(
            base_url=API_BASE, auth=(secret_key, ""), timeout=timeout, transport=transport
        )

    def _request(self, method, path, data=None, params=None, idempotency_key=None):
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        try:
            response = self._client.request(
                method, path, data=encode(data or {}) or None, params=encode(params or {}) or None, headers=headers
            )
        except httpx.TimeoutException as exc:
            raise GatewayError("timeout", "Stripe não respondeu a tempo", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise GatewayError("network", "Falha de rede com a Stripe", retryable=True) from exc
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400:
            error = body.get("error") or {}
            raise GatewayError(
                error.get("code") or error.get("type") or "stripe_error", str(error.get("message") or "")[:200],
                status=response.status_code, retryable=response.status_code >= 500 or response.status_code == 429,
            )
        return body

    def create_checkout_session(self, params, idempotency_key):
        return self._request("POST", "/v1/checkout/sessions", data=params, idempotency_key=idempotency_key)

    def retrieve_checkout_session(self, session_id):
        return self._request(
            "GET", f"/v1/checkout/sessions/{session_id}",
            params={"expand": ["payment_intent", "payment_intent.latest_charge.balance_transaction"]},
        )

    def expire_checkout_session(self, session_id, idempotency_key):
        return self._request("POST", f"/v1/checkout/sessions/{session_id}/expire", idempotency_key=idempotency_key)

    def retrieve_payment_intent(self, intent_id):
        return self._request(
            "GET", f"/v1/payment_intents/{intent_id}", params={"expand": ["latest_charge.balance_transaction"]}
        )

    def capture(self, intent_id, amount_cents, idempotency_key):
        return self._request(
            "POST", f"/v1/payment_intents/{intent_id}/capture",
            data={"amount_to_capture": amount_cents, "expand": ["latest_charge.balance_transaction"]},
            idempotency_key=idempotency_key,
        )

    def cancel(self, intent_id, idempotency_key):
        return self._request(
            "POST", f"/v1/payment_intents/{intent_id}/cancel", data={"cancellation_reason": "abandoned"},
            idempotency_key=idempotency_key,
        )

    def refund(self, intent_id, amount_cents, idempotency_key):
        return self._request(
            "POST", "/v1/refunds", data={"payment_intent": intent_id, "amount": amount_cents},
            idempotency_key=idempotency_key,
        )


_override = None
_cached = {}


def use(gateway):
    """Troca o gateway (testes: ``FakeStripe``; ``None`` volta ao configurado)."""
    global _override
    _override = gateway


def current():
    """Gateway ativo ou ``None`` (sem chave, ou chave que não seja de teste)."""
    if _override is not None:
        return _override
    key = settings().stripe_secret_key.strip()
    if not key.startswith(TEST_KEY_PREFIXES):
        return None
    if key not in _cached:
        _cached.clear()
        _cached[key] = StripeGateway(key)
    return _cached[key]


def verify_signature(payload: bytes, header: str, secret: str, now=None, tolerance=SIGNATURE_TOLERANCE_SECONDS):
    """``Stripe-Signature: t=...,v1=...``: HMAC-SHA256 de ``t.payload`` com o segredo do endpoint."""
    if not secret or not header:
        return False
    parts = {}
    signatures = []
    for item in header.split(","):
        key, _, value = item.strip().partition("=")
        if key == "v1":
            signatures.append(value)
        else:
            parts[key] = value
    try:
        timestamp = int(parts.get("t", ""))
    except ValueError:
        return False
    if abs((now if now is not None else time.time()) - timestamp) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, signature) for signature in signatures)


def sign(payload: bytes, secret: str, timestamp=None):
    """Cabeçalho ``Stripe-Signature`` (testes e simulação local do webhook)."""
    timestamp = int(timestamp if timestamp is not None else time.time())
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"
