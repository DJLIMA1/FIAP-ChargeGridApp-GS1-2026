import importlib.util
import sys
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

TOOLS = Path(__file__).parents[1]
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("set_central_rent", TOOLS / "set_central_rent.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
STATION = UUID("00000000-0000-4000-8000-000000000301")
NOVEMBER = date(2026, 11, 1)


class Connection:
    """``results``: respostas de ``fetchone`` na ordem das consultas."""

    def __init__(self, *results, rowcount=1):
        self.results, self.rowcount, self.queries = list(results), rowcount, []

    @contextmanager
    def transaction(self):
        yield

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, query, params):
        self.queries.append((query, params))

    def fetchone(self):
        return self.results.pop(0) if self.results else None


def test_preview_of_platform_default_only_reads():
    connection = Connection(None)
    assert module.set_rent(connection, None, "99", NOVEMBER) == (None, Decimal("99.00"), "preview")
    assert len(connection.queries) == 1 and "FOR UPDATE" not in connection.queries[0][0]


def test_apply_inserts_a_new_effective_rate():
    connection = Connection(None)
    assert module.set_rent(connection, None, "99,9", NOVEMBER, apply=True)[2] == "updated"
    query, params = connection.queries[-1]
    assert query.startswith("INSERT INTO central_rent_rates") and params[:3] == (None, Decimal("99.90"), NOVEMBER)


def test_station_override_updates_same_date_and_back_to_default():
    connection = Connection((1,), (Decimal("60.00"),))
    assert module.set_rent(connection, STATION, "padrao", NOVEMBER, apply=True) == (Decimal("60.00"), None, "updated")
    assert connection.queries[-1][0].startswith("UPDATE central_rent_rates") and connection.queries[-1][1][0] is None
    assert module.set_rent(Connection((1,), (Decimal("60.00"),)), STATION, "60", NOVEMBER, apply=True)[2] == "unchanged"


def test_refusals():
    with pytest.raises(module.RentError):
        module.set_rent(Connection(None), STATION, "60", NOVEMBER)  # posto não encontrado
    with pytest.raises(module.RentError):
        module.clean_amount("padrao")  # padrão precisa de valor
    for bad in ("-1", "10000.01", "abc", "NaN"):
        with pytest.raises(module.RentError):
            module.clean_amount(bad)
    with pytest.raises(module.RentError):
        module.set_rent(Connection(None, rowcount=0), None, "99", NOVEMBER, apply=True)


def test_next_month_and_credentials_only_in_environment(monkeypatch):
    assert module.next_month(date(2026, 12, 15)) == date(2027, 1, 1)
    assert module.next_month(date(2026, 10, 22)) == NOVEMBER
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit):
        module.main(["--amount", "99"])
