import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def load_module():
    path = Path(__file__).parents[1] / "build_dashboard_web.py"
    spec = importlib.util.spec_from_file_location("build_dashboard_web", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stage_bundles_dashboard_and_shared_code_without_private_files(tmp_path):
    module = load_module()
    staging = module.stage(tmp_path / "web-src")
    assert (staging / "main.py").is_file()
    assert (staging / "chargegrid_dashboard" / "app.py").is_file()
    assert (staging / "src" / "chargegrid_app" / "web_transport.py").is_file()
    assert (staging / "src" / "chargegrid_core" / "analytics.py").is_file()
    assert not list(staging.rglob("demo_ai.py"))
    assert (staging / "src" / "chargegrid_app" / "services" / "demo_ai_bridge.py").is_file()
    assert not list(staging.rglob("__pycache__"))
    assert not list(staging.rglob(".env*"))
    assert {p.name for p in (staging / "assets").iterdir()} == set(module.ASSETS)
    assert json.loads((staging / "dashboard_config.json").read_text()) == {"demo": True}


def test_stage_options_and_restaging_keep_flutter_cache(tmp_path):
    module = load_module()
    staging = tmp_path / "web-src"
    module.stage(staging)
    (staging / "build" / "flutter").mkdir(parents=True)
    (staging / "stale.txt").write_text("x")
    module.stage(staging, demo=False, api_url="https://api.example.test/v1")
    assert (staging / "build" / "flutter").is_dir()
    assert not (staging / "stale.txt").exists()
    config = json.loads((staging / "dashboard_config.json").read_text())
    assert config == {"demo": False, "api_url": "https://api.example.test/v1"}


def fake_output(tmp_path, files):
    output = tmp_path / "web"
    (output / "assets" / "app").mkdir(parents=True)
    with zipfile.ZipFile(output / "assets" / "app" / "app.zip", "w") as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)
    (output / "index.html").write_text("<html></html>")
    return output


def test_verify_rejects_private_preview_and_secrets(tmp_path):
    module = load_module()
    ok = {"main.pyc": b"", "dashboard_config.json": b'{"demo": true}'}
    module.verify(fake_output(tmp_path / "ok", ok))
    with pytest.raises(SystemExit, match="privados"):
        module.verify(fake_output(tmp_path / "ai", {**ok, "src/chargegrid_app/services/demo_ai.pyc": b""}))
    with pytest.raises(SystemExit, match="segredo"):
        module.verify(fake_output(tmp_path / "key", {**ok, "x.txt": b"OPENROUTER_API_KEY=abc"}))
    with pytest.raises(SystemExit, match="dashboard_config"):
        module.verify(fake_output(tmp_path / "cfg", {"main.pyc": b""}))


def test_prepare_deploy_copies_site_prunes_debug_files_and_keeps_vercel_link(tmp_path):
    module = load_module()
    output = fake_output(tmp_path, {"main.pyc": b""})
    (output / "canvaskit").mkdir()
    (output / "canvaskit" / "canvaskit.wasm").write_bytes(b"w")
    (output / "canvaskit" / "canvaskit.js.symbols").write_text("s")
    (output / "pyodide").mkdir()
    (output / "pyodide" / "python.exe").write_bytes(b"x")
    (output / "pyodide" / "pyodide.asm.wasm").write_bytes(b"w")
    deploy = tmp_path / "vercel"
    (deploy / ".vercel").mkdir(parents=True)
    (deploy / ".vercel" / "project.json").write_text("{}")
    module.prepare_deploy(output, deploy)
    public = deploy / "public"
    assert (public / "index.html").is_file() and (public / "canvaskit" / "canvaskit.wasm").is_file()
    assert not (public / "canvaskit" / "canvaskit.js.symbols").exists()
    assert not (public / "pyodide" / "python.exe").exists()
    assert (public / "pyodide" / "pyodide.asm.wasm").is_file()
    assert (deploy / ".vercel" / "project.json").is_file()
    assert json.loads((deploy / "vercel.json").read_text())["outputDirectory"] == "public"


def test_vercel_config_proxies_api_same_origin_and_caches_sensibly():
    config = json.loads((ROOT / "apps" / "dashboard" / "vercel.json").read_text())
    rewrites = config["rewrites"]
    assert rewrites[0]["source"] == "/v1/:path*"
    assert rewrites[0]["destination"].startswith("https://") and rewrites[0]["destination"].endswith("/v1/:path*")
    assert rewrites[-1]["destination"] == "/index.html"
    rules = {rule["source"]: {h["key"]: h["value"] for h in rule["headers"]} for rule in config["headers"]}
    assert "max-age=604800" in rules["/pyodide/(.*)"]["Cache-Control"]
    no_cache = next(source for source, headers in rules.items() if headers.get("Cache-Control") == "no-cache")
    for name in ("index.html", "main.dart.js", "assets/app/"):
        assert name in no_cache
