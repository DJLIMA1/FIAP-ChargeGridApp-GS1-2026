"""Preview or change the platform commission of one station (administrator only; never loads .env).

The commission is a contract term: the owner reads it in the panel but cannot change it.
New charging sessions copy the station value when they start; past sessions keep theirs.

Usage (credentials only in the environment):
    MIGRATION_DATABASE_URL=... python tools/set_platform_fee.py <station_uuid> --percent 20 [--apply]
"""

import argparse
import os
import sys
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID

from approve_operator import connection_options


class FeeError(ValueError):
    """A safe explanation for refusing the change."""


def clean_percent(value) -> Decimal:
    try:
        number = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        raise FeeError("Informe a comissão em porcentagem, por exemplo 25 ou 12,5.") from None
    if not number.is_finite() or not Decimal(0) <= number <= Decimal(100):
        raise FeeError("A comissão vai de 0% a 100%.")
    return number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def set_fee(connection, station_id, percent, apply=False):
    """``(anterior, nova, status)``; ``status``: ``preview`` | ``unchanged`` | ``updated``."""
    station_id = UUID(str(station_id))
    percent = clean_percent(percent)
    with connection.transaction(), connection.cursor() as cursor:
        query = "SELECT platform_fee_percent FROM stations WHERE id = %s"
        if apply:
            query += " FOR UPDATE"
        cursor.execute(query, (station_id,))
        found = cursor.fetchone()
        if found is None:
            raise FeeError("Posto não encontrado.")
        current = Decimal(found[0])
        if current == percent:
            return current, percent, "unchanged"
        if not apply:
            return current, percent, "preview"
        cursor.execute("UPDATE stations SET platform_fee_percent = %s WHERE id = %s", (percent, station_id))
        if cursor.rowcount != 1:
            raise FeeError("Alteração não aplicada; a transação foi revertida.")
        return current, percent, "updated"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("station_id", type=UUID, help="UUID exato do posto.")
    parser.add_argument("--percent", required=True, help="Nova comissão da plataforma (0 a 100).")
    parser.add_argument("--apply", action="store_true", help="Aplicar; sem esta opção apenas mostra a prévia.")
    args = parser.parse_args(argv)
    url = os.getenv("MIGRATION_DATABASE_URL")
    if not url:
        parser.error("Defina MIGRATION_DATABASE_URL no ambiente; não forneça credenciais nos argumentos.")
    try:
        clean_percent(args.percent)
        import psycopg

        url = url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(url, **connection_options(url)) as connection:
            current, new, status = set_fee(connection, args.station_id, args.percent, args.apply)
    except FeeError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - do not leak DSNs or database exception details
        print("Não foi possível alterar a comissão. Nenhuma alteração foi confirmada.", file=sys.stderr)
        return 1
    messages = {
        "preview": f"Prévia: comissão {current}% -> {new}%; execute com --apply para gravar.",
        "unchanged": f"Comissão já é {current}%; nenhuma alteração necessária.",
        "updated": f"Comissão alterada de {current}% para {new}%. Vale para as próximas recargas.",
    }
    print(f"Posto {args.station_id}: {messages[status]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
