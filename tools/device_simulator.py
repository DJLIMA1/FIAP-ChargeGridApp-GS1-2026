"""Bancada simulada do protocolo ESP32; nenhuma saída física é acionada."""
import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def number(value, low, high):
    """Número da API (Decimal chega como texto); None se ausente ou fora da faixa."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if low <= parsed <= high else None


SOC_SOURCES = ("simulated", "phone")
BENCH_POWER_W = 7200  # Potência nominal simulada da bancada.
BENCH_MIN_POWER_W = 1400  # 6 A em 230 V: menor corrente de recarga AC.
# Firmware 0.5.0+: ajuste de potência ao vivo (SET_POWER). ``legacy=True`` simula o antigo.
CAPABILITIES = ["set_power_v1"]


def load_charger(name, variant="GW7K-HCA-20", fail_writes=0, echo=None):
    """Adaptador de carregador + transporte SIMULADO (nenhuma conexão real)."""
    if name in (None, "", "bench"):
        return None, None
    if name != "goodwe-hca-g2":
        raise ValueError(f"Carregador desconhecido: {name}")
    try:
        from chargegrid_core.chargers import GoodWeHcaG2
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "chargegrid_core"))
        from chargegrid_core.chargers import GoodWeHcaG2
    if str(Path(__file__).resolve().parents[1]) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # execução direta: python tools/…
    from tools.edge.modbus_sim import SimulatedModbusTransport
    driver = GoodWeHcaG2(variant)
    transport = SimulatedModbusTransport(variant, fail_writes=fail_writes, echo=echo)
    for item in driver.setup_writes():
        transport.write(item.address, item.value)
    return driver, transport


def power_cap_w(*sources):
    """Potência simulada: min(nominal, max_power_kw do START/sessão); sem limite = nominal."""
    for source in sources:
        cap = number((source or {}).get("max_power_kw"), 0.1, 1000)
        if cap is not None:
            return min(BENCH_POWER_W, cap * 1000)
    return BENCH_POWER_W


class Device:
    def __init__(self, state_path=None, clock=time.monotonic, *, legacy=False, charger=None, transport=None):
        self.path = Path(state_path) if state_path else None
        self.clock = clock
        saved = json.loads(self.path.read_text()) if self.path and self.path.exists() else {}
        self.version = saved.get("version", 0)
        self.last_command = saved.get("last_command")
        self.session_id = saved.get("session_id")
        self.energy = saved.get("energy_wh", 0.0)
        self.state = "stopped" if self.session_id else "idle"
        self.reason = "communication_lost" if self.session_id else None
        # SoC do veículo (mesmas regras do firmware): None = desconhecido.
        self.soc_start = saved.get("soc_start") if self.session_id else None
        self.battery_kwh = saved.get("battery_kwh") if self.session_id else None
        self.soc_source = saved.get("soc_source") if self.session_id else None
        self.phone_soc = self.soc_start if self.soc_source == "phone" else None
        self.boot_id = str(uuid.uuid4())
        self.sequence = 0
        self.acks = []
        self.connected = False
        self.last_sync = clock()
        self.last_tick = clock()
        self.started = None
        self.limits = {}
        self.power_w = BENCH_POWER_W
        self.reservation_expires = None
        self.legacy = legacy
        self.charger = charger
        self.transport = transport
        self.presence_code = None
        self.public_code = None

    def save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"version": self.version, "last_command": self.last_command,
                                             "session_id": self.session_id, "energy_wh": self.energy,
                                             "soc_start": self.soc_start, "battery_kwh": self.battery_kwh,
                                             "soc_source": self.soc_source}))
            os.chmod(temporary, 0o600)
            temporary.replace(self.path)

    def reset_soc(self):
        self.soc_start = self.battery_kwh = self.soc_source = self.phone_soc = None

    def read_start_soc(self, source):
        if not source:
            return
        soc = number(source.get("soc_percent"), 0, 100)
        battery = number(source.get("battery_kwh"), 1, 1000)
        if soc is not None:
            self.soc_start = soc
        if battery is not None:
            self.battery_kwh = battery
        if source.get("soc_source") in SOC_SOURCES:
            self.soc_source = source["soc_source"]

    def full_energy(self):
        """Wh até 100 % na fonte simulada; None quando o SoC não é acompanhado."""
        if self.soc_source != "simulated" or self.soc_start is None or not self.battery_kwh:
            return None
        return (100 - self.soc_start) / 100 * self.battery_kwh * 1000

    def soc_known(self):
        return self.phone_soc is not None if self.soc_source == "phone" else self.full_energy() is not None

    def soc(self):
        if self.soc_source == "phone" and self.phone_soc is not None:
            return self.phone_soc
        if self.full_energy() is not None:
            return min(100, self.soc_start + self.energy / (10 * self.battery_kwh))
        return min(100, 20 + self.energy / 600)  # Bancada legada, sem SoC da API.

    def max_power_w(self):
        return self.charger.limits().max_power_w if self.charger else BENCH_POWER_W

    def charger_info(self):
        if self.charger:
            return {**self.charger.capability(), "transport": "simulated"}
        return {"model": "simulated_bench", "transport": "simulated", "min_power_w": BENCH_MIN_POWER_W,
                "max_power_w": BENCH_POWER_W, "step_w": 100, "phases": 1}

    def install_power(self, power_w):
        """Instala o limite (W). Com adaptador, escreve os registradores e só confirma pela
        releitura. Devolve (aplicado, erro)."""
        power_w = max(0, min(int(power_w), self.max_power_w()))
        if not self.charger:
            self.power_w = power_w
            return power_w, None
        from chargegrid_core.chargers import apply_power
        from chargegrid_core.chargers.goodwe_hca_g2 import WATCHED

        from tools.edge.modbus_sim import ModbusError
        try:
            result = apply_power(self.charger, self.transport, power_w, WATCHED)
        # Exceção Modbus simulada, valor recusado pelo adaptador ou falha de E/S: o limite anterior continua.
        except (ModbusError, ValueError, OSError) as exc:
            return self.power_w, f"modbus_error: {exc}"[:200]
        if not result["confirmed"]:
            return self.power_w, "readback_mismatch"
        self.power_w = result["applied_power_w"]
        return self.power_w, None

    def stop(self, reason):
        self.state = "stopped"
        self.connected = False
        self.reason = reason
        self.save()

    def tick(self):
        now = self.clock()
        elapsed = now - self.last_tick
        self.last_tick = now
        if self.state == "reserved" and self.reservation_expires and time.time() >= self.reservation_expires:
            self.state = "idle"
        if self.state != "charging":
            return
        # Só integra o tempo até o watchdog ou limite local.
        deadline = min(self.last_sync + 45, self.started + self.limits.get("max_duration_minutes", 60) * 60)
        self.energy += self.power_w * max(0, min(now, deadline) - (now - elapsed)) / 3600
        price = float(self.limits.get("price_per_kwh", 0)) * (1 - float(self.limits.get("discount_percent", 0)) / 100)
        cost_limit = self.limits.get("max_cost")
        energy_limit = float(cost_limit) / price * 1000 if cost_limit is not None and price > 0 else None
        if energy_limit is not None:
            self.energy = min(self.energy, energy_limit)
        full = self.full_energy()
        if full is not None:
            self.energy = min(self.energy, full)  # Nunca além dos 100 %.
        if now >= self.last_sync + 45:
            self.stop("communication_lost")
        elif now >= deadline:
            self.stop("duration_limit")
        elif full is not None and self.energy >= full:
            self.stop("battery_full")
        elif energy_limit is not None and self.energy >= energy_limit:
            self.stop("cost_limit")
        self.save()

    def payload(self):
        self.tick()
        self.sequence += 1
        self.save()
        # SoC próprio só na fonte simulada; phone ou sem dados de bateria: null (nunca eco da API).
        report_soc = self.session_id and self.soc_source == "simulated" and self.soc_known()
        body = {"boot_id": self.boot_id, "sequence": self.sequence, "firmware_version": "0.4.0" if self.legacy else "0.5.0",
                "session_id": self.session_id, "physical_state": self.state, "connected": self.connected,
                "soc_percent": round(self.soc(), 2) if report_soc else None,
                "energy_wh": self.energy, "power_w": self.power_w if self.state == "charging" else 0,
                "source": "simulated", "captured_at": utc_now(), "end_reason": self.reason, "acks": list(self.acks)}
        if not self.legacy:
            body.update(capabilities=list(CAPABILITIES), charger=self.charger_info(),
                        applied_power_w=self.power_w if self.state == "charging" else 0)
        return body

    def response(self, response):
        self.last_sync = self.clock()
        self.acks = []
        server_time = timestamp(response["server_time"])
        authorization = response["authorized"]
        current_version = int(response["control_version"])
        reservation = authorization.get("reservation")
        self.reservation_expires = timestamp(reservation["expires_at"]) if reservation else None
        new_session = authorization.get("session")
        if self.state == "stopped" and ((new_session and new_session["id"] != self.session_id) or (reservation and not new_session)):
            self.session_id = None
            self.energy = 0
            self.reason = None
            self.reset_soc()
        if new_session and self.session_id and new_session["id"] == self.session_id:
            # O app pode trocar a fonte para o celular; o nível do celular só é exibido/repassado.
            if new_session.get("soc_source") in SOC_SOURCES:
                self.soc_source = new_session["soc_source"]
            if self.battery_kwh is None:
                self.battery_kwh = number(new_session.get("battery_kwh"), 1, 1000)
            if self.soc_start is None:
                self.soc_start = number(new_session.get("start_soc_percent"), 0, 100)
            if self.soc_source == "phone":
                phone = number(new_session.get("soc_percent"), 0, 100)
                self.phone_soc = phone if phone is not None else (
                    self.phone_soc if self.phone_soc is not None else self.soc_start)
        connector = response.get("connector") or {}
        self.presence_code = connector.get("presence_code")
        self.public_code = connector.get("public_code")
        changed = False
        for command in response["commands"]:
            identifier = command["id"]
            version = int(command["version"])
            if identifier == self.last_command:
                restarted_start = command["type"] == "START" and self.state != "charging"
                ack = {"command_id": identifier, "status": "failed" if restarted_start else "applied",
                       "error": "previous_session_requires_reconciliation" if restarted_start else None}
                if command["type"] == "SET_POWER":
                    ack["applied_power_w"] = self.power_w
                self.acks.append(ack)
                continue
            if version <= self.version or version < current_version or timestamp(command["expires_at"]) <= server_time:
                continue
            kind = command["type"]
            error = None
            if kind == "START":
                session = authorization.get("session")
                if not session or session["id"] != command["session_id"]:
                    error = "unauthorized_session"
                elif self.session_id:
                    error = "previous_session_requires_reconciliation"
                else:
                    self.session_id = command["session_id"]
                    self.energy = 0
                    self.save()
                    self.reason = None
                    self.state = "charging"
                    self.connected = True  # Conexão de bancada explicitamente simulada.
                    self.started = self.clock()
                    self.last_tick = self.clock()
                    self.limits = dict(session)
                    # Limite de potência do posto/motorista (parameters prevalecem; API antiga: nominal).
                    # Firmware novo usa power_limit_w (pode ser 0: começa pausado até sobrar folga).
                    start_limit = (command.get("parameters") or {}).get("power_limit_w")
                    if not self.legacy and start_limit is not None:
                        self.install_power(number(start_limit, 0, 1000000) or 0)
                    else:
                        self.install_power(power_cap_w(command.get("parameters"), session))
                    self.reset_soc()
                    self.read_start_soc(session)
                    self.read_start_soc(command.get("parameters"))  # parameters prevalecem.
                    if self.soc_start is not None and self.soc_source is None:
                        self.soc_source = "simulated"
                    if self.soc_source == "phone":
                        self.phone_soc = self.soc_start
                    self.save()
            elif kind == "RESERVE":
                reservation = authorization.get("reservation")
                if not reservation or reservation["id"] != command["reservation_id"] or self.session_id:
                    error = "unauthorized_reservation"
                else:
                    self.state = "reserved"
                    self.reservation_expires = timestamp(reservation["expires_at"])
            elif kind == "STOP":
                if self.session_id and command["session_id"] != self.session_id:
                    error = "session_mismatch"
                elif not (self.state == "stopped" and self.reason):
                    reason = (command.get("parameters") or {}).get("reason")
                    full = reason == "battery_full" or (
                        self.soc_source == "phone" and self.phone_soc is not None and self.phone_soc >= 100)
                    self.stop("battery_full" if full else "requested")
            elif kind == "RELEASE":
                if self.state == "charging":
                    error = "charging_requires_stop"
                else:
                    self.state = "idle"
                    self.connected = False
            elif kind == "SET_POWER" and not self.legacy:
                limit = number((command.get("parameters") or {}).get("power_limit_w"), 0, 1000000)
                if self.state != "charging" or command.get("session_id") != self.session_id:
                    error = "no_active_session"
                elif limit is None:
                    error = "invalid_power_limit"
                else:
                    self.tick()  # Energia até aqui na potência antiga; daqui em diante, na nova.
                    _, error = self.install_power(limit)
            else:
                error = "unknown_command"
            ack = {"command_id": identifier, "status": "failed" if error else "applied", "error": error}
            if kind == "SET_POWER" and not self.legacy:
                ack["applied_power_w"] = self.power_w
            self.acks.append(ack)
            if not error:
                self.version = version
                self.last_command = identifier
                self.save()
                changed = True
        self.version = max(self.version, current_version)
        # Só elimina o resultado final após servidor confirmar a ausência de sessão.
        if self.state != "charging" and not authorization.get("session") and not self.acks:
            self.session_id = None
            self.energy = 0
            self.reason = None
            self.reset_soc()
            self.state = "idle" if not authorization.get("reservation") else self.state
        self.save()
        return changed


def main():
    import httpx
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=os.getenv("CHARGEGRID_API_URL", "https://localhost:8000"))
    parser.add_argument("--state", default=".device-simulator-state.json")
    parser.add_argument("--allow-local-http", action="store_true", help="Só localhost para teste local")
    parser.add_argument("--charger", choices=["bench", "goodwe-hca-g2"], default="bench",
                        help="goodwe-hca-g2: traduz SET_POWER em registradores Modbus num transporte SIMULADO")
    parser.add_argument("--hca-model", default="GW7K-HCA-20", choices=["GW7K-HCA-20", "GW11K-HCA-20", "GW22K-HCA-20"])
    parser.add_argument("--hca-fail-writes", type=int, default=0, help="Perde as N primeiras escritas (teste de ACK)")
    parser.add_argument("--legacy", action="store_true", help="Simula firmware 0.4.0 (sem SET_POWER)")
    args = parser.parse_args()
    from urllib.parse import urlparse
    url = urlparse(args.api)
    if url.scheme != "https" and not (args.allow_local_http and url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}):
        parser.error("Use HTTPS validado; HTTP só localhost com --allow-local-http")
    key = os.environ.get("CHARGEGRID_DEVICE_KEY")
    if not key:
        parser.error("Defina CHARGEGRID_DEVICE_KEY com a chave individual")
    charger, transport = load_charger(args.charger, args.hca_model, args.hca_fail_writes, echo=print)
    device = Device(args.state, legacy=args.legacy, charger=charger, transport=transport)
    interval = 1
    next_sync = 0
    with httpx.Client(timeout=10, follow_redirects=False) as client:
        while True:
            device.tick()
            if time.monotonic() >= next_sync:
                payload = device.payload()
                try:
                    result = client.post(args.api.rstrip("/") + "/v1/devices/sync", json=payload,
                                         headers={"Authorization": "Device " + key})
                    result.raise_for_status()
                    response = result.json()
                    changed = device.response(response)
                    interval = max(1, min(30, response["sync_interval_seconds"]))
                    next_sync = time.monotonic() if changed else time.monotonic() + interval
                    soc = f" soc={device.soc():.1f}% ({device.soc_source})" if device.soc_known() else ""
                    power = f" power_w={device.power_w if device.state == 'charging' else 0}"
                    print(f"{device.state} source=simulated energy_wh={device.energy:.2f}{power}{soc}")
                except (httpx.HTTPError, ValueError, KeyError):
                    interval = min(30, interval * 2)
                    next_sync = time.monotonic() + interval
                    print("Sync indisponível; watchdog local continua ativo.")
            time.sleep(0.1)


if __name__ == "__main__":
    main()
