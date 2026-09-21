"""Opt-in HTTP acceptance checks against a running ChargeGrid API.

Uses only explicitly supplied QA accounts. Creates labelled QA resources, keeps
credentials/device keys in the private state file, and never prints tokens.
Run with the API virtualenv. This is intentionally outside pytest discovery.
"""

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from device_simulator import Device


def save_private(path, data):
    descriptor = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    os.chmod(path, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(data, stream, indent=2)


class Acceptance:
    def __init__(self, api, state_path):
        self.state_path = state_path
        self.state = json.loads(state_path.read_text())
        self.client = httpx.Client(base_url=api.rstrip("/") + "/", timeout=40)
        self.results = []
        self.headers = {}

    def call(self, method, path, *, body=None, status=200, headers=None, key=None):
        actual_headers = dict(self.headers if headers is None else headers)
        if key:
            actual_headers["Idempotency-Key"] = key
        response = self.client.request(method, path, json=body, headers=actual_headers)
        if response.status_code != status:
            try:
                code = response.json().get("error", {}).get("code", "unknown")
            except ValueError:
                code = "non_json"
            raise AssertionError(
                f"{method} {path}: expected {status}, got {response.status_code} ({code})"
            )
        return response.json() if response.content else None

    def checked(self, name):
        self.results.append({"check": name, "result": "pass"})
        print("PASS", name, flush=True)

    def login(self, kind):
        credentials = self.state[kind]
        tokens = self.call(
            "POST",
            "auth/login",
            body={field: credentials[field] for field in ("email", "password")},
            headers={},
        )
        self.headers = {"Authorization": "Bearer " + tokens["access_token"]}
        return tokens

    def accounts(self):
        for kind, expected in [("consumer", "consumer"), ("vendor", "vendor")]:
            tokens = self.login(kind)
            profile = self.call("GET", "me")
            assert profile["account_type"] == expected
            self.state[kind]["id"] = profile["id"]
            if kind == "consumer":
                assert not profile["operator_enabled"]
                self.call("GET", "operator/summary", status=403)
            refreshed = self.call(
                "POST",
                "auth/refresh",
                body={"refresh_token": tokens["refresh_token"]},
                headers={},
            )
            self.headers = {"Authorization": "Bearer " + refreshed["access_token"]}
            assert self.call("GET", "me")["id"] == profile["id"]
            self.call("POST", "auth/logout")
            self.login(kind)
            assert self.call("GET", "me")["id"] == profile["id"]
            self.checked(
                f"{kind}: login, persisted account type, refresh, logout, relogin"
            )
        save_private(self.state_path, self.state)

    def provision(self):
        # Only deliberately supplied factory bundles can create new QA equipment.
        # Existing legacy QA state keeps its owners and device credentials intact.
        artifacts = {}
        for kind in ("simulator", "panel"):
            if kind not in self.state:
                path = os.getenv("CHARGEGRID_QA_FACTORY_" + kind.upper())
                if not path:
                    raise ValueError(
                        "Missing explicit private factory artifact for QA " + kind
                    )
                artifact = json.loads(Path(path).read_text())
                if not all(
                    artifact.get(field)
                    for field in (
                        "claim_token",
                        "device_key",
                        "device_id",
                        "connector_id",
                        "public_code",
                    )
                ):
                    raise ValueError("Incomplete QA factory artifact")
                artifacts[kind] = artifact
            elif not self.state[kind].get("device_key"):
                raise ValueError(
                    "Existing QA device credentials missing; repair private state explicitly"
                )
        self.login("vendor")
        for kind, artifact in artifacts.items():
            body = {"token": artifact["claim_token"]}
            if self.state.get("station"):
                body["station_id"] = self.state["station"]
            result = self.call("POST", "ownership/claim", body=body)
            if result["connector_id"] != artifact["connector_id"]:
                raise ValueError(
                    "Factory claim does not match the supplied equipment bundle"
                )
            self.state["station"] = result["station_id"]
            save_private(self.state_path, self.state)
            self.call(
                "PATCH",
                f"connectors/{result['connector_id']}",
                body={
                    "connector_type": "Bancada simulada",
                    "power_kw": "7.2",
                    "price_per_kwh": "1.50",
                    "max_duration_minutes": 60,
                    "active": True,
                },
            )
            self.call(
                "PATCH",
                "stations/" + result["station_id"],
                body={
                    "name": "ChargeGrid • Bancada QA",
                    "address": "Bancada simulada de validação — sem recarga real",
                    "latitude": -23.5505,
                    "longitude": -46.6333,
                    "active": True,
                },
            )
            self.state[kind] = {
                field: artifact[field]
                for field in ("connector_id", "device_id", "device_key", "public_code")
            }
            save_private(self.state_path, self.state)
        assert self.call("GET", "me")["operator_enabled"], (
            "QA vendor must claim a factory QR first"
        )
        self.checked(
            "vendor ownership: factory QR claims or preserved existing equipment"
        )

    def simulation(self):
        point = self.state["simulator"]
        device = Device()
        device_headers = {"Authorization": "Device " + point["device_key"]}

        def sync():
            result = self.call(
                "POST", "devices/sync", body=device.payload(), headers=device_headers
            )
            device.response(result)
            return result

        sync()
        self.login("consumer")
        station = self.call("GET", "stations/" + self.state["station"])
        assert next(
            c for c in station["connectors"] if c["id"] == point["connector_id"]
        )["available"]
        self.checked("device handshake makes connector available")
        key = str(uuid4())
        body = {"connector_id": point["connector_id"]}
        reservation = self.call("POST", "reservations", body=body, key=key, status=202)
        assert (
            self.call("POST", "reservations", body=body, key=key, status=202)["id"]
            == reservation["id"]
        )
        sync()
        sync()
        assert self.call("GET", "reservations/current")["status"] == "confirmed"
        self.call("POST", f"reservations/{reservation['id']}/cancel", status=202)
        sync()
        sync()
        assert self.call("GET", "reservations/current") is None
        self.checked("reservation idempotency, real device ACK and cancellation")
        reservation = self.call(
            "POST", "reservations", body=body, key=str(uuid4()), status=202
        )
        sync()
        sync()
        self.login("vendor")
        coupon = self.call(
            "POST",
            "coupons",
            status=201,
            body={
                "code": "QA-" + uuid4().hex[:10],
                "description": "Teste de integração",
                "station_id": self.state["station"],
                "discount_percent": 10,
                "valid_until": (
                    datetime.now(timezone.utc) + timedelta(hours=2)
                ).isoformat(),
            },
        )
        self.login("consumer")
        session = self.call(
            "POST",
            "charging-sessions",
            status=202,
            key=str(uuid4()),
            body={
                "public_code": point["public_code"],
                "reservation_id": reservation["id"],
                "max_duration_minutes": 5,
                "coupon_code": coupon["code"],
            },
        )
        sync()
        time.sleep(1)
        sync()
        current = self.call("GET", "charging-sessions/current")
        assert current["status"] == "charging" and current["discount_percent"] == 10
        assert float(current["energy_wh"]) > 0 and current["source"] == "simulated"
        self.checked("reserved start, coupon, telemetry and charging state")
        self.login("vendor")
        self.call("GET", "charging-sessions/" + session["id"], status=404)
        self.checked("another account cannot read consumer charging session")
        self.login("consumer")
        self.call(
            "POST",
            f"charging-sessions/{session['id']}/stop",
            status=202,
            key=str(uuid4()),
        )
        sync()
        sync()
        sync()
        assert self.call("GET", "charging-sessions/current") is None
        history = self.call("GET", "me/charging-sessions")
        final = next(item for item in history["items"] if item["id"] == session["id"])
        assert final["status"] == "completed" and float(final["energy_wh"]) > 0
        summary = self.call("GET", "me/summary")
        assert summary["sessions_count"] >= 1 and float(summary["energy_wh"]) > 0
        self.checked("stop ACK, final energy, history and monthly summary")
        self.login("vendor")
        self.call("PATCH", f"coupons/{coupon['id']}", body={"active": False})
        self.call("GET", f"stations/{self.state['station']}/charging-sessions")
        self.checked("operator history and coupon deactivation")

    def close(self):
        self.client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument(
        "--phase", choices=["accounts", "provision", "simulation", "all"], default="all"
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    qa = Acceptance(args.api, args.state)
    try:
        for phase in ("accounts", "provision", "simulation"):
            if args.phase in (phase, "all"):
                getattr(qa, phase)()
        if args.report:
            args.report.write_text(json.dumps(qa.results, indent=2) + "\n")
    finally:
        qa.close()


if __name__ == "__main__":
    main()
