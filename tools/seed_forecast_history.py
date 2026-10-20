"""Histórico SINTÉTICO rotulado para demonstrar a previsão num posto (prévia por padrão).

Grava em ``connector_hourly_stats`` linhas com ``origin = 'synthetic'`` (gerador
``syn-v1`` de ``chargegrid_core.forecast.synthetic``) para os conectores ativos de um posto.
Não cria sessões: receita, energia e sessões do painel continuam vindo só de dados reais.
Onde houver dado real na mesma hora, o real vence. Toda tela que usar estas linhas mostra
"Inclui histórico sintético".

Uso (DATABASE_URL no ambiente; nunca na linha de comando):

    python tools/seed_forecast_history.py --station <uuid>                 # prévia
    python tools/seed_forecast_history.py --station <uuid> --apply         # grava
    python tools/seed_forecast_history.py --station <uuid> --purge --apply # remove só o sintético

Atenção: confira o host exibido na prévia antes de usar ``--apply``.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "chargegrid_core"))

from chargegrid_core.forecast import synthetic  # noqa: E402
from chargegrid_core.forecast.aggregate import floor_hour  # noqa: E402
from chargegrid_core.forecast.calendar import to_local  # noqa: E402

ARCHETYPES = tuple(synthetic.ARCHETYPES)


def plan(station_id: str, connectors: list[tuple[str, float]], days: int, archetype: str, seed: int, now=None):
    """Linhas sintéticas para os ``days`` dias que terminam na hora local atual."""
    now = now or datetime.now(timezone.utc)
    end = floor_hour(to_local(now))
    start = (end - timedelta(days=days)).replace(hour=0)
    profile = {
        "index": int(uuid.UUID(station_id)) % 1_000_000, "archetype": archetype, "connectors": len(connectors),
        "scale": 1.0, "growth": 0.01, "power_kw": max(power for _, power in connectors) if connectors else 7.4,
        "schedule": None, "seed": seed, "ramp_days": 0,
    }
    span = (end - start).days + 1
    rows = synthetic.station_rows(profile, start, span, [cid for cid, _ in connectors])
    limit = end.replace(tzinfo=None)
    return [row for row in rows if to_local(row["hour_start"]) < limit]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--station", required=True, help="UUID do posto")
    parser.add_argument("--days", type=int, default=56, help="Dias de histórico sintético (padrão 56)")
    parser.add_argument("--archetype", choices=ARCHETYPES, default="shopping")
    parser.add_argument("--seed", type=int, default=20261020)
    parser.add_argument("--purge", action="store_true", help="Remove só as linhas sintéticas do posto")
    parser.add_argument("--apply", action="store_true", help="Grava (sem isto, apenas prévia)")
    args = parser.parse_args()
    url = os.getenv("DATABASE_URL")
    if not url:
        parser.error("Defina DATABASE_URL; nunca forneça credenciais na linha de comando.")
    try:
        station_id = str(uuid.UUID(args.station))
    except ValueError:
        parser.error("Informe o UUID do posto.")
    if not 1 <= args.days <= 120:
        parser.error("Escolha de 1 a 120 dias.")
    import psycopg

    url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    print(f"Banco: {urlsplit(url).hostname} · posto {station_id}")
    with psycopg.connect(url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT name FROM stations WHERE id = %s", (station_id,))
        found = cursor.fetchone()
        if not found:
            print("Posto não encontrado.", file=sys.stderr)
            return 1
        cursor.execute("SELECT id::text, COALESCE(power_limit_kw, power_kw) FROM connectors "
                       "WHERE station_id = %s AND active ORDER BY public_code", (station_id,))
        connectors = [(cid, float(power)) for cid, power in cursor.fetchall()]
        ids = [cid for cid, _ in connectors]
        cursor.execute("SELECT count(*) FROM connector_hourly_stats WHERE origin = 'synthetic' "
                       "AND connector_id = ANY(%s::uuid[])", (ids,))
        existing = cursor.fetchone()[0]
        if args.purge:
            print(f"{found[0]}: {existing} linha(s) sintética(s) a remover.")
            if args.apply:
                cursor.execute("DELETE FROM connector_hourly_stats WHERE origin = 'synthetic' "
                               "AND connector_id = ANY(%s::uuid[])", (ids,))
                print(f"Removidas: {cursor.rowcount}.")
            return 0
        if not connectors:
            print("Posto sem conectores ativos.", file=sys.stderr)
            return 1
        rows = plan(station_id, connectors, args.days, args.archetype, args.seed)
        print(f"{found[0]}: {len(connectors)} conector(es), {len(rows)} hora(s) sintéticas "
              f"({args.archetype}, {args.days} dias); já existem {existing} linha(s) sintética(s).")
        if not args.apply:
            print("Prévia: nada foi gravado. Use --apply para gravar.")
            return 0
        cursor.execute("DELETE FROM connector_hourly_stats WHERE origin = 'synthetic' "
                       "AND connector_id = ANY(%s::uuid[])", (ids,))
        cursor.executemany(
            "INSERT INTO connector_hourly_stats (connector_id, hour_start, origin, busy_seconds, energy_wh, "
            "energy_basis, sessions_started, max_power_w, generator, computed_at) VALUES (%s, %s, 'synthetic', %s, %s, "
            "'synthetic', %s, NULL, %s, now())",
            [(row["connector_id"], row["hour_start"], row["busy_seconds"], row["energy_wh"],
              row["sessions_started"], synthetic.VERSION) for row in rows])
        print(f"Gravadas {len(rows)} linha(s) sintética(s) rotuladas ({synthetic.VERSION}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
