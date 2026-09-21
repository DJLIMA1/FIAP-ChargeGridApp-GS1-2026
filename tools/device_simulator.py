"""Bancada simulada do protocolo ESP32; nenhuma saída física é acionada."""
import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


class Device:
    def __init__(self, state_path=None, clock=time.monotonic):
        self.path = Path(state_path) if state_path else None
        self.clock = clock
        saved = json.loads(self.path.read_text()) if self.path and self.path.exists() else {}
        self.version = saved.get("version", 0)
        self.last_command = saved.get("last_command")
        self.session_id = saved.get("session_id")
        self.energy = saved.get("energy_wh", 0.0)
        self.state = "stopped" if self.session_id else "idle"
        self.reason = "communication_lost" if self.session_id else None
        self.boot_id = str(uuid.uuid4())
        self.sequence = 0
        self.acks = []
        self.connected = False
        self.last_sync = clock()
        self.last_tick = clock()
        self.started = None
        self.limits = {}
        self.reservation_expires = None

    def save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"version": self.version, "last_command": self.last_command,
                                             "session_id": self.session_id, "energy_wh": self.energy}))
            os.chmod(temporary, 0o600)
            temporary.replace(self.path)

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
        self.energy += 7200 * max(0, min(now, deadline) - (now - elapsed)) / 3600
        price = float(self.limits.get("price_per_kwh", 0)) * (1 - float(self.limits.get("discount_percent", 0)) / 100)
        cost_limit = self.limits.get("max_cost")
        energy_limit = float(cost_limit) / price * 1000 if cost_limit is not None and price > 0 else None
        if energy_limit is not None:
            self.energy = min(self.energy, energy_limit)
        if now >= self.last_sync + 45:
            self.stop("communication_lost")
        elif now >= deadline:
            self.stop("duration_limit")
        elif energy_limit is not None and self.energy >= energy_limit:
            self.stop("cost_limit")
        self.save()

    def payload(self):
        self.tick()
        self.sequence += 1
        self.save()
        return {"boot_id": self.boot_id, "sequence": self.sequence, "firmware_version": "0.1.0",
                "session_id": self.session_id, "physical_state": self.state, "connected": self.connected,
                "soc_percent": min(100, 20 + self.energy / 600) if self.session_id else None,
                "energy_wh": self.energy, "power_w": 7200 if self.state == "charging" else 0,
                "source": "simulated", "captured_at": utc_now(), "end_reason": self.reason, "acks": list(self.acks)}

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
        changed = False
        for command in response["commands"]:
            identifier = command["id"]
            version = int(command["version"])
            if identifier == self.last_command:
                restarted_start = command["type"] == "START" and self.state != "charging"
                self.acks.append({"command_id": identifier, "status": "failed" if restarted_start else "applied",
                                  "error": "previous_session_requires_reconciliation" if restarted_start else None})
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
                else:
                    self.stop("requested")
            elif kind == "RELEASE":
                if self.state == "charging":
                    error = "charging_requires_stop"
                else:
                    self.state = "idle"
                    self.connected = False
            else:
                error = "unknown_command"
            self.acks.append({"command_id": identifier, "status": "failed" if error else "applied", "error": error})
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
            self.state = "idle" if not authorization.get("reservation") else self.state
        self.save()
        return changed


def main():
    import httpx
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=os.getenv("CHARGEGRID_API_URL", "https://localhost:8000"))
    parser.add_argument("--state", default=".device-simulator-state.json")
    parser.add_argument("--allow-local-http", action="store_true", help="Só localhost para teste local")
    args = parser.parse_args()
    from urllib.parse import urlparse
    url = urlparse(args.api)
    if url.scheme != "https" and not (args.allow_local_http and url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}):
        parser.error("Use HTTPS validado; HTTP só localhost com --allow-local-http")
    key = os.environ.get("CHARGEGRID_DEVICE_KEY")
    if not key:
        parser.error("Defina CHARGEGRID_DEVICE_KEY com a chave individual")
    device = Device(args.state)
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
                    print(f"{device.state} source=simulated energy_wh={device.energy:.2f}")
                except (httpx.HTTPError, ValueError, KeyError):
                    interval = min(30, interval * 2)
                    next_sync = time.monotonic() + interval
                    print("Sync indisponível; watchdog local continua ativo.")
            time.sleep(0.1)


if __name__ == "__main__":
    main()
