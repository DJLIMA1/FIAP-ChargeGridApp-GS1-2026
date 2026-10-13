import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "sync_core", Path(__file__).resolve().parents[1] / "sync_core.py")
sync_core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_core)


def test_vendored_core_copies_match_source():
    assert sync_core.differences() == [], "rode: python tools/sync_core.py"
