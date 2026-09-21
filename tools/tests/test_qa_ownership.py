import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def qa(tmp_path, monkeypatch):
    tools_path = Path(__file__).parents[1]
    monkeypatch.syspath_prepend(str(tools_path))
    spec = importlib.util.spec_from_file_location(
        "qa_live_ownership_test", tools_path / "qa_live.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    instance = module.Acceptance.__new__(module.Acceptance)
    instance.state = {}
    instance.state_path = tmp_path / "qa-state.json"
    instance.login = lambda kind: None
    instance.checked = lambda name: None
    return instance


def test_qa_preserves_existing_equipment_without_writes(qa):
    qa.state = {
        "station": "legacy",
        "simulator": {"connector_id": "one", "device_key": "old-one"},
        "panel": {"connector_id": "two", "device_key": "old-two"},
    }
    calls = []

    def call(method, path, **kwargs):
        calls.append((method, path))
        return {"operator_enabled": True}

    qa.call = call
    qa.provision()
    assert calls == [("GET", "me")]
    assert qa.state["panel"]["device_key"] == "old-two"


def test_qa_requires_explicit_factory_bundles_before_any_mutation(qa, monkeypatch):
    monkeypatch.delenv("CHARGEGRID_QA_FACTORY_SIMULATOR", raising=False)
    qa.call = lambda *args, **kwargs: pytest.fail("No API call should happen")
    with pytest.raises(ValueError, match="Missing explicit private factory artifact"):
        qa.provision()
    assert not qa.state_path.exists()


def test_qa_claims_factory_points_without_creating_devices_via_api(
    qa, tmp_path, monkeypatch
):
    calls = []
    for kind in ("simulator", "panel"):
        artifact = {
            "claim_token": kind + "-claim",
            "connector_id": kind + "-point",
            "device_id": kind + "-device",
            "device_key": kind + "-key",
            "public_code": kind + "-code",
        }
        path = tmp_path / (kind + ".json")
        path.write_text(json.dumps(artifact))
        monkeypatch.setenv("CHARGEGRID_QA_FACTORY_" + kind.upper(), str(path))

    def call(method, path, **kwargs):
        calls.append((method, path, kwargs.get("body")))
        if path == "ownership/claim":
            kind = kwargs["body"]["token"].split("-")[0]
            return {"station_id": "claimed-station", "connector_id": kind + "-point"}
        return {"operator_enabled": True}

    qa.call = call
    qa.provision()
    posts = [(path, body) for method, path, body in calls if method == "POST"]
    assert posts == [
        ("ownership/claim", {"token": "simulator-claim"}),
        ("ownership/claim", {"token": "panel-claim", "station_id": "claimed-station"}),
    ]
    assert qa.state["panel"]["device_key"] == "panel-key"
    assert "claim_token" not in qa.state_path.read_text()
