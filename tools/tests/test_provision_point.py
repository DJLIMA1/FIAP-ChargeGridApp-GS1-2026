import hashlib
import json
import os
import stat
from contextlib import contextmanager
from decimal import Decimal

import pytest

from tools import provision_point as module
from tools.tests.test_admin_tools import require_test_database_url


class Connection:
    def __init__(self):
        self.queries = []

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, query, params):
        self.queries.append((query, params))


def test_factory_creates_only_new_inactive_equipment_and_stores_hashes():
    connection = Connection()
    artifact = module.provision(connection, public_code="FACTORY-TEST")
    assert len(connection.queries) == 4
    assert all(query.startswith("INSERT INTO") for query, _ in connection.queries)
    station, point, device, claim = connection.queries
    assert "NULL" in station[0] and "FALSE" in station[0]
    assert "FALSE" in point[0]
    assert artifact["device_key"] != artifact["claim_token"]
    assert len(artifact["device_key"]) == len(artifact["claim_token"]) == 43
    assert (
        artifact["claim_url"] == "chargegrid://claim?token=" + artifact["claim_token"]
    )
    assert device[1][-1] == hashlib.sha256(artifact["device_key"].encode()).hexdigest()
    assert claim[1][-1] == hashlib.sha256(artifact["claim_token"].encode()).hexdigest()
    assert artifact["claim_token"] not in str(connection.queries)
    assert artifact["device_key"] not in str(connection.queries)


@pytest.mark.skipif(
    not os.getenv("CHARGEGRID_IMPORT_TEST_DATABASE_URL"),
    reason="banco descartável de provisionamento não configurado",
)
def test_factory_provisioning_works_on_migrated_schema_without_exporting_presence_seed():
    import psycopg

    database = os.environ["CHARGEGRID_IMPORT_TEST_DATABASE_URL"]
    require_test_database_url(database)
    with psycopg.connect(database) as connection, connection.transaction(force_rollback=True):
        artifact = module.provision(connection, public_code="FACTORY-PRESENCE-TEST")
        row = connection.execute(
            "SELECT presence_secret, owner_id, active FROM stations WHERE id = %s",
            (artifact["station_id"],),
        ).fetchone()
        assert len(bytes.fromhex(row[0])) == 32
        assert row[1:] == (None, False)
        assert row[0] not in str(artifact)
        assert "presence_secret" not in artifact


@pytest.mark.parametrize(
    "changes",
    [
        {"latitude": Decimal("NaN")},
        {"longitude": Decimal(181)},
        {"power_kw": Decimal(0)},
        {"price_per_kwh": Decimal(-1)},
        {"max_duration_minutes": 0},
        {"public_code": " "},
    ],
)
def test_invalid_factory_configuration_does_not_write(changes):
    connection = Connection()
    with pytest.raises(ValueError):
        module.provision(connection, **{"public_code": "FACTORY-TEST", **changes})
    assert connection.queries == []


def test_qr_and_credentials_private_and_never_overwritten(tmp_path):
    artifact = module.provision(Connection(), public_code="FACTORY-TEST")
    module.write_artifacts(tmp_path, artifact)
    config = tmp_path / "provisioning.json"
    qr = tmp_path / "ownership-qr.svg"
    assert json.loads(config.read_text()) == artifact
    assert b"<svg" in qr.read_bytes()
    assert (
        stat.S_IMODE(config.stat().st_mode) == stat.S_IMODE(qr.stat().st_mode) == 0o600
    )
    original = config.read_bytes()
    with pytest.raises(FileExistsError):
        module.write_artifacts(tmp_path, {**artifact, "device_key": "changed"})
    assert config.read_bytes() == original


def test_cli_preview_does_not_need_database_or_write(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    output = tmp_path / "private"
    assert module.main(["--public-code", "TEST", "--output", str(output)]) == 0
    assert not output.exists()
    assert "Prévia" in capsys.readouterr().out


def test_cli_does_not_leak_connection_error_or_reuse_output(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL", "postgresql://secret-user:secret-password@invalid/db"
    )
    output = tmp_path / "existing"
    output.mkdir()
    assert (
        module.main(["--public-code", "TEST", "--output", str(output), "--apply"]) == 1
    )
    logged = capsys.readouterr()
    assert "secret-password" not in logged.err + logged.out
    assert "secret-user" not in logged.err + logged.out
    assert list(output.iterdir()) == []
    assert os.getenv("MIGRATION_DATABASE_URL")
