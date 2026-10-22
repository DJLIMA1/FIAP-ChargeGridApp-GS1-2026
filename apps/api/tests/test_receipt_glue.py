"""Integração recibo/margem (C) × pagamento Stripe teste (A) × potência ao vivo (B)."""

from decimal import Decimal

from test_http import client_for
from test_live_power import _charge as _charge_live
from test_live_power import bench  # noqa: F401 - fixture reutilizada
from test_payments import _paid, _start_paid, client, flow, stripe  # noqa: F401 - fixtures reutilizadas

from app.models import Command, Payment
from app.modules.receipts import registry


def _receipt(http, session_id):
    response = http.get(f"/v1/charging-sessions/{session_id}/receipt")
    assert response.status_code == 200, response.text
    return response.json()


def _margin_row(factory, seed, session_id):
    owner, _ = client_for(factory, seed["owner"])  # troca o usuário do app: chamar por último
    report = owner.get("/v1/owner/margin").json()
    return next(item for item in report["items"] if item["session_id"] == session_id)


# ------------------------------------------------------------------ pagamento


def test_card_partial_capture_drives_receipt_total_and_margin(flow, stripe, factory, seed):  # noqa: F811
    payment = _paid(flow, stripe)
    session = _start_paid(flow, payment)
    flow.charge(session["id"], 3000)
    flow.stop(session["id"], 6200)
    done = flow.get(payment["id"])
    assert done["settlement"]["captured"] == "12.40" and done["settlement"]["returned"] == "7.60"
    receipt = _receipt(flow.http, session["id"])
    paid = receipt["payment"]
    assert paid["status"] == "available" and paid["payment_status"] == "completed"
    assert paid["environment"] == "sandbox"  # "test" gravado pela frente A vira "sandbox" no recibo
    assert (paid["authorized_amount"], paid["captured_amount"], paid["refunded_amount"], paid["net_amount"]) == \
        ("20.00", "12.40", "0.00", "12.40")
    assert paid["refund_status"] == "released" and paid["provider_reference"] == done["provider_ref"]
    assert paid["provider_fee"] == done["settlement"]["provider_fee"]
    charges = receipt["charges"]
    # 6,2 kWh × R$ 2,00 = 12,40: calculado, capturado e total batem ao centavo.
    assert charges["revenue_basis"] == "paid"
    assert charges["calculated_total"] == charges["paid_total"] == charges["total"] == "12.40"
    assert charges["difference"] == "0.00" and charges["adjustments"] == [] and charges["note"] is None
    labels = receipt["labels"]
    assert labels["payment_environment"] == "sandbox"
    assert labels["notes"] == ["Documento sem valor fiscal."]  # sem aviso de sandbox no texto
    with factory() as db:
        assert db.get(Payment, payment["id"]).environment == "test"  # valor armazenado não muda
    row = _margin_row(factory, seed, session["id"])
    fee = Decimal(done["settlement"]["provider_fee"])
    assert row["revenue_basis"] == "captured" and row["payment_environment"] == "sandbox"
    assert row["revenue"] == "12.40" and row["revenue_total"] == "12.40"
    assert Decimal(row["provider_fee"]) == fee and row["platform_fee"] == "3.10"
    assert Decimal(row["owner_net"]) == Decimal("12.40") - Decimal("3.10") - fee


def test_pix_refund_margin_uses_captured_minus_refunded(flow, stripe, factory, seed):  # noqa: F811
    payment = _paid(flow, stripe, method="pix")
    session = _start_paid(flow, payment)
    flow.charge(session["id"], 3000)
    flow.stop(session["id"], 6200)
    done = flow.get(payment["id"])
    receipt = _receipt(flow.http, session["id"])
    paid = receipt["payment"]
    assert (paid["captured_amount"], paid["refunded_amount"], paid["net_amount"]) == ("20.00", "7.60", "12.40")
    assert paid["refund_status"] == "refunded" and paid["method"] == "pix"
    assert receipt["charges"]["total"] == receipt["charges"]["paid_total"] == "12.40"
    assert receipt["charges"]["difference"] == "0.00"
    row = _margin_row(factory, seed, session["id"])
    assert row["revenue_total"] == "12.40"  # capturado 20,00 − devolvido 7,60, não o autorizado
    assert row["provider_fee"] == done["settlement"]["provider_fee"]
    assert row["platform_fee"] == "3.10"


def test_capture_below_calculated_total_is_explicit_and_captured_wins(flow, stripe, factory, seed):  # noqa: F811
    payment = _paid(flow, stripe)
    session = _start_paid(flow, payment)
    flow.charge(session["id"], 5000)
    flow.stop(session["id"], 10500)  # 21,00 de energia com teto pago de 20,00
    flow.get(payment["id"])
    charges = _receipt(flow.http, session["id"])["charges"]
    assert charges["calculated_total"] == "21.00" and charges["paid_total"] == "20.00"
    assert charges["total"] == "20.00" and charges["difference"] == "-1.00"
    assert charges["adjustments"] == [{"key": "waived", "label": "Acima do valor pré-pago: não cobrado",
                                       "amount": "-1.00"}]
    assert "difere do calculado" in charges["note"]
    row = _margin_row(factory, seed, session["id"])
    assert row["revenue"] == "21.00" and row["revenue_total"] == "20.00" and row["revenue_basis"] == "captured"


def test_below_provider_minimum_shows_zero_paid(flow, stripe, factory, seed):  # noqa: F811
    payment = _paid(flow, stripe)
    session = _start_paid(flow, payment)
    flow.charge(session["id"], 100)
    flow.stop(session["id"], 100)
    flow.get(payment["id"])
    charges = _receipt(flow.http, session["id"])["charges"]
    assert (charges["calculated_total"], charges["total"], charges["difference"]) == ("0.20", "0.00", "-0.20")
    assert charges["adjustments"][0]["key"] == "below_minimum"


def test_confirmed_payment_before_settlement_keeps_estimate(flow, stripe, factory, seed):  # noqa: F811
    payment = _paid(flow, stripe)
    session = _start_paid(flow, payment)
    flow.charge(session["id"], 3000)
    receipt = _receipt(flow.http, session["id"])
    assert receipt["payment"]["payment_status"] == "in_use" and receipt["payment"]["net_amount"] is None
    assert receipt["charges"]["revenue_basis"] == "estimated" and "paid_total" not in receipt["charges"]
    assert receipt["charges"]["note"].startswith("Pagamento confirmado")


def test_providers_are_registered_by_the_app():
    assert "payment" in registry._EXTRAS and "power_changes" in registry._SECTIONS


def test_receipt_pdf_shows_calculated_difference_and_paid_total(flow, stripe, factory, seed, monkeypatch):  # noqa: F811
    from app.reports import pdf

    monkeypatch.setattr(pdf, "COMPRESS", False)
    payment = _paid(flow, stripe)
    session = _start_paid(flow, payment)
    flow.charge(session["id"], 5000)
    flow.stop(session["id"], 10500)
    flow.get(payment["id"])
    response = flow.http.get(f"/v1/charging-sessions/{session['id']}/receipt.pdf")
    assert response.status_code == 200, response.text
    body = response.content
    for text in (b"Calculado pela energia", b"Acima do valor pr\\351-pago", b"Total pago"):
        assert text in body, text
    assert b"sandbox" not in body


# ------------------------------------------------------------------ potência


def test_power_changes_in_receipt_count_only_acknowledged(bench):  # noqa: F811
    _charge_live(bench, "a")
    bench.store(26)
    bench.sync("a", 2)  # redução pedida e confirmada (ACK) → 4 kW
    bench.store(12)
    bench.sync("a")  # aumento pedido, ACK ainda não chegou
    bench.sims["a"].acks = []
    bench.as_user(bench.drivers["a"])
    receipt = _receipt(bench.client, bench.sessions["a"])
    changes = receipt["power"]["changes"]
    assert [(c["direction"], c["status"]) for c in changes] == \
        [("start", "applied"), ("reduce", "applied"), ("raise", "requested")]
    start, reduce, raise_ = changes
    assert start["applied_kw"] == "7.200" and start["reason_code"] == "start_limit"
    assert reduce["requested_kw"] == "4.000" and reduce["applied_kw"] == "4.000"
    assert reduce["previous_kw"] == "7.200" and reduce["confirmed_at"] and reduce["source"] == "rebalance"
    assert reduce["reason_code"] and "26 kW dos 30 kW contratados ficam reservados para a loja" in reduce["reason_label"]
    assert raise_["requested_kw"] == "7.200" and raise_["applied_kw"] is None and raise_["confirmed_at"] is None
    assert [item["kw"] for item in receipt["power"]["applied_limits"]] == ["7.200", "4.000"]


def test_power_change_rejected_by_device_is_failed(bench):  # noqa: F811
    _charge_live(bench, "a")
    bench.store(25)
    bench.sync("a")
    command = bench.commands("a", "SET_POWER")[-1]
    payload = bench.sims["a"].payload()
    payload["acks"] = [{"command_id": str(command.id), "status": "applied", "error": None, "applied_power_w": 7200}]
    payload["applied_power_w"] = 7200
    assert bench.client.post("/v1/devices/sync", headers={"Authorization": "Device key-a"},
                             json=payload).status_code == 200
    bench.as_user(bench.drivers["a"])
    changes = _receipt(bench.client, bench.sessions["a"])["power"]["changes"]
    failed, retry = changes[1], changes[2]
    assert failed["status"] == "failed" and failed["failure_code"] == "applied_power_mismatch"
    assert failed["applied_kw"] is None and failed["reported_kw"] == "7.200"
    assert (retry["status"], retry["attempt"]) == ("requested", 2)  # reenvio da redução, ainda sem ACK
    assert all(change["at"].endswith("+00:00") for change in changes)


def test_power_change_failed_ack_without_event_is_failed(bench):  # noqa: F811
    _charge_live(bench, "a")
    bench.store(25)
    bench.sync("a")
    with bench.factory.begin() as db:
        command = db.get(Command, bench.commands("a", "SET_POWER")[-1].id)
        command.status, command.error = "failed", "readback_mismatch"
    bench.as_user(bench.drivers["a"])
    failed = _receipt(bench.client, bench.sessions["a"])["power"]["changes"][-1]
    assert failed["status"] == "failed" and failed["failure_code"] == "readback_mismatch"


def test_station_without_live_rebalance_keeps_start_limit(factory, seed):
    from test_receipts_economics import _charge

    driver, session_id = _charge(factory, seed, reserve=False)
    changes = _receipt(driver, session_id)["power"]["changes"]
    assert len(changes) == 1 and changes[0]["reason_code"] == "start_limit"
