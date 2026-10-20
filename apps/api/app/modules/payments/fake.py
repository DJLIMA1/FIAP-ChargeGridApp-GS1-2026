"""Stripe falsa, em memória, para os testes (nenhuma chamada de rede).

Imita o suficiente da Checkout Session e do PaymentIntent: pagar com cartão (autorização
retida), Pix (cobrado na hora) ou recusa; capturar parcial, cancelar, devolver e expirar.
Respeita ``Idempotency-Key`` (mesma chave → mesma resposta, sem repetir o efeito) e permite
injetar falhas (``fail_next``) e contar chamadas (``calls``).
"""

import copy
import itertools

from .gateway import GatewayError


class FakeStripe:
    environment = "test"

    def __init__(self):
        self.sessions = {}
        self.intents = {}
        self.calls = []
        self.fail_next = {}
        self._idempotent = {}
        self._ids = itertools.count(1)

    # ------------------------------------------------------------------ helpers
    def _next(self, prefix):
        return f"{prefix}_test_fake{next(self._ids)}"

    def _call(self, name, key, effect):
        self.calls.append(name)
        failure = self.fail_next.pop(name, None)
        if failure is not None:
            raise failure
        if key is not None:
            cache_key = (name, key)
            if cache_key not in self._idempotent:
                self._idempotent[cache_key] = effect()
            return copy.deepcopy(self._idempotent[cache_key])
        return copy.deepcopy(effect())

    def _session_view(self, session):
        view = dict(session)
        if session["payment_intent"]:
            view["payment_intent"] = self._intent_view(self.intents[session["payment_intent"]])
        return view

    def _intent_view(self, intent):
        view = dict(intent)
        view["latest_charge"] = dict(intent["latest_charge"]) if intent["latest_charge"] else None
        return view

    # ------------------------------------------------------------------ API
    def create_checkout_session(self, params, idempotency_key):
        def effect():
            session_id = self._next("cs")
            amount = params["line_items"][0]["price_data"]["unit_amount"]
            session = {
                "id": session_id, "object": "checkout.session", "status": "open", "payment_status": "unpaid",
                "url": f"https://checkout.stripe.test/c/pay/{session_id}", "amount_total": amount,
                "currency": params["line_items"][0]["price_data"]["currency"], "metadata": dict(params["metadata"]),
                "payment_intent": None, "expires_at": params.get("expires_at"), "params": copy.deepcopy(params),
            }
            self.sessions[session_id] = session
            return self._session_view(session)
        return self._call("create_checkout_session", idempotency_key, effect)

    def retrieve_checkout_session(self, session_id):
        return self._call("retrieve_checkout_session", None, lambda: self._session_view(self.sessions[session_id]))

    def expire_checkout_session(self, session_id, idempotency_key):
        def effect():
            session = self.sessions[session_id]
            if session["status"] != "open":
                raise GatewayError("checkout_session_not_open", "Session is not open", status=400)
            session["status"] = "expired"
            return self._session_view(session)
        return self._call("expire_checkout_session", idempotency_key, effect)

    def retrieve_payment_intent(self, intent_id):
        return self._call("retrieve_payment_intent", None, lambda: self._intent_view(self.intents[intent_id]))

    def capture(self, intent_id, amount_cents, idempotency_key):
        def effect():
            intent = self.intents[intent_id]
            if intent["status"] != "requires_capture":
                raise GatewayError("payment_intent_unexpected_state", intent["status"], status=400)
            if amount_cents > intent["amount_capturable"]:
                raise GatewayError("amount_too_large", "", status=400)
            intent.update(status="succeeded", amount_received=amount_cents, amount_capturable=0)
            fee = round(amount_cents * 0.0399) + 39
            intent["latest_charge"].update(
                captured=True, amount_captured=amount_cents, balance_transaction={"fee": fee}
            )
            return self._intent_view(intent)
        return self._call("capture", idempotency_key, effect)

    def cancel(self, intent_id, idempotency_key):
        def effect():
            intent = self.intents[intent_id]
            if intent["status"] not in ("requires_capture", "requires_payment_method", "requires_confirmation"):
                raise GatewayError("payment_intent_unexpected_state", intent["status"], status=400)
            intent.update(status="canceled", amount_capturable=0)
            return self._intent_view(intent)
        return self._call("cancel", idempotency_key, effect)

    def refund(self, intent_id, amount_cents, idempotency_key):
        def effect():
            intent = self.intents[intent_id]
            charge = intent["latest_charge"]
            if intent["status"] != "succeeded" or amount_cents > charge["amount_captured"] - charge["amount_refunded"]:
                raise GatewayError("refund_invalid", "", status=400)
            charge["amount_refunded"] += amount_cents
            return {"id": self._next("re"), "object": "refund", "amount": amount_cents, "status": "succeeded",
                    "payment_intent": intent_id}
        return self._call("refund", idempotency_key, effect)

    # ------------------------------------------------------------------ cenário de teste
    def pay(self, session_id, method="card", decline=False):
        """Simula o motorista concluindo (ou não) a Checkout."""
        session = self.sessions[session_id]
        intent_id = session["payment_intent"] or self._next("pi")
        amount = session["amount_total"]
        if decline:
            status, charge = "requires_payment_method", None
        else:
            manual = method == "card" and (
                session["params"].get("payment_method_options", {}).get("card", {}).get("capture_method") == "manual"
            )
            status = "requires_capture" if manual else "succeeded"
            charge = {
                "id": self._next("ch"), "captured": not manual, "amount_captured": 0 if manual else amount,
                "amount_refunded": 0, "payment_method_details": {"type": method},
                "balance_transaction": None if manual else {"fee": round(amount * 0.0119)},
            }
        self.intents[intent_id] = {
            "id": intent_id, "object": "payment_intent", "status": status, "amount": amount,
            "amount_capturable": amount if status == "requires_capture" else 0,
            "amount_received": amount if status == "succeeded" else 0, "currency": "brl",
            "metadata": dict(session["metadata"]), "latest_charge": charge,
            "last_payment_error": {"code": "card_declined"} if decline else None,
            "payment_method_types": [method],
        }
        session["payment_intent"] = intent_id
        if not decline:
            session.update(status="complete", payment_status="paid" if status == "succeeded" else "unpaid")
        return self.intents[intent_id]

    def event(self, event_type, obj, event_id=None):
        return {"id": event_id or self._next("evt"), "object": "event", "type": event_type,
                "data": {"object": copy.deepcopy(obj)}}
