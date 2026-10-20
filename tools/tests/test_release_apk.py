import importlib.util
from pathlib import Path

import pytest


def load_module():
    path = Path(__file__).parents[1] / "release_apk.py"
    spec = importlib.util.spec_from_file_location("release_apk", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PYPROJECT = '[project]\nname = "x"\nversion = "0.6.3"\n\n[tool.flet]\nbuild_number = 31\n'


def test_version_bump_touches_only_version_and_build():
    module = load_module()
    assert module.current(PYPROJECT) == ("0.6.3", 31)
    assert module.current(module.bumped(PYPROJECT, "0.6.4", 32)) == ("0.6.4", 32)
    assert 'name = "x"' in module.bumped(PYPROJECT, "0.6.4", 32)
    assert module.parse("0.6.10") > module.parse("0.6.9")
    with pytest.raises(SystemExit):
        module.parse("0.6")


def test_setup_note_goes_above_the_previous_release():
    module = load_module()
    doc = "# Setup\n\nTexto.\n\nO APK 0.6.3 (build 31) está em `builds/chargegrid-0.6.3.apk`.\n"
    note = module.setup_note("0.6.4", 32, "abc", "Atualizador no app.")
    result = module.with_note(doc, note)
    assert result.index("O APK 0.6.4 (build 32)") < result.index("O APK 0.6.3 (build 31)")
    assert "`app/chargegrid-0.6.4.apk`" in result and "Atualizador no app." in result


def test_manifest_has_what_the_api_validates(tmp_path):
    module = load_module()
    apk = tmp_path / "chargegrid-0.6.7.apk"
    apk.write_bytes(b"apk")
    data = module.manifest("0.6.7", 35, "https://x.public.blob.vercel-storage.com/app/chargegrid-0.6.7.apk", apk,
                           "a" * 64, "  Novidades. ")
    assert (data["version"], data["build"], data["size_bytes"], data["notes"]) == ("0.6.7", 35, 3, "Novidades.")
    assert data["url"].endswith(".apk") and data["published_at"].endswith("+00:00")


BLOB_LIST = """
  Uploaded At     Size          Pathname                     URL
  12h             172510946     app/chargegrid-0.7.0.apk     https://x.public.blob.vercel-storage.com/app/chargegrid-0.7.0.apk
  2h              173719257     app/chargegrid-0.7.1.apk     https://x.public.blob.vercel-storage.com/app/chargegrid-0.7.1.apk
  1m              173730613     app/chargegrid-0.8.0.apk     https://x.public.blob.vercel-storage.com/app/chargegrid-0.8.0.apk
  1m              484           app/latest.json              https://x.public.blob.vercel-storage.com/app/latest.json
"""


def test_old_apks_are_listed_for_deletion_except_the_new_one_and_the_manifest():
    module = load_module()
    urls = module.old_apk_urls(BLOB_LIST, "app/chargegrid-0.8.0.apk")
    assert urls == ["https://x.public.blob.vercel-storage.com/app/chargegrid-0.7.0.apk",
                    "https://x.public.blob.vercel-storage.com/app/chargegrid-0.7.1.apk"]


def test_delete_old_apks_deletes_each_old_url_and_never_the_new_one(monkeypatch):
    module = load_module()
    calls = []

    def fake_cli(args, token):
        calls.append(args)
        return (0, BLOB_LIST) if args[0] == "list" else (0, "Success")

    monkeypatch.setattr(module, "_blob_cli", fake_cli)
    removed = module.delete_old_apks("tok", "app/chargegrid-0.8.0.apk")
    assert len(removed) == 2
    deleted = [args[1] for args in calls if args[0] == "del"]
    assert all("0.8.0" not in url and "latest.json" not in url for url in deleted)


def test_delete_old_apks_only_warns_when_listing_fails(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "_blob_cli", lambda args, token: (1, "Error: store suspended"))
    assert module.delete_old_apks("tok", "app/chargegrid-0.8.0.apk") == []
