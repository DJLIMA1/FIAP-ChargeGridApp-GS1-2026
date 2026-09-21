"""Private legacy import. Preview never contacts Auth or writes to the database.

Application verifies confirmed identities and imports only explicit historical data.
Input files stay private; reports contain counts only, never source values.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx


def preview(data):
    if not isinstance(data, dict):
        raise TypeError("O documento precisa ser um objeto JSON.")
    report = {}
    aliases = {
        "users": ("users", "usuarios"),
        "stations": ("stations", "estacoes"),
        "coupons": ("coupons", "cupons"),
        "history": ("history", "historico"),
    }
    recognized = set()
    for category, names in aliases.items():
        found = [name for name in names if name in data]
        if len(found) > 1:
            raise ValueError("Categorias duplicadas não são aceitas.")
        records = data[found[0]] if found else []
        if not isinstance(records, (list, dict)):
            raise TypeError("As categorias precisam ser listas ou objetos.")
        recognized.update(found)
        report[category] = len(records)
    report["unknown_categories"] = len(set(data) - recognized)
    report["excluded_credentials_and_active_state"] = True
    return report


def verify_accounts(mapping, client):
    """Resolve explicit email -> UUID against Supabase's admin Auth endpoint.

    No JWT decoding or user supplied 'verified' boolean substitutes this check.
    """
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("Forneça um mapa explícito de e-mails para UUIDs.")
    verified = {}
    for email, identity in mapping.items():
        user_id = str(UUID(identity))
        response = client.get("/auth/v1/admin/users/" + user_id)
        response.raise_for_status()
        account = response.json()
        if (
            account.get("id") != user_id
            or not account.get("email_confirmed_at")
            or account.get("email", "").strip().casefold() != email.strip().casefold()
        ):
            raise ValueError("Identidade não confirmada ou diferente do mapa.")
        verified[email.strip().casefold()] = user_id
    return verified


def amount(value, suffix=""):
    text = str(value).strip().removeprefix("R$").strip()
    if suffix:
        text = text.removesuffix(suffix).strip()
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    number = Decimal(text)
    if not number.is_finite() or number < 0:
        raise ValueError("Número inválido.")
    return number


def timestamp(value):
    if isinstance(value, (int, float)):
        result = datetime.fromtimestamp(value, timezone.utc)
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.year < 2000:
        raise ValueError("Data inválida.")
    return result


def plan_import(data, accounts, source_id, connector_type=None):
    """Whitelist source fields; relationship resolution never guesses by name alone."""
    if not isinstance(data, dict) or not isinstance(data.get("users"), dict):
        raise TypeError("Formato suportado: users como objeto de e-mails.")
    namespace = uuid5(NAMESPACE_URL, "chargegrid-legacy:" + source_id)

    def identity(path):
        return str(uuid5(namespace, path))

    rows = {
        table: []
        for table in (
            "profiles",
            "stations",
            "connectors",
            "coupons",
            "charging_sessions",
        )
    }
    skipped = {"users": 0, "stations": 0, "coupons": 0, "history": 0}
    station_lookup = {}
    users = data["users"]
    for email, user in users.items():
        normalized = email.strip().casefold()
        if normalized not in accounts or not isinstance(user, dict):
            skipped["users"] += 1
            if isinstance(user, dict):
                for category in ("stations", "coupons", "history"):
                    skipped[category] += len(user.get(category, []))
            continue
        uid = str(UUID(accounts[normalized]))
        name = str(user.get("name", ""))[:100]
        rows["profiles"].append(
            {
                "id": uid,
                "name": name,
                "operator_enabled": bool(user.get("stations")),
            }
        )
        for index, station in enumerate(user.get("stations", [])):
            try:
                path = "users/" + normalized + "/stations/" + str(index)
                sid, cid = identity(path), identity(path + "/connector")
                lat, lng = Decimal(str(station["lat"])), Decimal(str(station["lng"]))
                if (
                    not lat.is_finite()
                    or not lng.is_finite()
                    or not -90 <= lat <= 90
                    or not -180 <= lng <= 180
                ):
                    raise ValueError()
                power, price = amount(station["power"]), amount(station["price"])
                duration = int(station["max_time"])
                kind = station.get("connector_type") or connector_type
                title, address = station["name"].strip(), station["endereco"].strip()
                if (
                    not kind
                    or len(kind) > 50
                    or power <= 0
                    or power > 1000
                    or price > 10000
                    or not 1 <= duration <= 1440
                    or not title
                    or len(title) > 100
                    or not address
                    or len(address) > 300
                ):
                    raise ValueError()
                rows["stations"].append(
                    {
                        "id": sid,
                        "owner_id": uid,
                        "name": title,
                        "address": address,
                        "latitude": lat,
                        "longitude": lng,
                        "active": False,
                    }
                )
                rows["connectors"].append(
                    {
                        "id": cid,
                        "station_id": sid,
                        "public_code": "LEGACY-" + cid,
                        "connector_type": kind,
                        "power_kw": power,
                        "price_per_kwh": price,
                        "max_duration_minutes": duration,
                        "active": False,
                        "control_version": 0,
                    }
                )
                station_lookup.setdefault((normalized, title), []).append(
                    (sid, cid, price)
                )
            except (ValueError, KeyError, TypeError, AttributeError, InvalidOperation):
                skipped["stations"] += 1
    for email, user in users.items():
        normalized = email.strip().casefold()
        if normalized not in accounts or not isinstance(user, dict):
            continue
        uid = str(UUID(accounts[normalized]))
        for index, coupon in enumerate(user.get("coupons", [])):
            try:
                discount = int(coupon["discount_percent"])
                if (
                    str(discount) != str(coupon["discount_percent"])
                    or not 0 <= discount <= 100
                ):
                    raise ValueError()
                valid = timestamp(coupon["valid_until"])
                station_name = coupon.get("station")
                matches = station_lookup.get((normalized, station_name), [])
                if len(matches) != 1:
                    raise ValueError()
                code = coupon["code"].strip()
                desc = coupon.get("desc", "").strip()
                if not code or len(code) > 50 or len(desc) > 200:
                    raise ValueError()
                rows["coupons"].append(
                    {
                        "id": identity(
                            "users/" + normalized + "/coupons/" + str(index)
                        ),
                        "operator_id": uid,
                        "station_id": matches[0][0],
                        "code": code,
                        "description": desc,
                        "discount_percent": discount,
                        "valid_until": valid,
                        "active": False,
                    }
                )
            except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
                skipped["coupons"] += 1
        for index, history in enumerate(user.get("history", [])):
            try:
                owner = history["owner"].strip().casefold()
                if owner not in accounts or history.get("status") not in (
                    "Pago",
                    "completed",
                ):
                    raise ValueError()
                matches = station_lookup.get((owner, history["local"]), [])
                if len(matches) != 1:
                    raise ValueError()
                ended = timestamp(history["timestamp"])
                energy = amount(history["kwh"], "kWh") * 1000
                cost = amount(history["valor"])
                if energy >= Decimal("1e13") or cost >= Decimal("1e8"):
                    raise ValueError()
                rows["charging_sessions"].append(
                    {
                        "id": identity(
                            "users/" + normalized + "/history/" + str(index)
                        ),
                        "user_id": uid,
                        "connector_id": matches[0][1],
                        "status": "completed",
                        "started_at": None,
                        "ended_at": ended,
                        "max_duration_minutes": 0,
                        "price_per_kwh": matches[0][2],
                        "discount_percent": 0,
                        "energy_wh": energy,
                        "source": "simulated",
                        "cost_estimate": cost,
                        "end_reason": "legacy_import",
                    }
                )
            except (
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                InvalidOperation,
                OverflowError,
            ):
                skipped["history"] += 1
    return rows, {
        "planned": {key: len(value) for key, value in rows.items()},
        "skipped": skipped,
    }


def apply_import(connection, rows):
    """Caller owns transaction. Lock, validate every collision, then insert atomically."""
    inserted = {}
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(734982103)")
        for table, records in rows.items():
            for record in records:
                cursor.execute(f"SELECT * FROM {table} WHERE id = %s", (record["id"],))
                existing = cursor.fetchone()
                if existing:
                    names = [column.name for column in cursor.description]
                    existing = dict(zip(names, existing))
                    fields = (
                        ("id", "operator_enabled")
                        if table == "profiles" and record["operator_enabled"]
                        else (("id",) if table == "profiles" else tuple(record))
                    )
                    if any(
                        (
                            existing.get(field) != record[field]
                            if isinstance(record[field], (Decimal, datetime, bool, int))
                            else str(existing.get(field)) != str(record[field])
                        )
                        for field in fields
                    ):
                        raise ValueError(
                            "Colisão de identidade ou conteúdo; transação cancelada."
                        )
                if table in ("connectors", "coupons"):
                    column = "public_code" if table == "connectors" else "code"
                    cursor.execute(
                        f"SELECT id FROM {table} WHERE {column} = %s", (record[column],)
                    )
                    collision = cursor.fetchone()
                    if collision and str(collision[0]) != record["id"]:
                        raise ValueError("Colisão de código; transação cancelada.")
        for table, records in rows.items():
            inserted[table] = 0
            for record in records:
                columns = ", ".join(record)
                placeholders = ", ".join(["%s"] * len(record))
                if table == "profiles":
                    columns += ", created_at"
                    placeholders += ", CURRENT_TIMESTAMP"
                cursor.execute(
                    f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING",
                    tuple(record.values()),
                )
                inserted[table] += cursor.rowcount
    return inserted


def main():
    parser = argparse.ArgumentParser(
        description="Prévia privada e importação administrativa atômica."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--account-map", type=Path)
    parser.add_argument(
        "--source-id",
        help="Identificador estável e exclusivo da origem; preserve nas repetições.",
    )
    parser.add_argument(
        "--connector-type",
        help="Tipo explicitamente confirmado pelo administrador; sem padrão.",
    )
    args = parser.parse_args()
    try:
        data = json.loads(args.source.read_text(encoding="utf-8"))
        if not args.account_map or not args.source_id:
            if args.apply:
                raise ValueError("Aplicação exige --account-map e --source-id.")
            print(json.dumps(preview(data), sort_keys=True))
            print(
                "Inventário apenas; use mapa e source-id para planejar registros aplicáveis."
            )
            return 0
        mapping = json.loads(args.account_map.read_text(encoding="utf-8"))
        if not isinstance(mapping, dict):
            raise TypeError("Mapa inválido.")
        accounts = {
            email.strip().casefold(): str(UUID(uid)) for email, uid in mapping.items()
        }
        if len(accounts) != len(mapping) or len(set(accounts.values())) != len(
            accounts
        ):
            raise ValueError("Mapa ambíguo.")
        rows, report = plan_import(data, accounts, args.source_id, args.connector_type)
        if args.apply:
            url, key = (
                os.getenv("SUPABASE_URL", ""),
                os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
            )
            database = os.getenv("LEGACY_IMPORT_DATABASE_URL", "")
            if not url.startswith("https://") or not key or not database:
                raise ValueError(
                    "Configure Auth administrativo e LEGACY_IMPORT_DATABASE_URL explicitamente."
                )
            with httpx.Client(
                base_url=url.rstrip("/"),
                headers={"apikey": key, "Authorization": "Bearer " + key},
                timeout=20,
            ) as client:
                verify_accounts(accounts, client)
            import psycopg

            with psycopg.connect(
                database.replace("postgresql+psycopg://", "postgresql://", 1)
            ) as connection:
                report["inserted"] = apply_import(connection, rows)
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception:  # noqa: BLE001 - CLI must not leak provider/database details
        print(
            "Importação falhou; nenhum dado desta transação foi gravado. Verifique formato, contas confirmadas, vínculos e conflitos.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
