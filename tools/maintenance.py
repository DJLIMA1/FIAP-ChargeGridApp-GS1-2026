"""Count expired records; --apply deletes them in one database transaction.

Telemetry older than 7 days is removed only after the hourly aggregates
(``connector_hourly_stats``) have closed those hours (``aggregate_watermarks``).
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone


WATERMARK = "connector_hourly_stats"
ROLLUP_MARGIN = timedelta(hours=72)


def telemetry_cutoff(cursor, cutoff):
    """Telemetria só sai depois de entrar nos agregados horários duráveis.

    Limite = o menor entre 7 dias e a marca d'água do rollup (``aggregate_watermarks``)
    menos as 72 h que o rollup diário recalcula.
    Sem a tabela (migração ainda não aplicada) vale o limite antigo; com a tabela e sem
    marca (rollup nunca rodou), nenhuma telemetria é apagada.
    """
    cursor.execute("SELECT to_regclass('aggregate_watermarks') IS NOT NULL", None)
    if not cursor.fetchone()[0]:
        return cutoff
    cursor.execute("SELECT rolled_until FROM aggregate_watermarks WHERE name = %s", (WATERMARK,))
    row = cursor.fetchone()
    if not row or row[0] is None:
        return None
    return min(cutoff, row[0] - ROLLUP_MARGIN)


def maintain(connection, apply=False, now=None):
    now = now or datetime.now(timezone.utc)
    counts = {}
    with connection.cursor() as cursor:
        telemetry = telemetry_cutoff(cursor, now - timedelta(days=7))
        # Replay/boot state and idempotency records deliberately have no retention here.
        targets = [("request_limits", "expires_at", now)]
        if telemetry is None:
            counts["telemetry_samples"] = "retida (agregados ainda não fechados)"
        else:
            targets.insert(0, ("telemetry_samples", "received_at", telemetry))
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
