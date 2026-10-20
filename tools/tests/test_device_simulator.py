from datetime import datetime, timedelta, timezone

from tools.device_simulator import Device


def response(kind="START", version=1, identifier="command"):
    now = datetime.now(timezone.utc)
    return {
        "server_time": now.isoformat(),
        "control_version": version,
        "sync_interval_seconds": 5,
        "authorized": {
            "reservation": None,
            "session": {
                "id": "session",
                "max_duration_minutes": 60,
                "max_cost": None,
                "price_per_kwh": 2,
                "discount_percent": 0,
            },
        },
        "commands": [
            {
                "id": identifier,
                "type": kind,
                "version": version,
                "expires_at": (now + timedelta(minutes=1)).isoformat(),
                "session_id": "session",
                "reservation_id": None,
                "parameters": {},
            }
        ],
    }


def test_duplicate_start_does_not_reset_energy():
    now = [0]
    device = Device(clock=lambda: now[0])
    device.response(response())
    now[0] = 10
    device.tick()
    energy = device.energy
    device.response(response())
    assert device.energy == energy == 20
    assert device.state == "charging"


def test_offline_stop_caps_energy_and_reconciles(tmp_path):
    now = [0]
    device = Device(tmp_path / "state.json", clock=lambda: now[0])
    device.response(response())
    now[0] = 60
    device.tick()
    assert device.state == "stopped"
    assert device.reason == "communication_lost"
    assert device.energy == 90
    restarted = Device(tmp_path / "state.json", clock=lambda: now[0])
    restarted.response(response())
    assert restarted.session_id == "session"
    assert restarted.state == "stopped"
    assert restarted.energy == 90
    assert restarted.acks[0]["status"] == "failed"


def test_expired_and_older_commands_do_not_start():
    device = Device()
    data = response()
    data["commands"][0]["expires_at"] = "2000-01-01T00:00:00Z"
    device.response(data)
    assert device.state == "idle"
    data = response(version=2)
    data["commands"][0]["version"] = 1
    device.response(data)
    assert device.state == "idle"


def test_stop_wrong_session_fails():
    device = Device()
    device.response(response())
    data = response(kind="STOP", version=2, identifier="stop")
    data["commands"][0]["session_id"] = "other"
    device.response(data)
    assert device.state == "charging"
    assert device.acks[0]["status"] == "failed"


def test_duration_and_cost_limits():
    now = [0]
    device = Device(clock=lambda: now[0])
    data = response()
    data["authorized"]["session"]["max_duration_minutes"] = 0.5
    device.response(data)
    now[0] = 31
    device.tick()
    assert device.reason == "duration_limit"
    assert device.energy == 60
    device = Device(clock=lambda: now[0])
    data = response()
    data["authorized"]["session"]["max_cost"] = 0.01
    device.response(data)
    now[0] += 10
    device.tick()
    assert device.reason == "cost_limit"
    assert device.energy == 5


def test_new_session_after_server_reconciliation():
    device = Device()
    device.response(response())
    device.stop("requested")
    data = response(version=2, identifier="new")
    data["authorized"]["session"]["id"] = "new-session"
    data["commands"][0]["session_id"] = "new-session"
    device.response(data)
    assert device.state == "charging"
    assert device.session_id == "new-session"
    assert device.energy == 0


def test_reservation_ttl_updates_on_every_sync():
    device = Device()
    data = response(kind="RESERVE")
    expiry = datetime.now(timezone.utc) + timedelta(seconds=30)
    data["authorized"] = {
        "session": None,
        "reservation": {"id": "reservation", "expires_at": expiry.isoformat()},
    }
    data["commands"][0]["reservation_id"] = "reservation"
    device.response(data)
    assert device.state == "reserved"
    expiry += timedelta(minutes=10)
    data["authorized"]["reservation"]["expires_at"] = expiry.isoformat()
    data["commands"] = []
    device.response(data)
    assert device.reservation_expires == expiry.timestamp()


def soc_start(source="simulated", soc=50, battery="60.00"):
    data = response()
    data["commands"][0]["parameters"] = {"soc_percent": soc, "battery_kwh": battery, "soc_source": source}
    return data


def test_legacy_start_keeps_bench_soc_without_battery_stop():
    now = [0]
    device = Device(clock=lambda: now[0])
    device.response(response())
    now[0] = 10
    payload = device.payload()
    assert device.soc_source is None and not device.soc_known()
    assert payload["soc_percent"] is None


def test_simulated_soc_rises_with_energy_and_ignores_api_echo():
    now = [0]
    device = Device(clock=lambda: now[0])
    device.response(soc_start())
    now[0] = 10
    assert device.payload()["soc_percent"] == round(50 + 20 / 600, 2)
    sync = soc_start()
    sync["commands"] = []
    sync["authorized"]["session"]["soc_percent"] = 12
    device.response(sync)
    assert device.soc() == 50 + 20 / 600


def test_simulated_battery_full_stops_locally(tmp_path):
    now = [0]
    device = Device(tmp_path / "state.json", clock=lambda: now[0])
    device.response(soc_start(soc=99.9, battery=10))
    now[0] = 10
    payload = device.payload()
    assert device.state == "stopped" and device.reason == "battery_full"
    assert payload["end_reason"] == "battery_full" and payload["soc_percent"] == 100
    assert abs(device.energy - 10) < 1e-6
    restarted = Device(tmp_path / "state.json", clock=lambda: now[0])
    assert restarted.soc_source == "simulated" and restarted.soc() == 100


def test_phone_soc_passthrough_and_battery_full_stop():
    now = [0]
    device = Device(clock=lambda: now[0])
    device.response(soc_start(source="phone", soc=40))
    now[0] = 10
    assert device.payload()["soc_percent"] is None and device.soc() == 40
    sync = soc_start(source="phone", soc=40)
    sync["commands"] = []
    sync["authorized"]["session"].update(soc_source="phone", soc_percent="63.50")
    device.response(sync)
    now[0] = 20
    payload = device.payload()
    assert payload["soc_percent"] is None and device.soc() == 63.5 and device.state == "charging"
    stop = response(kind="STOP", version=2, identifier="stop-full")
    stop["commands"][0]["parameters"] = {"reason": "battery_full"}
    device.response(stop)
    assert device.state == "stopped" and device.reason == "battery_full"


def test_phone_source_switch_mid_session():
    device = Device()
    device.response(soc_start())
    sync = soc_start()
    sync["commands"] = []
    sync["authorized"]["session"].update(soc_source="phone", soc_percent=100)
    device.response(sync)
    assert device.soc() == 100 and device.state == "charging"  # A API decide a parada.
    stop = response(kind="STOP", version=2, identifier="stop")
    device.response(stop)
    assert device.reason == "battery_full"


def test_start_power_limit_caps_simulated_power():
    now = [0]
    device = Device(clock=lambda: now[0])
    data = response()
    data["commands"][0]["parameters"] = {"max_power_kw": 3.6}
    device.response(data)
    now[0] = 10
    payload = device.payload()
    assert payload["power_w"] == 3600
    assert payload["energy_wh"] == 10  # 3.6 kW for 10 s
    # Older API (no field): bench rating; a limit above the rating keeps the rating.
    legacy = Device(clock=lambda: 0)
    legacy.response(response())
    assert legacy.payload()["power_w"] == 7200
    above = Device(clock=lambda: 0)
    data = response()
    data["authorized"]["session"]["max_power_kw"] = "60.0"
    above.response(data)
    assert above.payload()["power_w"] == 7200


def _start_then(device, now, command):
    device.response(response())
    now[0] = 1
    later = response(kind=command["type"], version=2, identifier=command["id"])
    later["commands"][0]["parameters"] = command.get("parameters", {})
    return device.response(later)


def test_payload_declares_live_power_capability_and_applied_power():
    now = [0]
    device = Device(clock=lambda: now[0])
    device.response(response())
    body = device.payload()
    assert body["capabilities"] == ["set_power_v1"]
    assert body["applied_power_w"] == 7200
    assert body["charger"]["model"] == "simulated_bench" and body["charger"]["transport"] == "simulated"
    legacy = Device(clock=lambda: now[0], legacy=True)
    assert "capabilities" not in legacy.payload() and legacy.payload()["firmware_version"] == "0.4.0"


def test_set_power_applies_acks_and_integrates_energy_at_new_power():
    now = [0]
    device = Device(clock=lambda: now[0])
    _start_then(device, now, {"type": "SET_POWER", "id": "p1", "parameters": {"power_limit_w": 3600}})
    assert device.acks == [{"command_id": "p1", "status": "applied", "error": None, "applied_power_w": 3600}]
    energy = device.energy
    now[0] = 41
    device.tick()
    assert round(device.energy - energy, 3) == 40.0  # 40 s a 3,6 kW
    # Reentrega do mesmo comando: confirma de novo com o valor aplicado.
    again = response(kind="SET_POWER", version=2, identifier="p1")
    device.response(again)
    assert device.acks[0]["applied_power_w"] == 3600


def test_zero_power_pauses_without_energy_or_errors():
    now = [0]
    device = Device(clock=lambda: now[0])
    _start_then(device, now, {"type": "SET_POWER", "id": "p0", "parameters": {"power_limit_w": 0}})
    energy = device.energy
    now[0] = 40
    device.tick()
    assert device.state == "charging" and device.energy == energy
    assert device.payload()["applied_power_w"] == 0


def test_start_with_power_limit_w_zero_begins_paused():
    now = [0]
    device = Device(clock=lambda: now[0])
    start = response()
    start["commands"][0]["parameters"] = {"power_limit_w": 0, "max_power_kw": 6.0}
    device.response(start)
    assert device.state == "charging" and device.power_w == 0


def test_legacy_firmware_rejects_set_power_as_unknown():
    now = [0]
    device = Device(clock=lambda: now[0], legacy=True)
    _start_then(device, now, {"type": "SET_POWER", "id": "p1", "parameters": {"power_limit_w": 3600}})
    assert device.acks == [{"command_id": "p1", "status": "failed", "error": "unknown_command"}]
    assert device.power_w == 7200


def test_set_power_without_session_fails():
    now = [0]
    device = Device(clock=lambda: now[0])
    command = response(kind="SET_POWER")
    command["commands"][0]["parameters"] = {"power_limit_w": 3000}
    device.response(command)
    assert device.acks[0]["status"] == "failed" and device.acks[0]["error"] == "no_active_session"


def _overstay_start(**parameters):
    data = response()
    data["commands"][0]["parameters"] = {"overstay": {"grace_minutes": 10, "interval_minutes": 1,
                                                      "amount": "1.00", "max_amount": "30.00"}, **parameters}
    return data


def test_stop_without_overstay_terms_still_unplugs():
    device = Device()
    device.response(response())
    device.response(response(kind="STOP", version=2, identifier="stop"))
    assert device.state == "stopped" and device.connected is False


def test_overstay_terms_keep_the_cable_until_unplug():
    now = [0]
    device = Device(clock=lambda: now[0], unplug_after=None)
    device.response(_overstay_start())
    device.response(response(kind="STOP", version=2, identifier="stop"))
    assert device.state == "stopped" and device.connected is True
    assert device.payload()["connected"] is True
    now[0] = 10_000
    device.tick()
    assert device.connected is True  # manual only
    assert device.unplug() is True and device.connected is False and device.unplug() is False


def test_unplug_after_and_never_while_charging():
    now = [0]
    device = Device(clock=lambda: now[0], unplug_after=30)
    device.response(_overstay_start())
    assert device.unplug() is False and device.connected is True  # charging
    now[0] = 5
    device.response(response(kind="STOP", version=2, identifier="stop"))
    now[0] = 34
    device.tick()
    assert device.connected is True
    now[0] = 35
    device.tick()
    assert device.connected is False


def test_legacy_firmware_ignores_overstay_terms():
    device = Device(legacy=True)
    device.response(_overstay_start())
    device.response(response(kind="STOP", version=2, identifier="stop"))
    assert device.connected is False


def test_reboot_reports_the_cable_disconnected(tmp_path):
    now = [0]
    device = Device(tmp_path / "state.json", clock=lambda: now[0], unplug_after=None)
    device.response(_overstay_start())
    device.response(response(kind="STOP", version=2, identifier="stop"))
    assert device.connected is True
    restarted = Device(tmp_path / "state.json", clock=lambda: now[0])
    assert restarted.connected is False


def test_overstay_terminal_text_matches_the_panel():
    from tools.device_simulator import overstay_text

    assert overstay_text(None) == ""
    assert overstay_text({"status": "grace", "grace_remaining_seconds": 462}).endswith("desconecte em 07:42")
    assert overstay_text({"status": "billing", "fee_due": "3.00"}).endswith("Taxa de permanência: R$ 3,00")
    assert overstay_text({"status": "no_fee"}).endswith("desconecte o cabo")


def test_payload_reports_the_panel_firmware_version():
    from pathlib import Path

    runtime = (Path(__file__).resolve().parents[2] / "firmware/esp32/include/runtime.h").read_text()
    assert '#define CHARGEGRID_FIRMWARE_VERSION "0.7.0"' in runtime
    assert Device().payload()["firmware_version"] == "0.7.0"
    assert Device(legacy=True).payload()["firmware_version"] == "0.4.0"


def test_real_api_timestamps_with_a_local_offset_still_apply():
    # The API serialises DB timestamps in the PostgreSQL session time zone (e.g. -03:00).
    data = response()
    server = datetime(2026, 10, 20, 7, 9, 20, 765272, tzinfo=timezone.utc)
    data["server_time"] = server.isoformat()
    data["commands"][0]["expires_at"] = (server + timedelta(seconds=30)).astimezone(
        timezone(timedelta(hours=-3))).isoformat()
    assert data["commands"][0]["expires_at"] == "2026-10-20T04:09:50.765272-03:00"
    device = Device()
    assert device.response(data) and device.state == "charging"
    expired = response(version=2, identifier="late")
    expired["server_time"] = server.isoformat()
    expired["commands"][0]["expires_at"] = (server - timedelta(seconds=1)).astimezone(
        timezone(timedelta(hours=-3))).isoformat()
    assert not Device().response(expired)


def _kiosk(connector):
    data = response()
    data["authorized"]["session"] = None
    data["commands"] = []
    data["connector"] = {"public_code": "CG-01", "owned": True, "active": True, **connector}
    return data


def test_kiosk_fields_from_the_real_sync_are_read_like_the_panel():
    from tools.device_simulator import kiosk_text

    device = Device()
    url = "https://api.chargegrid.test/pay/k/CG-01?c=62600"
    device.response(_kiosk({"kiosk_url": url, "payment": None}))
    assert device.kiosk_url == url and device.payment is None
    assert kiosk_text(device) == f" | Sem o app? Pague aqui · TESTE: {url}"
    device.response(_kiosk({"kiosk_url": url, "payment": {
        "status": "awaiting_payment", "status_label": "Aguardando pagamento", "amount": "20.00", "environment": "test"}}))
    assert device.payment == {"status": "awaiting_payment", "amount": "20.00", "environment": "test"}
    assert kiosk_text(device) == " | Aguardando pagamento (teste) · R$ 20,00"
    device.response(_kiosk({"kiosk_url": None, "payment": {"status": "paid", "amount": "20.00", "environment": "test"}}))
    assert device.kiosk_url is None and kiosk_text(device) == " | Pagamento confirmado (teste) · R$ 20,00"
    # Not https, unknown status or an older API without the fields: no QR, no payment line.
    device.response(_kiosk({"kiosk_url": "http://api/pay/k/CG-01?c=1", "payment": {"status": "in_use"}}))
    assert device.kiosk_url is None and device.payment is None and kiosk_text(device) == ""
    device.response(_kiosk({}))
    assert device.kiosk_url is None and device.payment is None


def test_totem_blocks_are_read_and_shown_like_the_panel():
    """Totem 0.8.0: connector.kiosk, kiosk_order e session.origin; ausentes (API antiga ou totem desligado) = nada."""
    from tools.device_simulator import kiosk_text

    device = Device()
    synced = response()
    synced["connector"] = {"kiosk": {"enabled": True, "method": "simulated", "label": "SIMULADO", "reason": None}}
    synced["kiosk_order"] = {"id": "order", "status": "charging", "status_label": "Recarga em andamento"}
    synced["authorized"]["session"]["origin"] = "kiosk_totem"
    device.response(synced)
    assert device.totem["label"] == "SIMULADO" and device.session_origin == "kiosk_totem"
    assert kiosk_text(device) == " | Totem: Recarga em andamento"
    older = response(version=2, identifier="other")
    older["connector"] = {"kiosk": {"enabled": True, "method": "cash"}}
    older["kiosk_order"] = {"id": "order", "status": "unknown"}
    device.response(older)
    assert device.totem is None and device.kiosk_order is None and device.session_origin is None
