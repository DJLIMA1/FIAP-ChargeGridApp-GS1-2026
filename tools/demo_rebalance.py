"""Demo do rebalanceamento ao vivo: pontos SIMULADOS + motoristas de demonstração.

Roda N pontos simulados (o mesmo protocolo do painel físico) no mesmo posto do painel e
dá comandos de palco pelo terminal. Nada aqui aciona saída física; os pontos são rotulados
como simulados e o consumo da loja é simulado. Credenciais só pelo ambiente:

  CHARGEGRID_DEMO_DEVICE_KEYS   chaves dos pontos simulados, separadas por vírgula (ordem = carro 1, 2…)
  CHARGEGRID_DEMO_DRIVERS       e-mail:senha das contas de motorista de demo, separadas por vírgula
  CHARGEGRID_DEMO_OWNER         e-mail:senha do vendedor (opcional; necessário para "loja")

Comandos: ``entra N`` (motorista N inicia no ponto simulado N), ``sai N``, ``loja KW``,
``status`` e ``sair``. Ex.: ``python tools/demo_rebalance.py --api https://… --station <id>
--hca 2`` (o carro 2 usa o adaptador GoodWe HCA G2 com transporte simulado).
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import uuid
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.device_simulator import Device, load_charger


def parse_list(value):
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def parse_credentials(value):
    pairs = []
    for item in parse_list(value):
        email, _, password = item.partition(":")
        if not email or not password:
            raise ValueError("Use e-mail:senha separados por vírgula")
        pairs.append((email, password))
    return pairs


class Account:
    """Login pela API (/v1/auth/login), com novo login quando o token expira."""

    def __init__(self, client, email, password):
        self.client, self.email, self.password, self.token = client, email, password, None

    def request(self, method, path, **kwargs):
        for attempt in range(2):
            if not self.token:
                response = self.client.post("/v1/auth/login", json={"email": self.email, "password": self.password})
                response.raise_for_status()
                self.token = response.json()["access_token"]
            headers = {**kwargs.pop("headers", {}), "Authorization": f"Bearer {self.token}"}
            response = self.client.request(method, path, headers=headers, **kwargs)
            if response.status_code == 401 and attempt == 0:
                self.token = None
                kwargs["headers"] = {key: value for key, value in headers.items() if key != "Authorization"}
                continue
            return response
        return response


def start_body(device):
    """Corpo do início: o código do posto vem do sync do próprio ponto simulado."""
    if not device.presence_code or not device.public_code:
        raise ValueError("O ponto simulado ainda não recebeu o código do posto; aguarde um sync.")
    return {"public_code": device.public_code, "presence_code": device.presence_code,
            "max_duration_minutes": 30, "soc_percent": 35, "battery_kwh": 60, "soc_source": "simulated"}


class Demo:
    def __init__(self, client, devices, drivers, owner=None, station=None, out=print):
        self.client, self.devices, self.drivers, self.owner, self.station = client, devices, drivers, owner, station
        self.sessions = {}
        self.out = out

    def _car(self, text):
        index = int(text) - 1
        if not 0 <= index < len(self.devices) or index >= len(self.drivers):
            raise ValueError(f"Carro {text} não configurado")
        return index

    def handle(self, line):
        words = line.strip().split()
        if not words:
            return True
        command, args = words[0].lower(), words[1:]
        try:
            if command == "sair":
                return False
            if command == "entra":
                index = self._car(args[0])
                response = self.drivers[index].request(
                    "POST", "/v1/charging-sessions", json=start_body(self.devices[index]),
                    headers={"Idempotency-Key": f"demo-{uuid.uuid4()}"})
                body = response.json()
                if response.status_code == 202:
                    self.sessions[index] = body["id"]
                    self.out(f"Carro {index + 1} entrou em {self.devices[index].public_code}: "
                             f"{body.get('power_reason') or 'aguardando o ponto'}")
                else:
                    self.out(f"Carro {index + 1} recusado: {body.get('error', {}).get('message', body)}")
            elif command == "sai":
                index = self._car(args[0])
                session = self.sessions.pop(index, None)
                if not session:
                    raise ValueError(f"Carro {index + 1} não está carregando")
                response = self.drivers[index].request(
                    "POST", f"/v1/charging-sessions/{session}/stop", headers={"Idempotency-Key": f"demo-{uuid.uuid4()}"})
                self.out(f"Carro {index + 1} saindo (HTTP {response.status_code})")
            elif command == "loja":
                if not self.owner or not self.station:
                    raise ValueError("Configure CHARGEGRID_DEMO_OWNER e --station para mudar a loja")
                response = self.owner.request("PUT", f"/v1/stations/{self.station}/building-load",
                                              json={"building_load_kw": args[0].replace(",", ".")})
                body = response.json()
                if response.status_code == 200:
                    self.out(f"Loja (SIMULADO) em {body['building_load_kw']} kW: disponível {body['available_kw']} kW")
                else:
                    self.out(f"Loja recusada: {body}")
            elif command == "status":
                for index, device in enumerate(self.devices):
                    power = device.power_w if device.state == "charging" else 0
                    self.out(f"[SIMULADO] carro {index + 1} {device.public_code}: {device.state} {power / 1000:g} kW "
                             f"{device.energy / 1000:.3f} kWh")
                if self.owner and self.station:
                    body = self.owner.request("GET", f"/v1/stations/{self.station}/power").json()
                    self.out(f"Posto: disponível {body['available_kw']} kW, em uso {body['envelope_kw']} kW")
                    if body["decisions"]:
                        self.out(f"Última decisão: {body['decisions'][0]['summary']}")
            else:
                self.out("Comandos: entra N, sai N, loja KW, status, sair")
        except (ValueError, IndexError, KeyError) as exc:
            self.out(f"Erro: {exc}")
        return True


def run_device(api, key, device, stop, label):
    import httpx

    interval, next_sync = 1, 0
    with httpx.Client(base_url=api, timeout=10, follow_redirects=False) as client:
        while not stop.is_set():
            device.tick()
            if time.monotonic() >= next_sync:
                try:
                    response = client.post("/v1/devices/sync", json=device.payload(),
                                           headers={"Authorization": "Device " + key})
                    response.raise_for_status()
                    body = response.json()
                    changed = device.response(body)
                    interval = max(1, min(30, body["sync_interval_seconds"]))
                    next_sync = time.monotonic() if changed else time.monotonic() + interval
                # Rede instável, HTTP de erro ou resposta fora do formato: o watchdog local continua valendo.
                except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                    interval = min(30, interval * 2)
                    next_sync = time.monotonic() + interval
                    print(f"[SIMULADO] {label}: sync indisponível")
            time.sleep(0.1)


def main():
    import httpx

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=os.getenv("CHARGEGRID_API_URL", "https://localhost:8000"))
    parser.add_argument("--station", help="ID do posto (para o comando loja e o status)")
    parser.add_argument("--hca", type=int, action="append", default=[],
                        help="Carro N usa o adaptador GoodWe HCA G2 com transporte simulado")
    parser.add_argument("--state-dir", default=".demo-rebalance")
    parser.add_argument("--allow-local-http", action="store_true")
    args = parser.parse_args()
    if not args.api.startswith("https://") and not (args.allow_local_http and "://localhost" in args.api):
        parser.error("Use HTTPS; HTTP só localhost com --allow-local-http")
    keys = parse_list(os.environ.get("CHARGEGRID_DEMO_DEVICE_KEYS"))
    drivers = parse_credentials(os.environ.get("CHARGEGRID_DEMO_DRIVERS"))
    if not keys or len(drivers) < len(keys):
        parser.error("Defina CHARGEGRID_DEMO_DEVICE_KEYS e um motorista por ponto em CHARGEGRID_DEMO_DRIVERS")
    owner = parse_credentials(os.environ.get("CHARGEGRID_DEMO_OWNER"))
    stop = threading.Event()
    devices = []
    for index, key in enumerate(keys, 1):
        charger, transport = load_charger("goodwe-hca-g2", echo=print) if index in args.hca else (None, None)
        device = Device(Path(args.state_dir) / f"carro{index}.json", charger=charger, transport=transport)
        devices.append(device)
        threading.Thread(target=run_device, args=(args.api, key, device, stop, f"carro {index}"), daemon=True).start()
    with httpx.Client(base_url=args.api, timeout=15) as client:
        demo = Demo(client, devices, [Account(client, *pair) for pair in drivers],
                    Account(client, *owner[0]) if owner else None, args.station)
        print("Pontos SIMULADOS em execução. Comandos: entra N, sai N, loja KW, status, sair")
        try:
            for line in sys.stdin:
                if not demo.handle(line):
                    break
        finally:
            stop.set()


if __name__ == "__main__":
    main()
