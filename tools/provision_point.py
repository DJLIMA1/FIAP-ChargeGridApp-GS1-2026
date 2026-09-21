"""Factory provisioning: create an unowned point and export its private claim QR.

Use MIGRATION_DATABASE_URL from the environment; no .env file is loaded. Run with
the administrative database role, never with credentials in shell arguments.
The QR is a single-use ownership secret, not the public charging QR.
"""

import argparse
import hashlib
import io
import json
import os
import secrets
import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

if __package__:
    from .approve_operator import connection_options
else:
    from approve_operator import connection_options


def provision(
    connection,
    *,
    public_code,
    name="Novo ponto ChargeGrid",
    address="Configure o endereço",
    latitude=Decimal(0),
    longitude=Decimal(0),
    power_kw=Decimal("7.4"),
    price_per_kwh=Decimal(0),
    connector_type="Tipo 2",
    max_duration_minutes=60,
):
    """Insert factory equipment in the caller's transaction; never alter old owners."""
    for value, lower, upper in (
        (latitude, -90, 90),
        (longitude, -180, 180),
        (power_kw, Decimal("0.001"), 1000),
        (price_per_kwh, 0, 10000),
    ):
        if not Decimal(value).is_finite() or not lower <= value <= upper:
            raise ValueError("Parâmetro numérico inválido")
    for value, maximum in (
        (public_code, 50),
        (name, 100),
        (address, 300),
        (connector_type, 50),
    ):
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise ValueError("Texto de identificação inválido")
    if not 1 <= max_duration_minutes <= 1440:
        raise ValueError("Duração inválida")
    station_id, connector_id, device_id = (uuid4() for _ in range(3))
    device_key, claim_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)

    def digest(secret):
        return hashlib.sha256(secret.encode()).hexdigest()

    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO stations (id, owner_id, name, address, latitude, longitude, active) "
            "VALUES (%s, NULL, %s, %s, %s, %s, FALSE)",
            (station_id, name.strip(), address.strip(), latitude, longitude),
        )
        cursor.execute(
            "INSERT INTO connectors (id, station_id, public_code, connector_type, power_kw, "
            "price_per_kwh, max_duration_minutes, active, control_version) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, 0)",
            (
                connector_id,
                station_id,
                public_code.strip(),
                connector_type.strip(),
                power_kw,
                price_per_kwh,
                max_duration_minutes,
            ),
        )
        cursor.execute(
            "INSERT INTO devices (id, connector_id, key_hash, revoked, sequence, physical_state, connected, reconciled) "
            "VALUES (%s, %s, %s, FALSE, -1, 'unknown', FALSE, FALSE)",
            (device_id, connector_id, digest(device_key)),
        )
        cursor.execute(
            "INSERT INTO device_claims (connector_id, token_hash, created_at) VALUES (%s, %s, CURRENT_TIMESTAMP)",
            (connector_id, digest(claim_token)),
        )
    return {
        "station_id": str(station_id),
        "connector_id": str(connector_id),
        "device_id": str(device_id),
        "public_code": public_code.strip(),
        "device_key": device_key,
        "claim_token": claim_token,
        "claim_url": "chargegrid://claim?token=" + claim_token,
        "warning": "Segredo de propriedade de uso único. Entregue o QR apenas ao comprador; não publique.",
    }


def write_artifacts(output, artifact):
    import qrcode
    from qrcode.image.svg import SvgPathImage

    qr = qrcode.make(artifact["claim_url"], image_factory=SvgPathImage, border=4)
    buffer = io.BytesIO()
    qr.save(buffer)
    # Exclusive creation prevents accidental credential replacement, even on retries.
    for filename, content in (
        (
            "provisioning.json",
            json.dumps(artifact, indent=2, ensure_ascii=False).encode(),
        ),
        ("ownership-qr.svg", buffer.getvalue()),
    ):
        fd = os.open(output / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-code", required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="Diretório NOVO privado fora do Git"
    )
    parser.add_argument("--name", default="Novo ponto ChargeGrid")
    parser.add_argument("--address", default="Configure o endereço")
    parser.add_argument("--latitude", type=Decimal, default=Decimal(0))
    parser.add_argument("--longitude", type=Decimal, default=Decimal(0))
    parser.add_argument("--power-kw", type=Decimal, default=Decimal("7.4"))
    parser.add_argument("--price-per-kwh", type=Decimal, default=Decimal(0))
    parser.add_argument("--connector-type", default="Tipo 2")
    parser.add_argument("--max-duration-minutes", type=int, default=60)
    parser.add_argument(
        "--apply", action="store_true", help="Confirma criação de equipamento novo"
    )
    args = parser.parse_args(argv)
    if not args.apply:
        print(
            "Prévia: será criado um ponto sem dono e inativo. Use --apply para provisionar."
        )
        return 0
    url = os.getenv("MIGRATION_DATABASE_URL")
    if not url:
        parser.error(
            "Defina MIGRATION_DATABASE_URL no ambiente; não forneça credenciais nos argumentos."
        )
    try:
        import psycopg

        # Require a new private directory, not a pre-existing/symlink destination.
        args.output.mkdir(mode=0o700)
        os.chmod(args.output, 0o700)
        url = url.replace("postgresql+psycopg://", "postgresql://", 1)
        config = {
            key: value
            for key, value in vars(args).items()
            if key not in ("apply", "output")
        }
        with (
            psycopg.connect(url, **connection_options(url)) as connection,
            connection.transaction(),
        ):
            artifact = provision(connection, **config)
            write_artifacts(args.output, artifact)
    except Exception:  # noqa: BLE001 - no DSN, claim token, or key in terminal logs
        print(
            "Provisionamento não confirmado. Verifique o banco e a pasta privada antes de repetir; "
            "nenhum equipamento existente foi sobrescrito.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Ponto {artifact['connector_id']} provisionado e inativo. Artefatos privados: {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
