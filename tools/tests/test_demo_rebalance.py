import pytest

from tools.demo_rebalance import Account, Demo, parse_credentials, start_body
from tools.device_simulator import Device


class Response:
    def __init__(self, status, body):
        self.status_code, self.body = status, body

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeClient:
    def __init__(self):
        self.calls = []
        self.expired_once = False

    def post(self, path, json=None):
        self.calls.append(("POST", path, None))
        return Response(200, {"access_token": f"token-{len(self.calls)}"})

    def request(self, method, path, headers=None, json=None):
        self.calls.append((method, path, headers.get("Authorization")))
        if path.endswith("/charging-sessions"):
            if not self.expired_once:
                self.expired_once = True
                return Response(401, {})
            return Response(202, {"id": "session-1", "power_reason": "6 kW porque a loja usa 12 de 30 kW"})
        if path.endswith("/building-load"):
            return Response(200, {"building_load_kw": json["building_load_kw"], "available_kw": "6.000"})
        return Response(202, {})


def _device():
    device = Device()
    device.presence_code, device.public_code = "#F12345", "CG-SIM1"
    return device


def test_parse_credentials_requires_email_and_password():
    assert parse_credentials("a@x.com:um, b@x.com:dois") == [("a@x.com", "um"), ("b@x.com", "dois")]
    with pytest.raises(ValueError):
        parse_credentials("sem-senha@x.com")


def test_start_body_uses_presence_code_from_simulated_point():
    assert start_body(_device())["presence_code"] == "#F12345"
    with pytest.raises(ValueError):
        start_body(Device())


def test_commands_start_stop_and_store_load_with_relogin_on_401():
    client, lines = FakeClient(), []
    driver, owner = Account(client, "d@x.com", "s"), Account(client, "o@x.com", "s")
    demo = Demo(client, [_device()], [driver], owner, "station-1", out=lines.append)
    assert demo.handle("entra 1")
    assert lines[-1] == "Carro 1 entrou em CG-SIM1: 6 kW porque a loja usa 12 de 30 kW"
    logins = [call for call in client.calls if call[1] == "/v1/auth/login"]
    assert len(logins) == 2  # token expirado: novo login e nova tentativa
    demo.handle("loja 24,5")
    assert lines[-1] == "Loja (SIMULADO) em 24.5 kW: disponível 6.000 kW"
    demo.handle("sai 1")
    assert ("POST", "/v1/charging-sessions/session-1/stop") in [call[:2] for call in client.calls]
    demo.handle("entra 9")
    assert lines[-1].startswith("Erro: Carro 9")
    assert demo.handle("sair") is False


def test_run_device_backs_off_when_the_network_fails(monkeypatch):
    import threading

    import httpx

    from tools import demo_rebalance

    stop = threading.Event()
    printed = []

    class Offline:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, *args, **kwargs):
            stop.set()
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "Client", Offline)
    monkeypatch.setattr("builtins.print", printed.append)
    monkeypatch.setattr(demo_rebalance.time, "sleep", lambda seconds: None)
    demo_rebalance.run_device("https://api.test", "key", Device(clock=lambda: 0), stop, "carro 1")
    assert printed == ["[SIMULADO] carro 1: sync indisponível"]
