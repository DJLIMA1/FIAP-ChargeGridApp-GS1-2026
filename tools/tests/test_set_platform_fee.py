import importlib.util
import sys
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

TOOLS = Path(__file__).parents[1]
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("set_platform_fee", TOOLS / "set_platform_fee.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
STATION = UUID("00000000-0000-4000-8000-000000000201")


class Connection:
    def __init__(self, current=Decimal("25.00"), rowcount=1):
        self.current, self.rowcount, self.queries, self.committed = current, rowcount, [], False

    @contextmanager
    def transaction(self):
        yield
        self.committed = True

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, query, params):
        self.queries.append((query, params))

    def fetchone(self):
        return None if self.current is None else (self.current,)


def test_preview_only_reads():
    connection = Connection()
    assert module.set_fee(connection, STATION, "20") == (Decimal("25.00"), Decimal("20.00"), "preview")
    assert len(connection.queries) == 1 and "FOR UPDATE" not in connection.queries[0][0]


def test_apply_locks_and_updates_only_the_station():
    connection = Connection()
    assert module.set_fee(connection, str(STATION), "12,5", apply=True)[2] == "updated"
    assert connection.queries[0][0].endswith("FOR UPDATE")
    assert connection.queries[1] == ("UPDATE stations SET platform_fee_percent = %s WHERE id = %s",
                                     (Decimal("12.50"), STATION))


def test_unchanged_and_missing_station():
    assert module.set_fee(Connection(), STATION, "25", apply=True)[2] == "unchanged"
    with pytest.raises(module.FeeError):
        module.set_fee(Connection(current=None), STATION, "20", apply=True)
    with pytest.raises(module.FeeError):
        module.set_fee(Connection(rowcount=0), STATION, "20", apply=True)


@pytest.mark.parametrize("value", ["-1", "100.01", "abc", "NaN"])
def test_invalid_percent(value):
    with pytest.raises(module.FeeError):
        module.clean_percent(value)


def test_main_requires_credentials_in_environment(monkeypatch, capsys):
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit):
        module.main([str(STATION), "--percent", "20"])
