"""Recibo explicável, resultado do dono (margem) e exportações CSV/PDF."""

import csv
import io
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from test_http import clear_overrides, client_for, sync_payload
from test_pricing import busy  # noqa: F401 - fixture reutilizada

from app.models import ChargingSession, Connector, Coupon, Profile, Reservation, Station, Telemetry, now
from app.modules.economics import service as economics_service
from app.modules.pricing.service import current_terms, locked_terms
from app.modules.receipts import registry
from app.presence_code import current_code
from app.reports import pdf

DEVICE = {"Authorization": "Device test-key"}


@pytest.fixture(autouse=True)
def _cleanup():
    # Providers registered by the app (payment, power and overstay) are restored after each test.
    extras, sections = dict(registry._EXTRAS), dict(registry._SECTIONS)
    yield
    clear_overrides()
    for name in ("payment", "overstay", "power_changes", "broken"):
        registry.unregister(name)
    registry._EXTRAS.update(extras)
    registry._SECTIONS.update(sections)


def _code(factory, seed):
    with factory() as db:
        return current_code(db.get(Station, seed["station"]))[0]


def _sync(client, sequence, **changes):
    response = client.post("/v1/devices/sync", headers=DEVICE, json=sync_payload(sequence, **changes))
    assert response.status_code == 200, response.text
    return response.json()


def _charge(factory, seed, *, coupon=None, reserve=True, energy=(2500, 5000), power=(7200, 3600)):
    """Reserva (opcional), inicia, confirma no equipamento, envia potência e encerra."""
    client, _ = client_for(factory, seed["a"])
    sequence = iter(range(1, 100))
    body = {"presence_code": _code(factory, seed), "max_duration_minutes": 30}
    if reserve:
        reserved = client.post("/v1/reservations", headers={"Idempotency-Key": f"r-{uuid.uuid4()}"},
                               json={"connector_id": str(seed["point"])})
        assert reserved.status_code == 202, reserved.text
        command = _sync(client, next(sequence))["commands"][0]
        _sync(client, next(sequence), physical_state="reserved",
              acks=[{"command_id": command["id"], "status": "applied", "error": None}])
        body["reservation_id"] = reserved.json()["id"]
        body["presence_code"] = _code(factory, seed)
    if coupon:
        body["coupon_code"] = coupon
    started = client.post("/v1/charging-sessions", headers={"Idempotency-Key": f"s-{uuid.uuid4()}"}, json=body)
    assert started.status_code == 202, started.text
    session_id = started.json()["id"]
    state = "reserved" if reserve else "idle"
    command = _sync(client, next(sequence), physical_state=state)["commands"][0]
    _sync(client, next(sequence), physical_state="charging", connected=True, session_id=session_id,
          energy_wh=energy[0], power_w=power[0], acks=[{"command_id": command["id"], "status": "applied"}])
    with factory.begin() as db:  # amostra extra 30 s depois (a API grava no máximo a cada 30 s)
        db.add(Telemetry(device_id=seed["device"], session_id=session_id, boot_id="http-boot", sequence=50,
                         captured_at=now() + timedelta(seconds=30), data={"power_w": power[1]}))
    stopped = client.post(f"/v1/charging-sessions/{session_id}/stop", headers={"Idempotency-Key": f"x-{session_id}"})
    assert stopped.status_code == 202
    stop = _sync(client, next(sequence), physical_state="charging", connected=True, session_id=session_id,
                 energy_wh=energy[0], power_w=power[1])["commands"][0]
    _sync(client, next(sequence), physical_state="stopped", session_id=session_id, energy_wh=energy[1], power_w=0,
          end_reason="requested", acks=[{"command_id": stop["id"], "status": "applied"}])
    return client, session_id


def _coupon(factory, seed, code="LOJA10", percent=10):
    with factory.begin() as db:
        db.add(Coupon(operator_id=seed["owner"], station_id=seed["station"], code=code, description="Loja",
                      discount_percent=percent, valid_until=now() + timedelta(days=1)))


def _set_cost(factory, seed, value="0.8000"):
    owner, _ = client_for(factory, seed["owner"])
    response = owner.put(f"/v1/stations/{seed['station']}/economics", json={"energy_cost_per_kwh": value})
    assert response.status_code == 200, response.text
    return response.json()


def test_full_flow_receipt_explains_price_energy_power_and_charges(factory, seed):
    _coupon(factory, seed)
    _set_cost(factory, seed)
    client, session_id = _charge(factory, seed, coupon="loja10")
    public = client.get(f"/v1/charging-sessions/{session_id}").json()
    for key in ("price_terms", "energy_cost_per_kwh", "platform_fee_percent"):
        assert key not in public  # formato da sessão não muda e o custo do dono não vai ao motorista
    response = client.get(f"/v1/charging-sessions/{session_id}/receipt")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    receipt = response.json()
    assert receipt["schema"] == "chargegrid.receipt" and receipt["schema_version"] == 1 and receipt["final"]
    price = receipt["price"]
    assert price["recorded"] and price["locked_by"] == "reservation"
    assert price["coupon"] == {"code": "LOJA10", "discount_percent": 10}
    assert [line["key"] for line in price["lines"]] == ["power_tier", "base", "demand", "locked_price", "coupon"]
    assert "Cupom LOJA10: −10%" in " ".join(price["explanation"])
    energy = receipt["energy"]
    assert energy["kwh"] == "5.000" and energy["confirmed_by_device"] and energy["source"] == "simulated"
    # 5 kWh × R$ 2,00 = 10,00; cupom 10 % = 1,00; total 9,00 (= cost_estimate ao centavo).
    assert receipt["charges"]["energy_gross"] == "10.00" and receipt["charges"]["discount"] == "1.00"
    assert receipt["charges"]["total"] == "9.00" and public["cost_estimate"] == "9.0000"
    assert receipt["power"]["status"] == "available"
    curve = [point["kw"] for point in receipt["power"]["samples"]]
    assert {"7.20", "3.60"} <= set(curve) and receipt["power"]["peak_kw"] == "7.20"
    assert receipt["power"]["changes"][0]["reason_code"] == "start_limit"
    kinds = [event["kind"] for event in receipt["timeline"]]
    assert "start_applied" in kinds and "ended" in kinds
    assert receipt["payment"]["status"] == "not_applicable"
    assert receipt["labels"]["simulated"] and receipt["labels"]["payment_environment"] == "none"
    with factory() as db:
        session = db.get(ChargingSession, session_id)
        assert session.energy_cost_per_kwh == Decimal("0.8000") and session.platform_fee_percent == Decimal("25.00")
        assert session.price_terms["coupon"]["code"] == "LOJA10"
        reservation = db.get(Reservation, session.reservation_id)
        assert reservation.price_terms["locked_by"] == "reservation"
    _set_cost(factory, seed, "5.0000")  # mudar o custo depois não reescreve a recarga
    owner, _ = client_for(factory, seed["owner"])
    margin = owner.get("/v1/owner/margin").json()
    row = next(item for item in margin["items"] if item["session_id"] == session_id)
    assert row["energy_cost_per_kwh"] == "0.8000" and row["cost_basis"] == "snapshot"
    assert (row["revenue"], row["platform_fee"], row["owner_net"], row["energy_cost"], row["margin"]) == \
        ("9.00", "2.25", "6.75", "4.00", "2.75")
    assert row["coupon_code"] == "LOJA10" and row["discount"] == "1.00"


def test_receipt_pdf_contains_honest_labels(factory, seed, monkeypatch):
    client, session_id = _charge(factory, seed, reserve=False)
    monkeypatch.setattr(pdf, "COMPRESS", False)
    response = client.get(f"/v1/charging-sessions/{session_id}/receipt.pdf")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"].startswith('attachment; filename="chargegrid-recibo-')
    body = response.content
    assert body.startswith(b"%PDF") and b"%%EOF" in body[-64:]
    for text in (b"Recibo de recarga", b"SIMULADO", b"Documento sem valor fiscal", b"Pre\\347o travado"):
        assert text in body, text


def test_receipt_is_only_for_the_session_owner(factory, seed):
    _, session_id = _charge(factory, seed, reserve=False)
    for user in ("b", "owner"):
        other, _ = client_for(factory, seed[user])
        assert other.get(f"/v1/charging-sessions/{session_id}/receipt").status_code == 404
        assert other.get(f"/v1/charging-sessions/{session_id}/receipt.pdf").status_code == 404
    assert other.get(f"/v1/charging-sessions/{uuid.uuid4()}/receipt").status_code == 404


def test_legacy_session_receipt_has_fallback(factory, seed):
    with factory.begin() as db:
        legacy = ChargingSession(user_id=seed["a"], connector_id=seed["point"], status="completed",
                                 started_at=now() - timedelta(hours=1), ended_at=now(), max_duration_minutes=30,
                                 price_per_kwh=Decimal("2.6000"), base_price_per_kwh=Decimal("2.0000"),
                                 demand_multiplier=Decimal("1.30"), discount_percent=5, energy_wh=Decimal(1000),
                                 cost_estimate=Decimal("2.4700"), source="measured")
        db.add(legacy)
        db.flush()
        legacy_id = legacy.id
    client, _ = client_for(factory, seed["a"])
    receipt = client.get(f"/v1/charging-sessions/{legacy_id}/receipt").json()
    assert not receipt["price"]["recorded"]
    assert "motivo não registrado" in " ".join(receipt["price"]["explanation"])
    assert receipt["price"]["lines"][-1]["label"] == "Cupom (código não registrado)"
    assert receipt["energy"]["status"] == "available" and not receipt["energy"]["confirmed_by_device"]
    assert receipt["power"]["status"] == "unavailable" and receipt["charges"]["total"] == "2.47"


def test_start_without_reservation_records_the_demand_reason(factory, busy):  # noqa: F811
    seed = busy
    client, _ = client_for(factory, seed["a"])
    started = client.post("/v1/charging-sessions", headers={"Idempotency-Key": "reason-start"},
                          json={"public_code": "CG-01", "presence_code": _code(factory, seed)})
    assert started.status_code == 202, started.text
    with factory() as db:
        session = db.get(ChargingSession, started.json()["id"])
        terms = session.price_terms
    assert terms["locked_by"] == "start" and terms["demand"]["recorded"]
    assert Decimal(terms["demand"]["multiplier"]) == session.demand_multiplier > 1
    assert terms["demand"]["reason_label"].startswith(("Alta demanda", "Demanda muito alta"))
    occupancy = next(f for f in terms["demand"]["factors"] if f["key"] == "occupancy")
    assert occupancy["value"] == "1 de 2"
    receipt = client.get(f"/v1/charging-sessions/{session.id}/receipt").json()
    assert not receipt["final"] and receipt["charges"]["status"] == "provisional"
    assert any(line["key"] == "demand" and line["unit"] == "×" and Decimal(line["value"]) > 1
               for line in receipt["price"]["lines"])


def test_locked_terms_match_current_terms(factory, busy):  # noqa: F811
    seed = busy
    with factory.begin() as db:
        connector = db.get(Connector, seed["point"])
        base, multiplier, terms = locked_terms(db, connector)
        assert (base, multiplier) == current_terms(db, connector)
        reservation = Reservation(user_id=seed["a"], connector_id=connector.id, status="confirmed",
                                  confirmation_deadline=now(), demand_multiplier=Decimal("1.15"),
                                  created_at=now() - timedelta(minutes=5))
        db.add(reservation)
        db.flush()
        locked = locked_terms(db, connector, reservation)
        assert locked[:2] == current_terms(db, connector, reservation)
        assert locked[2]["locked_by"] == "reservation" and not locked[2]["demand"]["recorded"]


def test_station_economics_get_put_and_privacy(factory, seed):
    owner, _ = client_for(factory, seed["owner"])
    url = f"/v1/stations/{seed['station']}/economics"
    initial = owner.get(url)
    assert initial.status_code == 200 and initial.headers["cache-control"] == "no-store"
    assert initial.json()["energy_cost_per_kwh"] is None and initial.json()["platform_fee_percent"] == "25.00"
    assert initial.json()["fee_editable"] is False
    saved = owner.put(url, json={"energy_cost_per_kwh": "0,85"})
    assert saved.status_code == 200 and saved.json()["energy_cost_per_kwh"] == "0.8500"
    for body, code in (({"energy_cost_per_kwh": "-1"}, "invalid_economics"),
                       ({"energy_cost_per_kwh": "abc"}, "invalid_economics"),
                       ({"platform_fee_percent": "10"}, "fee_read_only"),
                       ({"foo": 1}, "invalid_economics")):
        response = owner.put(url, json=body)
        assert response.status_code == 422 and response.json()["error"]["code"] == code, body
    cleared = owner.put(url, json={"energy_cost_per_kwh": None})
    assert cleared.json()["energy_cost_per_kwh"] is None
    driver, _ = client_for(factory, seed["a"])
    assert driver.get(url).status_code in (403, 404)
    assert driver.put(url, json={"energy_cost_per_kwh": "1"}).status_code in (403, 404)
    public = driver.get(f"/v1/stations/{seed['station']}").json()
    assert "energy_cost_per_kwh" not in public and "platform_fee_percent" not in public


@pytest.fixture
def margin_data(factory, seed):
    """Sessões com frações de centavo, um rival e uma sessão fora da janela."""
    moment = now().replace(microsecond=0)
    start = moment - timedelta(days=2)
    with factory.begin() as db:
        rival = Profile(id=uuid.uuid4(), name="Rival", operator_enabled=True)
        db.add(rival)
        db.flush()
        rival_station = Station(owner_id=rival.id, name="Rival", address="Outro", latitude=1, longitude=1)
        db.add(rival_station)
        db.flush()
        rival_point = Connector(station_id=rival_station.id, public_code="RIVAL-01", connector_type="CCS2",
                                power_kw=50, price_per_kwh=3)
        second_station = Station(owner_id=seed["owner"], name="Segundo", address="Rua 2", latitude=0, longitude=0,
                                 energy_cost_per_kwh=Decimal("0.5000"), platform_fee_percent=Decimal("20"))
        db.add_all([rival_point, second_station])
        db.flush()
        second_point = Connector(station_id=second_station.id, public_code="CG-S2", connector_type="Tipo 2",
                                 power_kw=7, price_per_kwh=Decimal("1.0050"))
        db.add(second_point)
        db.flush()
        db.get(Station, seed["station"]).energy_cost_per_kwh = Decimal("0.8000")

        def add(point, cost, energy, minutes_ago, status="completed", **extra):
            db.add(ChargingSession(user_id=seed["a"], connector_id=point, status=status,
                                   created_at=moment - timedelta(minutes=minutes_ago + 30),
                                   started_at=moment - timedelta(minutes=minutes_ago + 20),
                                   ended_at=moment - timedelta(minutes=minutes_ago), max_duration_minutes=60,
                                   price_per_kwh=extra.pop("price", Decimal("1.0050")), energy_wh=Decimal(energy),
                                   cost_estimate=Decimal(cost), source="simulated", **extra))

        add(seed["point"], "1.0050", 1000, 60)
        add(seed["point"], "1.0050", 1000, 120, platform_fee_percent=Decimal("25"),
            energy_cost_per_kwh=Decimal("0.7000"))
        add(seed["point"], "2.6000", 1000, 180, price=Decimal("2.6000"), base_price_per_kwh=Decimal("2.0000"),
            demand_multiplier=Decimal("1.30"))
        add(second_point.id, "1.0050", 1000, 240)
        add(seed["point"], "0", 0, 300, status="failed")
        add(seed["point"], "9.0000", 9000, 60 * 24 * 5)  # fora da janela
        add(rival_point.id, "150.0000", 50000, 60)
    return {**seed, "start": start, "end": moment, "rival_station": rival_station.id,
            "second_station": second_station.id}


def _window(data, **extra):
    return {"from": data["start"].isoformat(), "to": data["end"].isoformat(), **extra}


def test_margin_revenue_equals_overview_revenue_to_the_cent(factory, margin_data):
    owner, _ = client_for(factory, margin_data["owner"])
    overview = owner.get("/v1/owner/overview", params=_window(margin_data)).json()
    margin = owner.get("/v1/owner/margin", params=_window(margin_data)).json()
    # Por sessão ao centavo: 1,01 + 1,01 + 2,60 + 1,01 = 5,63 (a soma bruta daria 5,6150 → 5,62).
    assert overview["kpis"]["revenue"] == margin["totals"]["revenue"] == "5.63"
    assert margin["totals"]["sessions"] == overview["kpis"]["sessions"] == 4
    series = owner.get("/v1/owner/timeseries", params=_window(margin_data)).json()
    assert sum(Decimal(value) for value in series["series"]["revenue"]) == Decimal("5.63")
    ranking = sum(Decimal(item["revenue"]) for item in overview["ranking"])
    assert ranking == Decimal("5.63")


def test_margin_report_totals_effects_stations_and_basis(factory, margin_data):
    owner, _ = client_for(factory, margin_data["owner"])
    response = owner.get("/v1/owner/margin", params=_window(margin_data))
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    report = response.json()
    totals = report["totals"]
    assert report["schema_version"] == 1 and report["basis"] == "ended_at" and report["total"] == 4
    assert totals["coverage"] == {"sessions": 4, "with_energy_cost": 4, "missing_energy_cost": 0}
    # Comissões: 25 % de 1,01 (0,25) ×2, 25 % de 2,60 (0,65), 20 % de 1,01 (0,20).
    assert totals["platform_fee"] == "1.35" and totals["owner_net"] == "4.28"
    # Custos: 0,80 (atual) + 0,70 (travado) + 0,80 (atual) + 0,50 (segundo posto).
    assert totals["energy_cost"] == "2.80" and totals["margin"] == "1.48"
    assert report["dynamic_pricing"]["sessions_with_increase"] == 1
    assert report["dynamic_pricing"]["demand_effect"] == "0.60"
    bases = sorted(item["cost_basis"] for item in report["items"])
    assert bases == ["current", "current", "current", "snapshot"]
    assert {item["station_name"] for item in report["by_station"]} == {"Demo", "Segundo"}
    assert any("simulada" in warning for warning in report["warnings"])
    assert report["methodology"][0].startswith("Receita bruta não é lucro")
    page = owner.get("/v1/owner/margin", params=_window(margin_data, limit=1, offset=1)).json()
    assert len(page["items"]) == 1 and page["totals"] == totals and page["total"] == 4


def test_margin_without_energy_cost_has_no_total_margin(factory, margin_data):
    owner, _ = client_for(factory, margin_data["owner"])
    owner.put(f"/v1/stations/{margin_data['station']}/economics", json={"energy_cost_per_kwh": None})
    report = owner.get("/v1/owner/margin", params=_window(margin_data)).json()
    assert report["totals"]["margin"] is None
    assert report["totals"]["coverage"]["missing_energy_cost"] == 2
    assert any("sem custo da energia" in warning for warning in report["warnings"])


def test_margin_scope_and_station_filter(factory, margin_data):
    owner, _ = client_for(factory, margin_data["owner"])
    second = owner.get("/v1/owner/margin", params=_window(margin_data, station_id=margin_data["second_station"]))
    assert second.json()["totals"]["revenue"] == "1.01" and second.json()["total"] == 1
    assert owner.get("/v1/owner/margin", params=_window(margin_data, station_id=margin_data["rival_station"])
                     ).status_code == 404
    driver, _ = client_for(factory, margin_data["a"])
    assert driver.get("/v1/owner/margin").status_code == 403
    assert driver.get("/v1/owner/export/margin.csv").status_code == 403


def test_margin_csv_and_pdf_match_the_screen(factory, margin_data, monkeypatch):
    owner, _ = client_for(factory, margin_data["owner"])
    report = owner.get("/v1/owner/margin", params=_window(margin_data)).json()
    exported = owner.get("/v1/owner/export/margin.csv", params=_window(margin_data))
    assert exported.status_code == 200 and exported.headers["content-type"].startswith("text/csv")
    assert exported.headers["cache-control"] == "no-store"
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert len(rows) == report["total"]
    for column, key in (("Receita cobrada (R$)", "revenue_total"), ("Comissão da plataforma (R$)", "platform_fee"),
                        ("Repasse ao dono (R$)", "owner_net"), ("Custo estimado da energia (R$)", "energy_cost"),
                        ("Margem estimada (R$)", "margin")):
        assert sum(Decimal(row[column]) for row in rows) == Decimal(report["totals"][key]), column
    monkeypatch.setattr(pdf, "COMPRESS", False)
    document = owner.get("/v1/owner/export/margin.pdf", params=_window(margin_data))
    assert document.status_code == 200 and document.content.startswith(b"%PDF")
    assert b"Receita bruta n\\343o \\351 lucro" in document.content
    assert b"R$ 1,48" in document.content and b"R$ 5,63" in document.content


def test_margin_export_refuses_too_many_sessions(factory, margin_data, monkeypatch):
    monkeypatch.setattr(economics_service, "EXPORT_LIMIT", 2)
    owner, _ = client_for(factory, margin_data["owner"])
    response = owner.get("/v1/owner/export/margin.csv", params=_window(margin_data))
    assert response.status_code == 413 and response.json()["error"]["code"] == "export_too_large"


def test_driver_history_export_is_scoped_and_totals_match(factory, margin_data, monkeypatch):
    driver, _ = client_for(factory, margin_data["a"])
    exported = driver.get("/v1/me/charging-sessions/export.csv", params=_window(margin_data))
    assert exported.status_code == 200 and exported.headers["cache-control"] == "no-store"
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    # As 4 do dono + a rival (outro posto, mesma motorista) + a falha; a de 5 dias fica fora.
    assert len(rows) == 6 and {row["Posto"] for row in rows} == {"Demo", "Segundo", "Rival"}
    monkeypatch.setattr(pdf, "COMPRESS", False)
    document = driver.get("/v1/me/charging-sessions/export.pdf", params=_window(margin_data))
    assert document.status_code == 200 and document.content.startswith(b"%PDF")
    # 5,63 dos postos do dono + 150,00 da rival.
    assert b"R$ 155,63" in document.content
    invalid = driver.get("/v1/me/charging-sessions/export.csv",
                         params={"from": margin_data["end"].isoformat(), "to": margin_data["start"].isoformat()})
    assert invalid.status_code == 422
    assert driver.get("/v1/me/charging-sessions/export.xlsx").status_code == 422
    other, _ = client_for(factory, margin_data["b"])  # client_for troca o usuário do app inteiro
    assert list(csv.DictReader(io.StringIO(other.get("/v1/me/charging-sessions/export.csv").text))) == []


def test_other_fronts_plug_payment_overstay_and_power_changes(factory, seed):
    _set_cost(factory, seed)
    client, session_id = _charge(factory, seed, reserve=False)

    def payment(db, sessions):
        return {session.id: {"environment": "sandbox", "provider": "stripe", "provider_reference": "pi_test",
                             "net_amount": "10.00", "provider_fee": "0.40", "captured_amount": "10.00"}
                for session in sessions}

    def overstay(db, sessions):
        return {session.id: {"amount": "2.00", "billable_minutes": 10} for session in sessions}

    def broken(db, session):
        raise RuntimeError("falha de outra frente")

    registry.register_extras("payment", payment)
    registry.register_extras("overstay", overstay)
    registry.register_section("power_changes", lambda db, session: [
        {"at": now().isoformat(), "applied_kw": "3.600", "status": "applied", "reason_code": "rebalance",
         "reason_label": "Outro carro entrou"}])
    registry.register_section("broken", broken)
    receipt = client.get(f"/v1/charging-sessions/{session_id}/receipt").json()
    assert receipt["payment"]["provider_reference"] == "pi_test"
    assert receipt["labels"]["payment_environment"] == "sandbox"
    assert receipt["charges"]["overstay"] == "2.00" and receipt["charges"]["paid_total"] == "10.00"
    assert receipt["power"]["changes"][0]["reason_code"] == "rebalance"
    assert "broken" not in receipt.get("extensions", {})
    owner, _ = client_for(factory, seed["owner"])
    row = next(item for item in owner.get("/v1/owner/margin").json()["items"] if item["session_id"] == session_id)
    assert row["revenue_basis"] == "captured" and row["revenue_total"] == "10.00"
    assert row["overstay_revenue"] == "2.00" and row["provider_fee"] == "0.40"
    assert row["platform_fee"] == "2.50" and row["owner_net"] == "7.10"
