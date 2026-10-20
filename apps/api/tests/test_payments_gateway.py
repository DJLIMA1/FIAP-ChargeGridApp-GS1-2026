"""StripeGateway real sem rede: formato do formulário, expand, idempotência, erros e assinatura."""

import time
from urllib.parse import parse_qsl

import httpx
import pytest

from app.modules.payments.gateway import GatewayError, StripeGateway, encode, sign, verify_signature


def _gateway(handler):
    return StripeGateway("sk_test_unit", transport=httpx.MockTransport(handler))


def test_encode_nested_params_like_stripe():
    pairs = encode({"line_items": [{"price_data": {"unit_amount": 2000}}], "confirm": True, "skip": None,
                    "expand": ["a", "b"]})
    assert pairs == [("line_items[0][price_data][unit_amount]", "2000"), ("confirm", "true"),
                     ("expand[0]", "a"), ("expand[1]", "b")]


def test_post_sends_form_body_auth_and_idempotency_key():
    seen = {}

    def handler(request):
        seen.update(method=request.method, path=request.url.path, body=dict(parse_qsl(request.content.decode())),
                    headers=request.headers)
        return httpx.Response(200, json={"id": "pi_1", "status": "succeeded"})

    result = _gateway(handler).capture("pi_1", 1240, "capture-x")
    assert result["status"] == "succeeded"
    assert (seen["method"], seen["path"]) == ("POST", "/v1/payment_intents/pi_1/capture")
    assert seen["body"] == {"amount_to_capture": "1240", "expand[0]": "latest_charge.balance_transaction"}
    assert seen["headers"]["idempotency-key"] == "capture-x"
    assert seen["headers"]["content-type"] == "application/x-www-form-urlencoded"
    assert seen["headers"]["authorization"].startswith("Basic ")


def test_get_sends_expand_as_query():
    def handler(request):
        assert request.method == "GET" and not request.content
        assert request.url.params.get_list("expand[0]") == ["payment_intent"]
        return httpx.Response(200, json={"id": "cs_1"})

    assert _gateway(handler).retrieve_checkout_session("cs_1")["id"] == "cs_1"


@pytest.mark.parametrize(("status", "retryable"), [(400, False), (402, False), (429, True), (500, True)])
def test_provider_errors_are_classified(status, retryable):
    def handler(request):
        return httpx.Response(status, json={"error": {"code": "card_declined", "message": "x" * 300}})

    with pytest.raises(GatewayError) as error:
        _gateway(handler).cancel("pi_1", "cancel-x")
    assert (error.value.code, error.value.status, error.value.retryable) == ("card_declined", status, retryable)
    assert len(error.value.message) == 200


def test_timeout_is_retryable():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(GatewayError) as error:
        _gateway(handler).refund("pi_1", 100, "refund-x")
    assert (error.value.code, error.value.retryable) == ("timeout", True)


def test_signature_roundtrip_and_rejections():
    payload = b'{"id":"evt_1"}'
    header = sign(payload, "whsec_a")
    assert verify_signature(payload, header, "whsec_a")
    assert not verify_signature(payload + b" ", header, "whsec_a")
    assert not verify_signature(payload, header, "whsec_b")
    assert not verify_signature(payload, "", "whsec_a")
    assert not verify_signature(payload, "t=abc,v1=00", "whsec_a")
    assert not verify_signature(payload, sign(payload, "whsec_a", time.time() - 301), "whsec_a")
    # Vários v1 (rotação do segredo): basta um válido.
    assert verify_signature(payload, header + ",v1=deadbeef", "whsec_a")
