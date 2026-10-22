import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from chargegrid_core import receipt as r

UTC = timezone.utc
NOW = datetime(2026, 10, 20, 18, 0, tzinfo=UTC)
STATUS = {"multiplier": "1.30", "level": "high", "level_label": "Alta", "reason": "demand_schedule",
          "reason_label": "Alta demanda · Horário 18:00–21:00",
          "factors": [{"key": "occupancy", "label": "Ocupação agora", "value": "3 de 4", "detail": "75%"}],
          "schedule_now": {"start": "18:00", "end": "21:00", "days": [0], "prices": {"p1": "1.2000"}}}


def terms(**overrides):
    params = dict(locked_at="2026-10-20T17:02:00Z", locked_by="reservation", connector_base="1.0000",
                  base="1.2000", multiplier="1.30", status=STATUS, interval=STATUS["schedule_now"],
                  connector_id="p1", coupon={"id": "c1", "code": "LOJA10", "discount_percent": 10})
    params.update(overrides)
    return r.price_terms(**params)


def session(**overrides):
    base = {"id": "1a2b3c4d-0000-4000-8000-000000000000", "status": "completed", "reservation_id": "res1",
            "created_at": "2026-10-20T17:05:00Z", "started_at": "2026-10-20T17:06:00Z",
            "ended_at": "2026-10-20T17:46:00Z", "energy_wh": "10000.000", "price_per_kwh": "1.5600",
            "base_price_per_kwh": "1.2000", "demand_multiplier": "1.30", "discount_percent": 10,
            "cost_estimate": "14.0400", "source": "simulated", "last_measurement_at": "2026-10-20T17:46:00Z",
            "end_reason": "requested_stop", "power_limit_kw": "7.200", "start_soc_percent": "20",
            "soc_percent": "45", "price_terms": terms()}
    base.update(overrides)
    return base


EVENTS = [{"kind": "start_applied", "source": "device_sync", "observed_at": "2026-10-20T17:06:00Z"},
          {"kind": "stop_applied", "source": "device_sync", "observed_at": "2026-10-20T17:46:00Z"},
          {"kind": "ended", "source": "device_sync", "observed_at": "2026-10-20T17:46:00Z"}]


def facts(**overrides):
    base = {"session": session(), "station": {"name": "Posto A", "address": "Av. X, 10"},
            "point": {"public_code": "CG-7KQ2", "connector_type": "Tipo 2", "power_kw": "7.4"},
            "events": EVENTS, "samples": [], "sections": {}, "now": NOW}
    base.update(overrides)
    return base


def test_price_terms_snapshot_records_reason_schedule_and_coupon():
    snap = terms()
    assert snap["base_source"] == "schedule" and snap["schedule_window"] == "18:00–21:00"
    assert snap["demand"]["reason_label"].startswith("Alta demanda") and snap["demand"]["recorded"]
    assert snap["coupon"] == {"id": "c1", "code": "LOJA10", "discount_percent": 10}
    assert snap["connector_base_per_kwh"] == "1.0000" and snap["locked_by"] == "reservation"


def test_schedule_without_price_for_connector_is_connector_base():
    snap = terms(connector_id="other", base="1.0000")
    assert snap["base_source"] == "connector" and snap["schedule_window"] is None


def test_reservation_demand_snapshot_wins_over_status():
    demand = r.demand_snapshot(STATUS)
    snap = terms(status={"multiplier": "1.00", "factors": []}, demand=demand)
    assert snap["demand"]["reason_label"] == STATUS["reason_label"] and snap["demand"]["multiplier"] == "1.30"


def test_receipt_v1_explains_price_energy_and_charges():
    receipt = r.build_receipt(facts())
    assert receipt["schema"] == "chargegrid.receipt" and receipt["schema_version"] == 1
    assert receipt["final"] and receipt["number"] == "1A2B3C4D"
    keys = [line["key"] for line in receipt["price"]["lines"]]
    assert keys == ["connector_base", "schedule", "demand", "locked_price", "coupon"]
    text = " ".join(receipt["price"]["explanation"])
    assert "Tarifa do horário 18:00–21:00" in text and "1,3×" in text and "Ocupação agora: 3 de 4" in text
    assert "na reserva" in text and "Cupom LOJA10: −10%" in text
    assert receipt["energy"]["confirmed_by_device"] and receipt["energy"]["kwh"] == "10.000"
    assert receipt["charges"] == {"status": "final", "currency": "BRL", "energy_gross": "15.60", "discount": "1.56",
                                  "energy_total": "14.04", "overstay": None, "total": "14.04",
                                  "calculated_total": "14.04", "revenue_basis": "estimated",
                                  "note": "Valor estimado pela energia registrada; sem pagamento confirmado."}
    assert receipt["payment"]["status"] == "not_applicable" and receipt["overstay"]["status"] == "not_applicable"
    assert receipt["labels"]["simulated"]  # a flag continua; o texto visível não fala em simulação
    assert receipt["energy"]["source_label"] == "Energia calculada pelo equipamento"
    assert not any(re.search(r"simulad|\bdemo\b|demonstra|\bteste\b", note, re.IGNORECASE)
                   for note in receipt["labels"]["notes"])
    assert "Documento sem valor fiscal." in receipt["labels"]["notes"]
    assert receipt["times"]["end_reason_label"] == "Parada solicitada"
    assert receipt["times"]["duration_minutes"] == "40.0"


def test_legacy_session_without_terms_has_honest_fallback():
    receipt = r.build_receipt(facts(session=session(price_terms=None)))
    price = receipt["price"]
    assert not price["recorded"]
    assert [line["key"] for line in price["lines"]] == ["base", "demand", "locked_price", "coupon"]
    assert "motivo não registrado" in " ".join(price["explanation"])
    assert price["lines"][-1]["label"] == "Cupom (código não registrado)"


def test_active_session_is_provisional_and_unconfirmed():
    receipt = r.build_receipt(facts(session=session(status="charging", ended_at=None, end_reason=None),
                                    events=EVENTS[:1]))
    assert not receipt["final"] and receipt["charges"]["status"] == "provisional"
    assert receipt["energy"]["status"] == "pending" and not receipt["energy"]["confirmed_by_device"]


def test_finished_without_device_end_is_not_confirmed():
    receipt = r.build_receipt(facts(session=session(status="interrupted", end_reason="communication_lost"),
                                    events=EVENTS[:1]))
    assert not receipt["energy"]["confirmed_by_device"]
    assert "não foi confirmado" in receipt["energy"]["note"]


def test_measured_source_label():
    receipt = r.build_receipt(facts(session=session(source="measured")))
    assert receipt["labels"]["measurement"] == "measured" and not receipt["labels"]["simulated"]
    assert receipt["energy"]["source_label"] == "Energia medida pelo equipamento"


def test_power_curve_is_downsampled_ordered_and_has_start_limit():
    start = datetime(2026, 10, 20, 17, 6, tzinfo=UTC)
    samples = [{"captured_at": (start + timedelta(seconds=10 * i)).isoformat(), "power_w": 7000 + i % 3}
               for i in range(500)][::-1]
    samples.append({"captured_at": start.isoformat(), "power_w": None})
    power = r.build_receipt(facts(samples=samples))["power"]
    assert power["status"] == "available" and len(power["samples"]) == r.MAX_POWER_POINTS
    times = [point["t"] for point in power["samples"]]
    assert times == sorted(times) and times[0] == start.isoformat()
    assert power["sample_count"] == 500 and power["peak_kw"] == "7.00"
    assert power["changes"][0]["reason_code"] == "start_limit" and power["changes"][0]["status"] == "applied"


def test_power_without_samples_is_unavailable():
    power = r.build_receipt(facts())["power"]
    assert power["status"] == "unavailable" and "indisponíveis" in power["note"]


def test_sections_from_other_fronts_are_plugged():
    sections = {"payment": {"environment": "sandbox", "provider": "stripe", "provider_reference": "pi_123",
                            "net_amount": "14.04"},
                "overstay": {"amount": "2.00", "billable_minutes": 10},
                "power_changes": [{"at": "2026-10-20T17:20:00Z", "applied_kw": "3.600", "status": "applied",
                                   "reason_code": "rebalance", "reason_label": "Outro carro entrou"}],
                "forecast": {"note": "x"}}
    receipt = r.build_receipt(facts(sections=sections))
    assert receipt["payment"]["status"] == "available" and receipt["payment"]["provider_reference"] == "pi_123"
    assert receipt["labels"]["payment_environment"] == "sandbox"
    assert receipt["charges"]["overstay"] == "2.00" and receipt["charges"]["calculated_total"] == "16.04"
    assert receipt["charges"]["revenue_basis"] == "paid" and receipt["charges"]["paid_total"] == "14.04"
    # O capturado manda no total; a diferença para o calculado fica explícita.
    assert receipt["charges"]["total"] == "14.04" and receipt["charges"]["difference"] == "-2.00"
    assert receipt["charges"]["adjustments"] == [
        {"key": "other", "label": "Outra diferença entre o calculado e o capturado", "amount": "-2.00"}]
    assert receipt["power"]["changes"][0]["reason_code"] == "rebalance"
    assert receipt["extensions"] == {"forecast": {"note": "x"}}


def test_downsample_keeps_ends():
    assert r.downsample(list(range(10)), 3) == [0, 4, 9]
    assert r.downsample([1, 2], 120) == [1, 2]


def test_history_rows_and_totals_follow_me_summary_rule():
    rows = [r.history_row(session(), NOW),
            r.history_row(session(id="s2", status="failed", energy_wh="0", cost_estimate="0"), NOW),
            r.history_row(session(id="s3", status="interrupted", cost_estimate="1.2350", energy_wh="1000"), NOW)]
    assert rows[0]["total"] == "14.04" and rows[2]["total"] == "1.24"
    totals = r.history_totals(rows)
    assert totals == {"sessions": 2, "energy_kwh": "11.000", "total": "15.28", "sources": {"simulated": 2}}
    assert Decimal(rows[0]["energy_kwh"]) == Decimal("10.000")


def test_settled_payment_matching_energy_has_zero_difference():
    payment = {"environment": "sandbox", "status": "completed", "net_amount": "14.04", "provider_fee": "0.95",
               "waived_amount": "0.00", "uncollected_amount": "0.00"}
    receipt = r.build_receipt(facts(sections={"payment": payment}))
    charges = receipt["charges"]
    assert charges["total"] == charges["paid_total"] == charges["calculated_total"] == "14.04"
    assert charges["difference"] == "0.00" and charges["adjustments"] == [] and charges["note"] is None
    assert receipt["payment"]["status"] == "available" and receipt["payment"]["payment_status"] == "completed"


def test_capture_differences_are_explained_line_by_line():
    payment = {"net_amount": "12.00", "waived_amount": "2.04", "uncollected_amount": "0.00",
               "overstay_amount": "0.00"}
    charges = r.build_receipt(facts(sections={"payment": payment}))["charges"]
    assert (charges["calculated_total"], charges["total"], charges["difference"]) == ("14.04", "12.00", "-2.04")
    assert charges["adjustments"] == [{"key": "waived", "label": "Acima do valor pré-pago: não cobrado",
                                       "amount": "-2.04"}]
    assert "difere do calculado" in charges["note"] and "-R$ 2,04" in charges["note"]
    # Permanência cobrada no pagamento sem a seção de permanência (frente D ausente).
    payment = {"net_amount": "15.04", "overstay_amount": "1.00", "waived_amount": "0.00",
               "uncollected_amount": "0.00"}
    charges = r.build_receipt(facts(sections={"payment": payment}))["charges"]
    assert charges["adjustments"] == [{"key": "overstay", "label": "Taxa de permanência cobrada no pagamento",
                                       "amount": "1.00"}]


def test_confirmed_unsettled_payment_keeps_estimate():
    payment = {"environment": "sandbox", "status": "in_use", "net_amount": None}
    charges = r.build_receipt(facts(sections={"payment": payment}))["charges"]
    assert charges["revenue_basis"] == "estimated" and "paid_total" not in charges
    assert charges["total"] == "14.04" and charges["note"].startswith("Pagamento confirmado")


def test_receipt_total_and_capture_use_the_same_cent_rule():
    """Recibo (``cost_estimate`` → ``charged_amount``) e captura (``billing.energy_cents``) batem ao centavo."""
    from chargegrid_core import billing, economics

    for energy_wh in ("1", "125", "2500.5", "6200", "7333.333", "10005", "12345.678"):
        for price in ("0.0100", "1.2345", "1.5600", "2.0000", "2.5050"):
            for discount in (0, 10, 33, 50):
                estimate = (Decimal(energy_wh) / Decimal(1000) * Decimal(price) * Decimal(100 - discount)
                            / Decimal(100)).quantize(Decimal("0.0001"))  # como a API grava cost_estimate
                assert economics.charged_amount(estimate) == billing.money(
                    billing.energy_cents(energy_wh, price, discount)), (energy_wh, price, discount)


def test_applied_limits_follow_only_acknowledged_changes():
    changes = [{"at": "2026-10-20T17:06:00Z", "applied_kw": "7.200", "status": "applied",
                "confirmed_at": "2026-10-20T17:06:01Z"},
               {"at": "2026-10-20T17:20:00Z", "requested_kw": "4.000", "applied_kw": "4.000", "status": "applied",
                "confirmed_at": "2026-10-20T17:20:02Z"},
               {"at": "2026-10-20T17:30:00Z", "requested_kw": "7.200", "applied_kw": None, "status": "requested",
                "confirmed_at": None}]
    power = r.build_receipt(facts(sections={"power_changes": changes}))["power"]
    assert power["applied_limits"] == [{"t": "2026-10-20T17:06:01Z", "kw": "7.200"},
                                       {"t": "2026-10-20T17:20:02Z", "kw": "4.000"}]
