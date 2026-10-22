"""Preview or change the monthly rent per central (administrator only; never loads .env).

The rent is a contract term: the owner reads it in the panel/app but cannot change it. It is
charged per linked central (the station screen), prorated by local day and deducted from the
owner's payout statement (``chargegrid_core.rent``). Rates have an effective date, so changing
the value never rewrites days before it.

Usage (credentials only in the environment):
    # platform default from 2026-11-01 (default date: first day of next month, São Paulo)
    MIGRATION_DATABASE_URL=... python tools/set_central_rent.py --amount 99 --from 2026-11-01 [--apply]
    # override for one station, or back to the default with --amount padrao
    MIGRATION_DATABASE_URL=... python tools/set_central_rent.py --station <uuid> --amount 60 [--apply]
"""

import argparse
import os
import sys
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID
from zoneinfo import ZoneInfo

from approve_operator import connection_options

MAX_RENT = Decimal("10000")
BACK_TO_DEFAULT = ("padrao", "padrão", "default")


class RentError(ValueError):
    """A safe explanation for refusing the change."""


def clean_amount(value, station_id=None) -> Decimal | None:
    """R$ 0 a R$ 10.000 por central; ``padrao`` (só com posto) = volta ao padrão (``None``)."""
    text = str(value).strip().lower()
    if text in BACK_TO_DEFAULT:
        if station_id is None:
            raise RentError("O padrão da plataforma precisa de um valor; 'padrao' só vale com --station.")
        return None
    try:
        number = Decimal(text.replace(",", "."))
    except (InvalidOperation, ValueError):
        raise RentError("Informe o aluguel mensal em reais, por exemplo 99 ou 99,90.") from None
    if not number.is_finite() or not Decimal(0) <= number <= MAX_RENT:
        raise RentError("O aluguel mensal vai de R$ 0,00 a R$ 10.000,00 por central.")
    return number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def next_month(today: date | None = None) -> date:
    today = today or datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    return date(today.year + (today.month == 12), today.month % 12 + 1, 1)


def clean_date(value) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise RentError("Informe a data de vigência como AAAA-MM-DD.") from None


def set_rent(connection, station_id, amount, effective, apply=False):
    """``(anterior, novo, status)``; ``status``: ``preview`` | ``unchanged`` | ``updated``.

    ``anterior`` é o valor já gravado para o mesmo posto/padrão e a mesma data (``None`` se não há).
    """
    station_id = UUID(str(station_id)) if station_id is not None else None
    amount = clean_amount(amount, station_id) if not isinstance(amount, Decimal) and amount is not None else amount
    if station_id is None and amount is None:
        raise RentError("O padrão da plataforma precisa de um valor.")
    effective = clean_date(effective) if not isinstance(effective, date) else effective
    with connection.transaction(), connection.cursor() as cursor:
        if station_id is not None:
            cursor.execute("SELECT 1 FROM stations WHERE id = %s", (station_id,))
            if cursor.fetchone() is None:
                raise RentError("Posto não encontrado.")
        query = ("SELECT monthly_amount FROM central_rent_rates WHERE station_id IS NOT DISTINCT FROM %s "
                 "AND effective_from = %s")
        if apply:
            query += " FOR UPDATE"
        cursor.execute(query, (station_id, effective))
        found = cursor.fetchone()
        current = Decimal(found[0]) if found and found[0] is not None else None
        if found is not None and current == amount:
            return current, amount, "unchanged"
        if not apply:
            return current, amount, "preview"
        if found is None:
            cursor.execute("INSERT INTO central_rent_rates (id, station_id, monthly_amount, effective_from, note) "
                           "VALUES (gen_random_uuid(), %s, %s, %s, %s)",
                           (station_id, amount, effective, "tools/set_central_rent.py"))
        else:
            cursor.execute("UPDATE central_rent_rates SET monthly_amount = %s WHERE station_id IS NOT DISTINCT FROM %s "
                           "AND effective_from = %s", (amount, station_id, effective))
        if cursor.rowcount != 1:
            raise RentError("Alteração não aplicada; a transação foi revertida.")
        return current, amount, "updated"


def _text(value):
    return "padrão da plataforma" if value is None else f"R$ {value}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--amount", required=True, help="Aluguel mensal por central (0 a 10000) ou 'padrao'.")
    parser.add_argument("--station", type=UUID, help="UUID do posto (sem esta opção: padrão da plataforma).")
    parser.add_argument("--from", dest="effective", help="Vigência AAAA-MM-DD (padrão: 1º dia do mês seguinte).")
    parser.add_argument("--apply", action="store_true", help="Aplicar; sem esta opção apenas mostra a prévia.")
    args = parser.parse_args(argv)
    url = os.getenv("MIGRATION_DATABASE_URL")
    if not url:
        parser.error("Defina MIGRATION_DATABASE_URL no ambiente; não forneça credenciais nos argumentos.")
    try:
        amount = clean_amount(args.amount, args.station)
        effective = clean_date(args.effective) if args.effective else next_month()
        import psycopg

        url = url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(url, **connection_options(url)) as connection:
            current, new, status = set_rent(connection, args.station, amount, effective, args.apply)
    except RentError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - do not leak DSNs or database exception details
        print("Não foi possível alterar o aluguel. Nenhuma alteração foi confirmada.", file=sys.stderr)
        return 1
    target = f"Posto {args.station}" if args.station else "Padrão da plataforma"
    messages = {
        "preview": f"Prévia: aluguel por central a partir de {effective}: {_text(new)}; execute com --apply "
                   "para gravar.",
        "unchanged": f"Aluguel a partir de {effective} já é {_text(current)}; nenhuma alteração necessária.",
        "updated": f"Aluguel por central a partir de {effective}: {_text(new)}. Descontado do repasse do dono.",
    }
    print(f"{target}: {messages[status]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
