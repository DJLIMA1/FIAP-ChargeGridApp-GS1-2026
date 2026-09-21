"""Count expired records; --apply deletes them in one database transaction."""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone


def maintain(connection, apply=False, now=None):
    now = now or datetime.now(timezone.utc)
    # Replay/boot state and idempotency records deliberately have no retention here.
    targets = [
        ("telemetry_samples", "received_at", now - timedelta(days=7)),
        ("request_limits", "expires_at", now),
    ]
    counts = {}
    with connection.cursor() as cursor:
        for table, column, cutoff in targets:
            cursor.execute(
                f"SELECT count(*) FROM {table} WHERE {column} < %s", (cutoff,)
            )
            counts[table] = cursor.fetchone()[0]
        if apply:
            for table, column, cutoff in targets:
                cursor.execute(f"DELETE FROM {table} WHERE {column} < %s", (cutoff,))
                counts[table] = cursor.rowcount
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Excluir registros vencidos; padrão é prévia.",
    )
    args = parser.parse_args()
    url = os.getenv("DATABASE_URL")
    if not url:
        parser.error(
            "Defina DATABASE_URL; nunca forneça credenciais na linha de comando."
        )
    try:
        import psycopg

        url = url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(url) as connection:
            counts = maintain(connection, args.apply)
        print(
            ("Aplicado" if args.apply else "Prévia")
            + ": "
            + ", ".join(f"{table}={count}" for table, count in counts.items())
        )
    except Exception:  # noqa: BLE001 - ensure safe rollback message for any DB failure
        print(
            "Manutenção falhou; a transação foi revertida. Verifique configuração e banco.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
