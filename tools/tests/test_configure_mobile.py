import importlib.util
import json
from pathlib import Path


def load_module():
    path = Path(__file__).parents[1] / "configure_mobile.py"
    spec = importlib.util.spec_from_file_location("configure_mobile", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mobile_configuration_contains_only_public_api_url(tmp_path):
    env_file = tmp_path / ".env"
    output = tmp_path / "assets" / "app_config.json"
    env_file.write_text(
        "DATABASE_URL=postgresql://user:private-password@example.test/database\n"
        "SUPABASE_ANON_KEY=public-key\n"
        "CHARGEGRID_API_URL=https://api.example.test/v1\n",
        encoding="utf-8",
    )

    load_module().configure_mobile(env_file, output)

    assert json.loads(output.read_text(encoding="utf-8")) == {
        "api_url": "https://api.example.test/v1"
    }
    assert "private-password" not in output.read_text(encoding="utf-8")
