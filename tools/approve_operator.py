"""Preview or approve one persisted vendor account by UUID; never load .env files."""

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID


class ApprovalError(ValueError):
    """A safe, non-personal explanation for refusing an approval."""


def approve(connection, profile_id, apply=False):
    profile_id = UUID(str(profile_id))
    with connection.transaction(), connection.cursor() as cursor:
        query = "SELECT account_type, operator_enabled FROM profiles WHERE id = %s"
        if apply:
            query += " FOR UPDATE"
        cursor.execute(query, (profile_id,))
        profile = cursor.fetchone()
        if profile is None:
            raise ApprovalError(
                "Perfil não encontrado; a conta precisa concluir o primeiro acesso."
            )
        account_type, enabled = profile
        if account_type != "vendor":
            raise ApprovalError(
                "Aprovação recusada: somente contas de vendedor podem ser aprovadas."
            )
        if enabled:
            return "already_approved"
        if not apply:
            return "pending"
        cursor.execute(
            "UPDATE profiles SET operator_enabled = TRUE WHERE id = %s AND account_type = %s",
            (profile_id, "vendor"),
        )
        if cursor.rowcount != 1:
            raise ApprovalError("Aprovação não aplicada; a transação foi revertida.")
        return "approved"


def connection_options(url):
    options = {"connect_timeout": 10, "prepare_threshold": None}
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    # Reuse the project's public CA for Supabase verify-full connections without
    # loading application settings (which would implicitly read secret .env files).
    if (
        (parsed.hostname or "").endswith((".supabase.com", ".supabase.co"))
        and query.get("sslmode") == ["verify-full"]
        and "sslrootcert" not in query
    ):
        options["sslrootcert"] = str(
            Path(__file__).resolve().parents[1]
            / "apps/api/certs/supabase-prod-ca-2021.crt"
        )
    return options


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "profile_id", type=UUID, help="UUID exato do perfil de vendedor a aprovar."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplicar aprovação; sem esta opção apenas consulta.",
    )
    args = parser.parse_args(argv)
    url = os.getenv("MIGRATION_DATABASE_URL")
    if not url:
        parser.error(
            "Defina MIGRATION_DATABASE_URL no ambiente; não forneça credenciais nos argumentos."
        )
    try:
        import psycopg

        url = url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(url, **connection_options(url)) as connection:
            result = approve(connection, args.profile_id, args.apply)
    except ApprovalError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - do not leak DSNs or database exception details
        print(
            "Não foi possível aprovar. Nenhuma alteração foi confirmada; verifique o banco e a configuração.",
            file=sys.stderr,
        )
        return 1
    messages = {
        "pending": "Prévia: vendedor pendente; execute com --apply para aprovar.",
        "already_approved": "Vendedor já aprovado; nenhuma alteração necessária.",
        "approved": "Vendedor aprovado. Entre novamente no app para abrir a gestão de postos.",
    }
    print(f"Perfil {args.profile_id}: {messages[result]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
