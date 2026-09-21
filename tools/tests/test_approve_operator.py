import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

PATH = Path(__file__).parents[1] / "approve_operator.py"
SPEC = importlib.util.spec_from_file_location("approve_operator", PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
PROFILE_ID = UUID("00000000-0000-4000-8000-000000000103")


class Connection:
    def __init__(self, profile=("vendor", False), rowcount=1):
        self.profile = profile
        self.rowcount = rowcount
        self.queries = []
        self.committed = False
        self.rolled_back = False

    @contextmanager
    def transaction(self):
        try:
            yield
        except Exception:
            self.rolled_back = True
            raise
        else:
            self.committed = True

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, query, params):
        self.queries.append((query, params))

    def fetchone(self):
        return self.profile


def test_preview_only_reads_exact_vendor_uuid():
    connection = Connection()
    assert module.approve(connection, PROFILE_ID) == "pending"
    assert len(connection.queries) == 1
    query, params = connection.queries[0]
    assert query.startswith("SELECT") and "FOR UPDATE" not in query
    assert params == (PROFILE_ID,)
    assert str(PROFILE_ID) not in query


def test_apply_locks_and_updates_only_selected_vendor():
    connection = Connection()
    assert module.approve(connection, str(PROFILE_ID), apply=True) == "approved"
    assert connection.queries[0][0].endswith("FOR UPDATE")
    query, params = connection.queries[1]
    assert "WHERE id = %s AND account_type = %s" in query
    assert params == (PROFILE_ID, "vendor")
    assert connection.committed


@pytest.mark.parametrize("profile", [None, ("consumer", False), ("consumer", True)])
def test_missing_or_consumer_account_cannot_be_approved(profile):
    connection = Connection(profile)
    with pytest.raises(module.ApprovalError):
        module.approve(connection, PROFILE_ID, apply=True)
    assert len(connection.queries) == 1
    assert connection.rolled_back


def test_repeated_approval_does_not_write():
    connection = Connection(("vendor", True))
    assert module.approve(connection, PROFILE_ID, apply=True) == "already_approved"
    assert len(connection.queries) == 1


def test_unexpected_update_count_rolls_back():
    connection = Connection(rowcount=0)
    with pytest.raises(module.ApprovalError):
        module.approve(connection, PROFILE_ID, apply=True)
    assert connection.rolled_back


def test_invalid_uuid_is_rejected_before_query():
    connection = Connection()
    with pytest.raises(ValueError):
        module.approve(connection, "not-a-uuid", apply=True)
    assert connection.queries == []


def test_cli_requires_explicit_environment(monkeypatch, capsys):
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as error:
        module.main([str(PROFILE_ID)])
    assert error.value.code == 2
    assert "MIGRATION_DATABASE_URL" in capsys.readouterr().err


def test_cli_never_exposes_connection_error_secrets(monkeypatch, capsys):
    secret_url = "postgresql://admin:secret@db.example/postgres"
    monkeypatch.setenv("MIGRATION_DATABASE_URL", secret_url)

    def failed_connect(*args, **kwargs):
        raise RuntimeError(secret_url)

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=failed_connect))
    assert module.main([str(PROFILE_ID), "--apply"]) == 1
    output = capsys.readouterr()
    assert "secret" not in output.err and "admin" not in output.err
    assert not output.out


def test_supabase_tls_verification_keeps_explicit_ca_and_never_disables_tls():
    url = (
        "postgresql://aws-0-sa-east-1.pooler.supabase.com/postgres?sslmode=verify-full"
    )
    options = module.connection_options(url)
    assert Path(options["sslrootcert"]).is_file()
    assert "sslmode" not in options
    assert "sslrootcert" not in module.connection_options(
        url + "&sslrootcert=/custom/ca.pem"
    )
    assert "sslrootcert" not in module.connection_options(
        "postgresql://localhost/chargegrid_test"
    )
